import logging
import os
import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from threading import Event, RLock, Thread
from time import monotonic

from home_automation.config.camera_settings import CameraConfig
from home_automation.services.camera_settings_service import (
    CameraSettingsService,
)
from home_automation.services.clip_naming import LOCAL_TIME_ZONE, clip_key
from home_automation.services.disk_activity_log import DiskActivityLog
from home_automation.services.recording_stats_service import (
    RecordingStatsService,
)


LOGGER = logging.getLogger("home_automation")

# Finished clips wait here, inside the RAM buffer directory, until the
# next batch. ffmpeg never writes into this folder, so a recorder
# restart (which clears unfinished files) cannot touch them.
PENDING_DIRECTORY_NAME = "pending"

CHECK_SECONDS = 10
MOUNT_TIMEOUT_SECONDS = 60
PARK_TIMEOUT_SECONDS = 30
SMART_TIMEOUT_SECONDS = 30

# While the disk activity log is on, ask the disk this often between
# batches whether it is really asleep. The question does not wake it.
SLEEP_CHECK_SECONDS = 300

# SMART attributes worth showing. Anything non-zero in the first three
# means the disk is wearing out.
SMART_ATTRIBUTES = {
    "Reallocated_Sector_Ct": "reallocated_sectors",
    "Current_Pending_Sector": "pending_sectors",
    "Offline_Uncorrectable": "uncorrectable_sectors",
    "Power_On_Hours": "power_on_hours",
    "Start_Stop_Count": "start_stop_count",
    "Load_Cycle_Count": "load_cycle_count",
    "Temperature_Celsius": "temperature_c",
}

DAY_DIRECTORY_PATTERN = re.compile(r"^\d{4}/\d{2}/\d{2}$")

# A clip's path on the disk, as the downloader asks for it.
CLIP_KEY_PATTERN = re.compile(
    r"^cam\d+/\d{4}/\d{2}/\d{2}/\d{2}/cam_\d+_\d{4}_\d{2}_\d{2}_\d{2}_\d{2}_\d{2}\.(mp4|ts)$"
)

# After the downloader browsed the disk, keep it awake this long in case
# more requests follow, then park it.
BROWSE_IDLE_SECONDS = 180


