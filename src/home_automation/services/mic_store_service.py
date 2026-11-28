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

MEGABYTE = 1024 * 1024


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

    def status(self) -> dict:
        settings = self._settings_service.get()
        files = self._files()

        modules: dict[str, dict] = {}

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

        for entry in modules.values():
            entry["mb"] = round(entry.pop("bytes") / MEGABYTE, 1)

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
