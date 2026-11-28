import logging
import shutil
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from threading import Event, RLock, Thread
from zoneinfo import ZoneInfo

from home_automation.config.mic_settings import MODULE_ID_PATTERN
from home_automation.services.mic_recorder import (
    FILE_NAME_FORMAT,
    FILE_TIME_ZONE,
    SEGMENT_EXTENSION,
)
from home_automation.services.mic_settings_service import MicSettingsService


LOGGER = logging.getLogger("home_automation")

LOCAL_TIME_ZONE = ZoneInfo(FILE_TIME_ZONE)

# The age and size rules are applied this often.
CLEAN_INTERVAL_SECONDS = 60

# Free RAM is looked at this often. It is one cheap question to the
# system, and it must be asked often: the camera clips grow all the
# time, and the microphone sound has to give way before a clip is
# dropped.
RAM_CHECK_INTERVAL_SECONDS = 5

# The disk copy drops a camera clip when the RAM disk has less than
# archive_buffer_reserve_mb free. The microphone sound starts giving way
# this much earlier.
GIVE_WAY_MARGIN_MB = 50

# A file touched this recently may be the one a recorder is writing,
# even if the recorder has not told us its name yet.
FRESH_FILE_SECONDS = 10

# Two files of one run follow each other without a pause. Where one
# begins and the other ends can be worked out to well under a tenth of a
# second (measured), so files closer together than this are one stretch
# of sound, and anything more is shown as a hole.
SAME_STRETCH_SECONDS = 0.5

MEGABYTE = 1024 * 1024


def opus_seconds(path: Path) -> float:
    """
    How much sound an Opus file holds, read from the file itself: the
    position written in its last page, minus the start-up samples named
    in its first. Cheap enough to ask for every stored file. 0 when the
    file cannot be read as Opus.
    """

    try:
        with path.open("rb") as handle:
            head = handle.read(64)

            if head[:4] != b"OggS" or head[28:36] != b"OpusHead":
                return 0.0

            pre_skip = int.from_bytes(head[38:40], "little")

            handle.seek(0, 2)
            size = handle.tell()
            handle.seek(max(0, size - 65536))
            tail = handle.read()
    except OSError:
        return 0.0

    position = len(tail)

    while True:
        position = tail.rfind(b"OggS", 0, position)

        if position < 0:
            return 0.0

        # A real page start is followed by version 0.
        if position + 14 <= len(tail) and tail[position + 4] == 0:
            break

    granule = int.from_bytes(tail[position + 6:position + 14], "little")

    # Opus counts in 48000ths of a second, whatever the sound's own rate.
    return max(0.0, (granule - pre_skip) / 48000)


@dataclass(frozen=True)
class StoredFile:
    path: Path
    module_id: str
    # Start of the file, from its name (seconds since 1970).
    started: float
    # Last write: the end of the sound in it.
    modified: float
    size: int


