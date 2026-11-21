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


LOGGER = logging.getLogger("home_automation")

# Finished clips wait here, inside the RAM buffer directory, until the
# next batch. ffmpeg never writes into this folder, so a recorder
# restart (which clears unfinished files) cannot touch them.
PENDING_DIRECTORY_NAME = "pending"

CHECK_SECONDS = 10
MOUNT_TIMEOUT_SECONDS = 60
PARK_TIMEOUT_SECONDS = 30
SMART_TIMEOUT_SECONDS = 30

# SMART attributes worth showing. Anything non-zero in the first three
# means the disk is wearing out.
SMART_ATTRIBUTES = {
    "Reallocated_Sector_Ct": "reallocated_sectors",
    "Current_Pending_Sector": "pending_sectors",
    "Offline_Uncorrectable": "uncorrectable_sectors",
    "Power_On_Hours": "power_on_hours",
    "Start_Stop_Count": "start_stop_count",
    "Temperature_Celsius": "temperature_c",
}

DAY_DIRECTORY_PATTERN = re.compile(r"^\d{4}/\d{2}/\d{2}$")


class ArchiveService:
    """
    Keep the main-stream clips on a USB disk that rests between batches.

    Finished clips arrive from the archive recorders into RAM. Every
    archive_flush_minutes, or sooner when the RAM buffer passes its
    limit, one batch runs: mount the disk (which spins it up), move
    every waiting clip to camN/YYYY/MM/DD/ with the same name the cloud
    copy has, free space by deleting the oldest day when needed, read
    the disk's SMART counters, unmount, and park the disk.

    If the disk is absent the clips wait in RAM up to the buffer limit;
    beyond it the oldest waiting clips are dropped so RAM never fills.
    """

    def __init__(self, settings_service: CameraSettingsService) -> None:
        self._settings_service = settings_service
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

        destination = self._pending_directory() / pending_name

        try:
            file_path.replace(destination)
        except OSError:
            # Different filesystem would be a configuration mistake.
            shutil.move(str(file_path), str(destination))

        waiting_bytes = self._enforce_buffer_limit(
            settings.archive_buffer_limit_mb * 1024 * 1024
        )

        if waiting_bytes >= settings.archive_buffer_limit_mb * 1024 * 1024 * 0.9:
            self._wake.set()

    def flush(self, reason: str = "manual") -> dict:
        """Run one batch now. Safe to call from the API."""

        with self._flush_lock:
            self._run_batch(reason)

        return self.status()

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

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
                    sum(path.stat().st_size for path in files) / 1e6, 1
                ),
                "buffer_limit_mb": settings.archive_buffer_limit_mb,
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
                    self.flush(reason="timer" if due else "buffer")
                except Exception:
                    LOGGER.exception("Archive batch failed")

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

        try:
            self._mount(archive_root)
        except Exception as error:
            self._set_error(f"Could not mount the archive disk: {error}")
            return

        moved = 0
        moved_bytes = 0

        try:
            for path in files:
                relative = path.name.replace("__", "/")
                destination = archive_root / relative

                try:
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    size = path.stat().st_size
                    self._copy_with_fsync(path, destination)

                    if destination.stat().st_size != size:
                        raise OSError("size mismatch after copy")

                    path.unlink()
                    moved += 1
                    moved_bytes += size

                except Exception as error:
                    LOGGER.error(
                        "Archive copy failed for %s: %s", path.name, error
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

        finally:
            self._unmount_and_park(archive_root, settings.archive_disk_device)

    # ------------------------------------------------------------------
    # Disk handling
    # ------------------------------------------------------------------

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
                    self._set_error(
                        "Could not unmount the archive disk: "
                        + (result.stderr or result.stdout).strip()
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

            with self._lock:
                self._parked = result.returncode == 0

            if result.returncode != 0:
                self._set_error(
                    "Could not park the archive disk: "
                    + (result.stderr or result.stdout).strip()
                )

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
            return []

        return sorted(
            (path for path in directory.iterdir() if path.is_file()),
            key=lambda path: path.name,
        )

    def _enforce_buffer_limit(self, limit_bytes: int) -> int:
        files = self._pending_files()
        total = sum(path.stat().st_size for path in files)

        for path in files:
            if total <= limit_bytes:
                break

            size = path.stat().st_size
            path.unlink(missing_ok=True)
            total -= size

            LOGGER.warning(
                "Archive buffer full and the disk is unavailable; "
                "dropped waiting clip %s",
                path.name,
            )

        return total

    def _set_error(self, message: str) -> None:
        with self._lock:
            self._last_error = message

        LOGGER.error("Archive: %s", message)