class ArchiveService:
    """
    Keep the main-stream clips on a USB disk that rests between batches.

    Finished clips arrive from the archive recorders into RAM. Every
    archive_flush_minutes one batch runs: mount the disk (which spins
    it up), move every waiting clip, oldest first, to camN/YYYY/MM/DD/
    with the same name the cloud copy has, free space by deleting the
    oldest day when needed, read the disk's SMART counters, unmount,
    and park the disk.

    A batch starts early when the waiting clips reach
    archive_buffer_limit_mb, or when the RAM disk has less than twice
    archive_buffer_reserve_mb free.

    A waiting clip is dropped only when the RAM disk itself is nearly
    full (less than archive_buffer_reserve_mb free), never because of
    a size limit. That needs the disk to be away or failing for a long
    time. The oldest clip of all cameras goes first.
    """

    def __init__(
        self,
        settings_service: CameraSettingsService,
        stats_service: RecordingStatsService | None = None,
        activity_log: DiskActivityLog | None = None,
    ) -> None:
        self._settings_service = settings_service
        self._stats_service = stats_service
        self._activity_log = activity_log
        # Per camera, for the UI: when a clip last reached the disk and
        # how many have, since service start.
        self._camera_stats: dict[str, dict] = {}
        self._lock = RLock()
        self._flush_lock = RLock()
        self._wake = Event()
        self._stop = Event()

        self._last_flush_at: datetime | None = None
        self._last_flush_files = 0
        self._last_flush_bytes = 0
        self._last_error: str | None = None
        self._disk: dict = {}
        self._smart: dict = {}
        self._parked = False

        # For the disk activity log: when we last woke the disk
        # (monotonic), why the next early batch was asked for, and the
        # last answer of the sleep check.
        self._awake_since: float | None = None
        self._early_reason = "size"
        self._sleep_state: str | None = None
        self._last_sleep_check = monotonic()

        # Until when the disk must stay mounted for browsing (monotonic).
        self._browse_until = 0.0

        self._thread = Thread(
            target=self._loop,
            name="archive",
            daemon=True,
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        self._pending_directory().mkdir(parents=True, exist_ok=True)
        self._thread.start()
        self._log_activity(
            "service_start",
            note="disk state not known until the first wake or check",
        )
        LOGGER.info("Archive service started")

    def shutdown(self) -> None:
        self._stop.set()
        self._wake.set()

        if self._thread.is_alive():
            self._thread.join(timeout=MOUNT_TIMEOUT_SECONDS + 30)

        # A planned restart should not lose the clips waiting in RAM.
        if self._settings_service.get().archive_enabled and self._pending_files():
            try:
                self.flush(reason="shutdown")
            except Exception:
                LOGGER.exception("Final archive batch failed")

    # ------------------------------------------------------------------
    # Clips from the archive recorders
    # ------------------------------------------------------------------

    def submit(self, camera: CameraConfig, file_path: Path) -> None:
        """A finished clip from the archive recorder (already in RAM)."""

        settings = self._settings_service.get()

        if not settings.archive_enabled:
            file_path.unlink(missing_ok=True)
            return

        closed_at = datetime.fromtimestamp(
            file_path.stat().st_mtime,
            tz=LOCAL_TIME_ZONE,
        )

        # Keep the final name from the start; the folder structure is
        # flattened with "__" while the clip waits.
        pending_name = clip_key(camera, closed_at, file_path.suffix).replace(
            "/", "__"
        )

        pending_directory = self._pending_directory()
        # RAM directories can vanish (the whole /dev/shm tree was once
        # emptied under us); never let that lose clips.
        pending_directory.mkdir(parents=True, exist_ok=True)
        destination = pending_directory / pending_name

        try:
            file_path.replace(destination)
        except OSError:
            # Different filesystem would be a configuration mistake.
            shutil.move(str(file_path), str(destination))

        reserve_bytes = settings.archive_buffer_reserve_mb * 1024 * 1024

        self._drop_oldest_if_ram_full(reserve_bytes)

        waiting_bytes = sum(
            self._size(path) for path in self._pending_files()
        )

        # Start a batch early: enough is waiting, or RAM is getting
        # short. Neither drops anything.
        if waiting_bytes >= settings.archive_buffer_limit_mb * 1024 * 1024:
            self._early_reason = "size"
            self._wake.set()
        elif self._ram_free_bytes() < 2 * reserve_bytes:
            self._early_reason = "low_ram"
            self._wake.set()

    def flush(self, reason: str = "manual") -> dict:
        """Run one batch now. Safe to call from the API."""

        with self._flush_lock:
            self._run_batch(reason)

        return self.status()

    # ------------------------------------------------------------------
    # Browsing the disk (for the downloader on the Mac)
    # ------------------------------------------------------------------

    def _browse_root(self) -> Path:
        """
        Mount the disk for browsing and keep it awake for a while. The
        batch and the browsing share the flush lock so they never fight
        over mounting and parking.
        """

        settings = self._settings_service.get()
        archive_root = Path(settings.archive_directory)

        if not settings.archive_enabled:
            raise RuntimeError("The archive is switched off")

        if not Path(settings.archive_disk_device).exists():
            raise RuntimeError("Archive disk is not plugged in")

        with self._flush_lock:
            self._wake_disk(archive_root, "browse")

            with self._lock:
                self._browse_until = monotonic() + BROWSE_IDLE_SECONDS

        return archive_root

    def list_cameras(self) -> list[str]:
        root = self._browse_root()
        return sorted(
            path.name
            for path in root.glob("cam*")
            if path.is_dir() and path.name[3:].isdigit()
        )

    def list_days(self, camera: str) -> list[str]:
        root = self._browse_root()
        days = []

        for day_directory in (root / camera).glob("*/*/*"):
            relative = "/".join(day_directory.parts[-3:])
            if day_directory.is_dir() and DAY_DIRECTORY_PATTERN.match(relative):
                days.append(relative.replace("/", "-"))

        return sorted(days, reverse=True)

    def list_clips(self, camera: str, day: str) -> list[dict]:
        root = self._browse_root()
        year, month, day_number = day.split("-")
        day_directory = root / camera / year / month / day_number
        clips = []

        if day_directory.is_dir():
            for path in day_directory.glob("*/*"):
                key = str(path.relative_to(root))
                if path.is_file() and CLIP_KEY_PATTERN.match(key):
                    clips.append({"key": key, "size": path.stat().st_size})

        clips.sort(key=lambda clip: clip["key"])
        return clips

    def clip_path(self, key: str) -> Path:
        """Absolute path of one clip for serving; raises if unknown."""

        if not CLIP_KEY_PATTERN.match(key):
            raise ValueError("Not a clip key")

        root = self._browse_root()
        path = root / key

        if not path.is_file():
            raise FileNotFoundError(key)

        return path

    def _park_if_browse_idle(self) -> None:
        settings = self._settings_service.get()
        archive_root = Path(settings.archive_directory)

        with self._lock:
            idle = monotonic() >= self._browse_until

        if not idle or not os.path.ismount(archive_root):
            return

        # Do not interfere with a running batch.
        if not self._flush_lock.acquire(blocking=False):
            return

        try:
            with self._lock:
                if monotonic() < self._browse_until:
                    return

            LOGGER.info("Archive disk idle after browsing; parking it")
            self._unmount_and_park(archive_root, settings.archive_disk_device)

        finally:
            self._flush_lock.release()

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def camera_status(self, camera_key: str) -> dict:
        """Disk-copy state of one camera for the UI."""

        prefix = f"{camera_key}__"
        waiting = [path for path in self._pending_files() if path.name.startswith(prefix)]

        with self._lock:
            stats = dict(self._camera_stats.get(camera_key, {}))
            last_flush_at = (
                self._last_flush_at.isoformat(timespec="seconds")
                if self._last_flush_at
                else None
            )
            last_error = self._last_error

        return {
            "waiting_files": len(waiting),
            "waiting_bytes": sum(self._size(path) for path in waiting),
            "stored_ok": stats.get("stored_ok", 0),
            "stored_failed": stats.get("stored_failed", 0),
            "dropped": stats.get("dropped", 0),
            "last_stored_at": stats.get("last_stored_at"),
            "last_stored_bytes": stats.get("last_stored_bytes"),
            "last_batch_at": last_flush_at,
            "last_error": last_error,
        }

    def _note(self, camera_key: str, **changes) -> None:
        with self._lock:
            entry = self._camera_stats.setdefault(camera_key, {})
            for key, value in changes.items():
                if key.startswith("+"):
                    entry[key[1:]] = entry.get(key[1:], 0) + value
                else:
                    entry[key] = value

    def status(self) -> dict:
        settings = self._settings_service.get()
        files = self._pending_files()

        with self._lock:
            return {
                "enabled": settings.archive_enabled,
                "directory": settings.archive_directory,
                "disk_device": settings.archive_disk_device,
                "disk_present": Path(settings.archive_disk_device).exists(),
                "mounted": os.path.ismount(settings.archive_directory),
                "parked": self._parked,
                "waiting_files": len(files),
                "waiting_mb": round(
                    sum(self._size(path) for path in files) / 1e6, 1
                ),
                "buffer_limit_mb": settings.archive_buffer_limit_mb,
                "buffer_reserve_mb": settings.archive_buffer_reserve_mb,
                "ram_free_mb": round(self._ram_free_bytes() / 1024 / 1024),
                "flush_minutes": settings.archive_flush_minutes,
                "last_flush_at": (
                    self._last_flush_at.isoformat()
                    if self._last_flush_at
                    else None
                ),
                "last_flush_files": self._last_flush_files,
                "last_flush_mb": round(self._last_flush_bytes / 1e6, 1),
                "last_error": self._last_error,
                "disk": dict(self._disk),
                "smart": dict(self._smart),
            }

    # ------------------------------------------------------------------
    # The batch
    # ------------------------------------------------------------------

    def _loop(self) -> None:
        last_run = monotonic()

        while not self._stop.is_set():
            settings = self._settings_service.get()
            due = monotonic() - last_run >= settings.archive_flush_minutes * 60

            if settings.archive_enabled and (due or self._wake.is_set()):
                self._wake.clear()
                last_run = monotonic()

                try:
                    self.flush(reason="timer" if due else self._early_reason)
                except Exception:
                    LOGGER.exception("Archive batch failed")

            try:
                self._park_if_browse_idle()
            except Exception:
                LOGGER.exception("Archive park after browsing failed")

            try:
                self._check_sleep_if_due()
            except Exception:
                LOGGER.exception("Disk sleep check failed")

            self._stop.wait(timeout=CHECK_SECONDS)

    def _run_batch(self, reason: str) -> None:
        settings = self._settings_service.get()
        files = self._pending_files()
        archive_root = Path(settings.archive_directory)

        if not files and reason not in ("manual", "shutdown"):
            return

        if not Path(settings.archive_disk_device).exists():
            self._set_error("Archive disk is not plugged in")
            return

        LOGGER.info(
            "Archive batch starting (%s): %s clip(s)", reason, len(files)
        )

        batch_started = monotonic()

        try:
            self._wake_disk(archive_root, reason)
        except Exception as error:
            self._set_error(f"Could not mount the archive disk: {error}")
            return

        moved = 0
        moved_bytes = 0

        try:
            for path in files:
                relative = path.name.replace("__", "/")
                destination = archive_root / relative
                camera_key = relative.split("/", 1)[0]

                try:
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    size = path.stat().st_size
                    self._copy_with_fsync(path, destination)

                    if destination.stat().st_size != size:
                        raise OSError("size mismatch after copy")

                    path.unlink()
                    moved += 1
                    moved_bytes += size

                    self._note(
                        camera_key,
                        **{"+stored_ok": 1},
                        last_stored_at=datetime.now(LOCAL_TIME_ZONE).isoformat(timespec="seconds"),
                        last_stored_bytes=size,
                    )

                    if self._stats_service is not None:
                        self._stats_service.record(
                            camera_key, "disk", size, self._clip_time(relative)
                        )

                except Exception as error:
                    self._note(camera_key, **{"+stored_failed": 1})
                    LOGGER.error(
                        "Disk copy failed for %s: %s", path.name, error
                    )

            self._free_space(archive_root, settings.archive_min_free_gb)
            self._read_disk(archive_root)
            self._read_smart(settings.archive_disk_device)

            with self._lock:
                self._last_flush_at = datetime.now(LOCAL_TIME_ZONE)
                self._last_flush_files = moved
                self._last_flush_bytes = moved_bytes
                self._last_error = None

            LOGGER.info(
                "Archive batch done: %s clip(s), %.0f MB",
                moved,
                moved_bytes / 1e6,
            )

            with self._lock:
                smart = dict(self._smart)

            self._log_activity(
                "batch",
                reason=reason,
                seconds=round(monotonic() - batch_started, 1),
                clips=moved,
                mb=round(moved_bytes / 1e6, 1),
                start_stop_count=smart.get("start_stop_count"),
                load_cycle_count=smart.get("load_cycle_count"),
            )

        finally:
            with self._lock:
                browsing = monotonic() < self._browse_until

            if browsing:
                LOGGER.info("Archive disk stays awake: browsing in progress")
                self._log_activity("stay_awake", note="downloader is browsing")
            else:
                self._unmount_and_park(archive_root, settings.archive_disk_device)

    # ------------------------------------------------------------------
    # Disk handling
    # ------------------------------------------------------------------

    def _wake_disk(self, archive_root: Path, reason: str) -> None:
        """Mount the disk, which spins it up. Does nothing if it is awake."""

        if os.path.ismount(archive_root):
            return

        started = monotonic()

        try:
            self._mount(archive_root)
        except Exception as error:
            self._log_activity("wake_failed", reason=reason, note=str(error)[:200])
            raise

        with self._lock:
            self._parked = False
            self._awake_since = started
            self._sleep_state = None

        self._log_activity(
            "wake",
            reason=reason,
            seconds=round(monotonic() - started, 1),
        )

    @staticmethod
    def _mount(archive_root: Path) -> None:
        if os.path.ismount(archive_root):
            return

        # The fstab entry carries the "user" option, so no sudo needed.
        result = subprocess.run(
            ["mount", str(archive_root)],
            capture_output=True,
            text=True,
            timeout=MOUNT_TIMEOUT_SECONDS,
            check=False,
        )

        if result.returncode != 0 or not os.path.ismount(archive_root):
            raise RuntimeError(
                (result.stderr or result.stdout).strip() or "mount failed"
            )

    def _unmount_and_park(self, archive_root: Path, device: str) -> None:
        try:
            subprocess.run(["sync"], timeout=MOUNT_TIMEOUT_SECONDS, check=False)

            if os.path.ismount(archive_root):
                result = subprocess.run(
                    ["umount", str(archive_root)],
                    capture_output=True,
                    text=True,
                    timeout=MOUNT_TIMEOUT_SECONDS,
                    check=False,
                )

                if result.returncode != 0:
                    message = (result.stderr or result.stdout).strip()
                    self._set_error(
                        "Could not unmount the archive disk: " + message
                    )
                    self._log_activity(
                        "park",
                        seconds=self._awake_seconds(),
                        note=("unmount failed: " + message)[:200],
                    )
                    return

            # scripts/install_archive.sh allows exactly this command.
            result = subprocess.run(
                ["sudo", "-n", "hdparm", "-y", device],
                capture_output=True,
                text=True,
                timeout=PARK_TIMEOUT_SECONDS,
                check=False,
            )

            awake_seconds = self._awake_seconds()

            with self._lock:
                self._parked = result.returncode == 0
                self._awake_since = None
                self._sleep_state = None
                # Give the disk a moment before the first sleep check.
                self._last_sleep_check = monotonic()

            if result.returncode != 0:
                message = (result.stderr or result.stdout).strip()
                self._set_error("Could not park the archive disk: " + message)
                self._log_activity(
                    "park",
                    seconds=awake_seconds,
                    note=("park failed: " + message)[:200],
                )
            else:
                self._log_activity("park", seconds=awake_seconds, note="ok")

        except Exception as error:
            self._set_error(f"Could not release the archive disk: {error}")

    @staticmethod
    def _copy_with_fsync(source: Path, destination: Path) -> None:
        temporary = destination.with_name(destination.name + ".part")

        with open(source, "rb") as src, open(temporary, "wb") as dst:
            shutil.copyfileobj(src, dst, length=1024 * 1024)
            dst.flush()
            os.fsync(dst.fileno())

        temporary.replace(destination)

    def _free_space(self, archive_root: Path, min_free_gb: int) -> None:
        """Delete the oldest day (all cameras) until enough space is free."""

        while True:
            usage = shutil.disk_usage(archive_root)

            if usage.free >= min_free_gb * 1024**3:
                return

            days = self._days_on_disk(archive_root)

            if not days:
                return

            oldest = days[0]
            removed = 0

            for camera_directory in archive_root.glob("cam*"):
                day_directory = camera_directory / oldest
                if day_directory.is_dir():
                    removed += sum(1 for _ in day_directory.rglob("*") if _.is_file())
                    shutil.rmtree(day_directory, ignore_errors=True)
                    # Drop empty month and year folders left behind.
                    for parent in (day_directory.parent, day_directory.parent.parent):
                        try:
                            parent.rmdir()
                        except OSError:
                            pass

            LOGGER.warning(
                "Archive disk under %s GB free; deleted %s (%s files)",
                min_free_gb,
                oldest,
                removed,
            )

    @staticmethod
    def _clip_time(relative_key: str) -> datetime:
        """The clip's own time from its name, for the hourly counters."""

        name = relative_key.rsplit("/", 1)[-1]
        stamp = name.split("_", 2)[-1].rsplit(".", 1)[0]  # YYYY_MM_DD_HH_MM_SS

        try:
            return datetime.strptime(stamp, "%Y_%m_%d_%H_%M_%S").replace(
                tzinfo=LOCAL_TIME_ZONE
            )
        except ValueError:
            return datetime.now(LOCAL_TIME_ZONE)

    @staticmethod
    def _days_on_disk(archive_root: Path) -> list[str]:
        days: set[str] = set()

        for camera_directory in archive_root.glob("cam*"):
            for day_directory in camera_directory.glob("*/*/*"):
                relative = "/".join(day_directory.parts[-3:])
                if day_directory.is_dir() and DAY_DIRECTORY_PATTERN.match(relative):
                    days.add(relative)

        return sorted(days)

    def _read_disk(self, archive_root: Path) -> None:
        usage = shutil.disk_usage(archive_root)
        days = self._days_on_disk(archive_root)

        with self._lock:
            self._disk = {
                "total_gb": round(usage.total / 1024**3, 1),
                "used_gb": round(usage.used / 1024**3, 1),
                "free_gb": round(usage.free / 1024**3, 1),
                "oldest_day": days[0].replace("/", "-") if days else None,
                "newest_day": days[-1].replace("/", "-") if days else None,
                "days": len(days),
            }

    def _read_smart(self, device: str) -> None:
        try:
            result = subprocess.run(
                ["sudo", "-n", "smartctl", "-d", "sat,16", "-A", device],
                capture_output=True,
                text=True,
                timeout=SMART_TIMEOUT_SECONDS,
                check=False,
            )
        except Exception as error:
            with self._lock:
                self._smart = {"error": str(error)}
            return

        values: dict = {}

        for line in result.stdout.splitlines():
            parts = line.split()
            if len(parts) >= 10 and parts[1] in SMART_ATTRIBUTES:
                try:
                    values[SMART_ATTRIBUTES[parts[1]]] = int(parts[9])
                except ValueError:
                    pass

        if not values:
            values = {"error": (result.stderr or result.stdout).strip()[:200]}
        else:
            values["read_at"] = datetime.now(LOCAL_TIME_ZONE).isoformat()

        with self._lock:
            self._smart = values

    # ------------------------------------------------------------------
    # Disk activity log (a study of how the disk rests; off by default)
    # ------------------------------------------------------------------

    def _log_activity(self, event: str, **fields) -> None:
        if self._activity_log is None:
            return

        if not self._settings_service.get().archive_activity_log_enabled:
            return

        self._activity_log.write(event, **fields)

    def _awake_seconds(self) -> float | None:
        with self._lock:
            since = self._awake_since

        return None if since is None else round(monotonic() - since, 1)

    def _check_sleep_if_due(self) -> None:
        """
        Between batches, ask the disk whether it is asleep and write
        the answer when it changes. smartctl's "-n standby" asks
        without waking the disk. Only while the log is switched on.
        """

        settings = self._settings_service.get()

        if (
            self._activity_log is None
            or not settings.archive_activity_log_enabled
            or not settings.archive_enabled
        ):
            return

        if monotonic() - self._last_sleep_check < SLEEP_CHECK_SECONDS:
            return

        if os.path.ismount(settings.archive_directory):
            return

        if not Path(settings.archive_disk_device).exists():
            return

        # Never get in the way of a batch or of browsing.
        if not self._flush_lock.acquire(blocking=False):
            return

        try:
            self._last_sleep_check = monotonic()

            # scripts/install_archive.sh allows exactly this command.
            result = subprocess.run(
                [
                    "sudo", "-n", "smartctl", "-d", "sat,16",
                    "-n", "standby", "-i", settings.archive_disk_device,
                ],
                capture_output=True,
                text=True,
                timeout=SMART_TIMEOUT_SECONDS,
                check=False,
            )
        except Exception as error:
            state, note = "unknown", str(error)[:200]
        else:
            output = (result.stdout or "") + (result.stderr or "")
            upper = output.upper()

            if "STANDBY" in upper or "SLEEP" in upper:
                state, note = "asleep", ""
            elif "ACTIVE" in upper or "IDLE" in upper or result.returncode == 0:
                state = "awake"
                note = "nothing of ours woke the disk"
            else:
                state, note = "unknown", output.strip()[:200]
        finally:
            self._flush_lock.release()

        with self._lock:
            changed = state != self._sleep_state
            self._sleep_state = state
            parked = self._parked

        if changed:
            if state == "awake" and not parked:
                note = "awake, and we have not parked it since the service started"

            self._log_activity("check", reason=state, note=note)

    def activity(self, limit: int = 2000) -> dict:
        """The log's lines (newest last) and a summary per day."""

        settings = self._settings_service.get()

        if self._activity_log is None:
            return {"enabled": False, "file": None, "days": [], "events": []}

        events = self._activity_log.read()

        return {
            "enabled": settings.archive_activity_log_enabled,
            "file": str(self._activity_log.path),
            "lines": len(events),
            "days": self._activity_log.summary(),
            "events": events[-limit:],
        }

    # ------------------------------------------------------------------
    # RAM buffer
    # ------------------------------------------------------------------

    def _pending_directory(self) -> Path:
        return (
            Path(self._settings_service.get().archive_buffer_directory)
            / PENDING_DIRECTORY_NAME
        )

    def _pending_files(self) -> list[Path]:
        directory = self._pending_directory()

        if not directory.is_dir():
            directory.mkdir(parents=True, exist_ok=True)
            return []

        # Oldest clip first, whichever camera it came from. The waiting
        # name starts with the camera key, so sorting by name alone
        # would put every cam1 clip before any cam2 clip.
        return sorted(
            (path for path in directory.iterdir() if path.is_file()),
            key=lambda path: (
                self._clip_time(path.name.replace("__", "/")),
                path.name,
            ),
        )

    @staticmethod
    def _size(path: Path) -> int:
        # A batch may move a clip away while we look at it.
        try:
            return path.stat().st_size
        except OSError:
            return 0

    def _ram_free_bytes(self) -> int:
        """Free space in the RAM disk that holds the waiting clips."""

        directory = self._pending_directory()

        try:
            directory.mkdir(parents=True, exist_ok=True)
            return shutil.disk_usage(directory).free
        except OSError:
            # Cannot tell; never drop clips on a guess.
            return 2**62

    def _drop_oldest_if_ram_full(self, reserve_bytes: int) -> None:
        """
        The last resort. Clips are dropped only when the RAM disk is
        nearly full, so the recorders can keep writing. With a working
        disk a batch empties the buffer long before this.
        """

        if self._ram_free_bytes() >= reserve_bytes:
            return

        for path in self._pending_files():
            path.unlink(missing_ok=True)
            self._note(path.name.split("__", 1)[0], **{"+dropped": 1})

            LOGGER.warning(
                "RAM is nearly full and the disk has not taken the "
                "waiting clips; dropped the oldest one: %s",
                path.name,
            )

            if self._ram_free_bytes() >= reserve_bytes:
                break

    def _set_error(self, message: str) -> None:
        with self._lock:
            self._last_error = message

        LOGGER.error("Archive: %s", message)