class MicStoreService:
    """
    Keeps the stored microphone sound within its rules.

    The sound lives only on the RAM disk, one folder per module, one
    Opus file a minute (written by MicRecorder). Three rules, in this
    order:

    1. Age. A file whose sound ended more than keep_minutes ago is
       deleted.
    2. Size. When all modules together use more than ram_limit_mb, the
       oldest minute goes first, whichever module it is from, so every
       module keeps the same length of history.
    3. Giving way. When the RAM disk itself runs short, the oldest
       minutes go until it no longer is. The same RAM disk holds the
       camera clips waiting for the disk copy, and those come first: the
       microphone sound gives way before any camera clip is dropped.

    A file that is being written is never deleted.
    """

    def __init__(
        self,
        settings_service: MicSettingsService,
        directory: Path,
        files_in_use: Callable[[], set[Path]],
        camera_reserve_mb: Callable[[], int],
        free_bytes: Callable[[], int] | None = None,
    ) -> None:
        self._settings_service = settings_service
        self._directory = directory
        self._files_in_use = files_in_use
        self._camera_reserve_mb = camera_reserve_mb
        self._free_bytes = free_bytes or self._ram_free_bytes
        self._reserve_cache: tuple[int | None, float] = (None, 0.0)
        # Length of each stored file, remembered while the file is
        # unchanged: path -> (last write, size, seconds).
        self._seconds_cache: dict[Path, tuple[float, int, float]] = {}

        self._lock = RLock()
        self._stop_event = Event()
        self._thread: Thread | None = None

        # Counted since the backend started, for the page.
        self._deleted_for_age = 0
        self._deleted_for_size = 0
        self._deleted_for_ram = 0
        self._last_gave_way_at: str | None = None

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def start(self) -> None:
        with self._lock:
            if self._thread is not None:
                return

            self._stop_event.clear()
            self._thread = Thread(
                target=self._run,
                name="mic-store",
                daemon=True,
            )
            self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()

        with self._lock:
            thread = self._thread
            self._thread = None

        if thread is not None:
            thread.join(timeout=10)

    def clean(self) -> None:
        """Apply the age and size rules now."""

        with self._lock:
            settings = self._settings_service.get()
            in_use = self._files_in_use()
            now = time.time()

            files = self._files()
            cutoff = now - settings.keep_minutes * 60

            kept: list[StoredFile] = []

            for stored in files:
                if (
                    stored.modified < cutoff
                    and self._may_delete(stored, in_use, now)
                ):
                    self._delete(stored)
                    self._deleted_for_age += 1
                else:
                    kept.append(stored)

            limit = settings.ram_limit_mb * MEGABYTE
            total = sum(stored.size for stored in kept)

            for stored in kept:
                if total <= limit:
                    break

                if not self._may_delete(stored, in_use, now):
                    continue

                self._delete(stored)
                self._deleted_for_size += 1
                total -= stored.size

    def give_way_if_ram_short(self) -> None:
        """Delete the oldest sound while the RAM disk is short."""

        floor = (self._camera_reserve() + GIVE_WAY_MARGIN_MB) * MEGABYTE

        if self._free_bytes() >= floor:
            return

        with self._lock:
            in_use = self._files_in_use()
            now = time.time()
            deleted = 0

            for stored in self._files():
                if not self._may_delete(stored, in_use, now):
                    continue

                self._delete(stored)
                deleted += 1

                if self._free_bytes() >= floor:
                    break

            if deleted:
                self._deleted_for_ram += deleted
                self._last_gave_way_at = datetime.now(
                    LOCAL_TIME_ZONE
                ).isoformat(timespec="seconds")

                LOGGER.warning(
                    "RAM disk is short: deleted the oldest %s minute(s) "
                    "of microphone sound so the camera clips keep their "
                    "room",
                    deleted,
                )

    def delete_module(self, module_id: str) -> None:
        """Delete everything stored for a module taken off the list."""

        if MODULE_ID_PATTERN.fullmatch(module_id) is None:
            return

        with self._lock:
            shutil.rmtree(self._directory / module_id, ignore_errors=True)

    def files_between(
        self,
        module_id: str,
        start: float,
        end: float,
    ) -> list[tuple[Path, float, float]]:
        """
        A module's files that hold sound between two moments (seconds
        since 1970), oldest first: each file's path, the moment its
        sound begins and its length in seconds.
        """

        files = [
            stored
            for stored in self._files()
            if stored.module_id == module_id
        ]

        return [
            (stored.path, began, seconds)
            for stored, began, seconds in self._timed(files)
            if began < end and began + seconds > start
        ]

    def stretches(self, files: list[StoredFile]) -> list[dict]:
        """
        The unbroken stretches of sound in a module's files, so the page
        can show what is stored and where the holes are.
        """

        stretches: list[dict] = []

        for _stored, began, seconds in self._timed(files):
            end = began + seconds

            if (
                stretches
                and began - stretches[-1]["end"] <= SAME_STRETCH_SECONDS
            ):
                stretches[-1]["end"] = max(stretches[-1]["end"], end)
            else:
                stretches.append({"start": began, "end": end})

        return [
            {
                "start": round(stretch["start"], 1),
                "end": round(stretch["end"], 1),
            }
            for stretch in stretches
        ]

    def status(self) -> dict:
        settings = self._settings_service.get()
        files = self._files()

        self._forget_seconds_of_deleted(files)

        modules: dict[str, dict] = {}
        files_by_module: dict[str, list[StoredFile]] = {}

        for stored in files:
            entry = modules.setdefault(
                stored.module_id,
                {
                    "files": 0,
                    "bytes": 0,
                    "oldest_at": self._iso(stored.started),
                    "newest_at": None,
                },
            )
            entry["files"] += 1
            entry["bytes"] += stored.size
            entry["newest_at"] = self._iso(stored.modified)
            files_by_module.setdefault(stored.module_id, []).append(stored)

        for module_id, entry in modules.items():
            entry["mb"] = round(entry.pop("bytes") / MEGABYTE, 1)
            entry["stretches"] = self.stretches(files_by_module[module_id])

        with self._lock:
            return {
                "directory": str(self._directory),
                "used_mb": round(
                    sum(stored.size for stored in files) / MEGABYTE, 1
                ),
                "ram_limit_mb": settings.ram_limit_mb,
                "keep_minutes": settings.keep_minutes,
                "ram_free_mb": round(self._free_bytes() / MEGABYTE),
                "gives_way_under_mb": (
                    self._camera_reserve() + GIVE_WAY_MARGIN_MB
                ),
                "deleted_for_age": self._deleted_for_age,
                "deleted_for_size": self._deleted_for_size,
                "deleted_for_ram": self._deleted_for_ram,
                "last_gave_way_at": self._last_gave_way_at,
                "modules": modules,
            }

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _run(self) -> None:
        next_clean = 0.0

        while not self._stop_event.is_set():
            try:
                self.give_way_if_ram_short()

                if time.monotonic() >= next_clean:
                    next_clean = time.monotonic() + CLEAN_INTERVAL_SECONDS
                    self.clean()
            except Exception:
                LOGGER.exception("Microphone store check failed")

            self._stop_event.wait(RAM_CHECK_INTERVAL_SECONDS)

    def _files(self) -> list[StoredFile]:
        """Every stored file, oldest first across all modules."""

        found: list[StoredFile] = []

        try:
            module_directories = [
                entry
                for entry in self._directory.iterdir()
                if entry.is_dir()
                and MODULE_ID_PATTERN.fullmatch(entry.name) is not None
            ]
        except OSError:
            return found

        for module_directory in module_directories:
            for path in module_directory.glob(f"*{SEGMENT_EXTENSION}"):
                try:
                    details = path.stat()
                except OSError:
                    continue

                found.append(
                    StoredFile(
                        path=path,
                        module_id=module_directory.name,
                        started=self._start_time(path, details.st_mtime),
                        modified=details.st_mtime,
                        size=details.st_size,
                    )
                )

        found.sort(key=lambda stored: (stored.started, stored.module_id))

        return found

    def _seconds(self, stored: StoredFile) -> float:
        cached = self._seconds_cache.get(stored.path)

        if (
            cached is not None
            and cached[0] == stored.modified
            and cached[1] == stored.size
        ):
            return cached[2]

        seconds = opus_seconds(stored.path)
        self._seconds_cache[stored.path] = (
            stored.modified,
            stored.size,
            seconds,
        )

        return seconds

    def _timed(
        self,
        files: list[StoredFile],
    ) -> list[tuple[StoredFile, float, float]]:
        """
        One module's files, oldest first, each with the moment its
        sound begins and its length in seconds. Files without sound are
        left out.

        A file's name gives only the second it began in. The exact
        moment comes from its neighbours, because inside one run the
        files follow each other without a pause:

        - a file followed by the next file of its run ended where that
          one began, and that one began exactly on the clock;
        - the last file of a run began where the one before it ended;
        - a file alone began at its last write minus its length. (That
          is not used when a neighbour can tell, because the last file
          of a run is closed only when the module is noticed to have
          gone, which can be seconds after its sound ended.)
        """

        timed: list[tuple[StoredFile, float, float]] = []
        with_sound = [
            (stored, self._seconds(stored)) for stored in files
        ]
        with_sound = [
            (stored, seconds) for stored, seconds in with_sound if seconds > 0
        ]

        previous_end: float | None = None

        for index, (stored, seconds) in enumerate(with_sound):
            earliest = stored.started
            latest = stored.started + 0.999
            began: float | None = None

            if index + 1 < len(with_sound):
                from_next = with_sound[index + 1][0].started - seconds

                if earliest - 0.05 <= from_next <= latest:
                    began = from_next

            if (
                began is None
                and previous_end is not None
                and earliest - 0.5 <= previous_end <= latest
            ):
                began = previous_end

            if began is None:
                began = stored.modified - seconds

            began = min(max(began, earliest), latest)
            previous_end = began + seconds

            timed.append((stored, began, seconds))

        return timed

    def _forget_seconds_of_deleted(self, files: list[StoredFile]) -> None:
        if len(self._seconds_cache) <= 2 * len(files) + 16:
            return

        present = {stored.path for stored in files}

        for path in list(self._seconds_cache):
            if path not in present:
                self._seconds_cache.pop(path, None)

    @staticmethod
    def _start_time(path: Path, fallback: float) -> float:
        try:
            return (
                datetime.strptime(path.stem, FILE_NAME_FORMAT)
                .replace(tzinfo=LOCAL_TIME_ZONE)
                .timestamp()
            )
        except ValueError:
            return fallback

    @staticmethod
    def _may_delete(
        stored: StoredFile,
        in_use: set[Path],
        now: float,
    ) -> bool:
        if stored.path in in_use:
            return False

        return now - stored.modified >= FRESH_FILE_SECONDS

    @staticmethod
    def _delete(stored: StoredFile) -> None:
        try:
            stored.path.unlink(missing_ok=True)
        except OSError as error:
            LOGGER.warning(
                "Could not delete microphone file %s: %s",
                stored.path,
                error,
            )

    def _camera_reserve(self) -> int:
        """archive_buffer_reserve_mb, asked for once a minute at most."""

        value, read_at = self._reserve_cache

        if value is not None and time.monotonic() - read_at < 60:
            return value

        try:
            value = int(self._camera_reserve_mb())
        except Exception:
            # The camera default, if the camera settings cannot be read.
            value = 250

        self._reserve_cache = (value, time.monotonic())

        return value

    def _ram_free_bytes(self) -> int:
        try:
            self._directory.mkdir(parents=True, exist_ok=True)
            return shutil.disk_usage(self._directory).free
        except OSError:
            # Cannot tell; never delete sound on a guess.
            return 2**62

    @staticmethod
    def _iso(timestamp: float) -> str:
        return datetime.fromtimestamp(
            timestamp,
            LOCAL_TIME_ZONE,
        ).isoformat(timespec="seconds")
