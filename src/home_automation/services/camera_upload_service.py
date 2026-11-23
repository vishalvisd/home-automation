from collections import deque
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
import logging
from pathlib import Path
import shutil
from threading import Condition, Lock
from time import monotonic
from zoneinfo import ZoneInfo

from home_automation.config.camera_settings import CameraConfig
from home_automation.services.camera_settings_service import (
    CameraSettingsService,
)
from home_automation.services.camera_storage_provider import (
    CameraStorageProvider,
)
from home_automation.services.clip_naming import clip_key
from home_automation.services.cloud_rotation_service import (
    CloudRotationService,
)
from home_automation.services.recording_stats_service import (
    RecordingStatsService,
)
from home_automation.services.router_restart_service import (
    RouterRestartService,
)


LOGGER = logging.getLogger("home_automation")

LOCAL_TIME_ZONE = ZoneInfo("Asia/Kolkata")

# The nightly router restart runs only in this hour of the day
# (0 = between midnight and 1 AM, Asia/Kolkata).
ROUTER_RESTART_HOUR = 0

# Before the router's power is cut, uploads already in progress get
# this long to finish.
UPLOADS_FINISH_WAIT_SECONDS = 60

# After an upload pause ends, the clips that waited are uploaded. For
# at most this long the waiting clips are still limited by size, not by
# pending_upload_limit, so the backlog is not thrown away.
CATCH_UP_MAX_SECONDS = 30 * 60

# The two kinds of upload pause.
PAUSE_HOLD = "hold"  # clips wait in RAM and upload afterwards
PAUSE_SKIP = "skip"  # clips are deleted; no backlog, no burst afterwards
PAUSE_MODES = (PAUSE_HOLD, PAUSE_SKIP)


class CameraUploadService:
    """
    Upload finished segments once, then delete them.

    Segments live in RAM (/dev/shm). Nothing is ever kept: a failed
    upload is logged and the file is deleted. If uploads fall behind,
    the oldest waiting segment is dropped so RAM cannot fill up.

    Uploads can be paused for a set number of minutes (for example
    during a video call). Recording goes on. There are two kinds:

    - "hold": the cloud clips wait in RAM and are uploaded when the
      pause ends. While they wait they are limited by size
      (upload_pause_buffer_mb) and they give way before the disk copy
      would run short of RAM.
    - "skip": the cloud clips of that time are deleted as they close,
      so nothing waits and there is no burst of uploads afterwards.
      The cloud copy has a gap; the disk copy has everything.
    """

    def __init__(
        self,
        settings_service: CameraSettingsService,
        storage_provider: CameraStorageProvider,
        stats_service: RecordingStatsService | None = None,
        rotation_service: CloudRotationService | None = None,
        router_restart_service: RouterRestartService | None = None,
    ) -> None:
        self._settings_service = settings_service
        self._storage_provider = storage_provider
        self._stats_service = stats_service
        self._rotation_service = rotation_service
        self._router_restart_service = router_restart_service

        # Uploads can be held while the router is restarted. A worker
        # waits at this gate before it starts an upload.
        self._gate = Condition()
        self._uploads_held = False
        self._uploads_running = 0

        # Only one worker decides about the nightly router restart,
        # and only once per day.
        self._restart_lock = Lock()
        self._restart_handled_day: str | None = None

        # The upload pause. All guarded by the gate.
        self._pause_mode = PAUSE_HOLD
        self._pause_skipped = 0
        self._pause_until = 0.0  # monotonic clock
        self._pause_until_wall: datetime | None = None
        self._catch_up_until = 0.0  # monotonic clock
        self._pause_dropped = 0
        self._shutting_down = False

        # Per camera, for the UI. In memory only.
        self._stats_lock = Lock()
        self._stats: dict[str, dict] = {}

        # One upload worker per configured camera. Cameras added later
        # share these workers until the backend restarts.
        camera_count = len(settings_service.get().cameras)

        self._executor = ThreadPoolExecutor(
            max_workers=max(1, camera_count),
            thread_name_prefix="camera-upload",
        )

        # Segments submitted but not yet picked up by a worker.
        self._pending_lock = Lock()
        self._pending: dict[str, deque[Path]] = {}

    def submit(
        self,
        camera: CameraConfig,
        file_path: Path,
    ) -> None:
        settings = self._settings_service.get()

        if not settings.b2_upload_enabled:
            # With upload off the file has nowhere to go. Delete it
            # now rather than let RAM fill up.
            file_path.unlink(missing_ok=True)

            LOGGER.info(
                "Upload disabled; camera segment deleted [%s]: %s",
                camera.name,
                file_path,
            )
            return

        if self._skipping():
            self._skip(camera, file_path)
            return

        backlog_allowed = self._backlog_allowed(settings.pending_upload_limit)

        if not backlog_allowed:
            self._enforce_pending_limit(
                camera,
                settings.pending_upload_limit,
            )

        with self._pending_lock:
            self._pending.setdefault(
                camera.key,
                deque(),
            ).append(file_path)

        if backlog_allowed:
            self._enforce_pause_buffer(file_path.parent)

        self._executor.submit(
            self._upload_and_delete,
            camera,
            file_path,
        )

    def shutdown(self) -> None:
        # Do not sit out a router restart while shutting down.
        if self._router_restart_service is not None:
            self._router_restart_service.abort()

        # Nor an upload pause. Its backlog cannot be uploaded in the
        # time a shutdown has, so keep only what the normal rule keeps.
        # Trim first, then let the waiting workers go.
        limit = self._settings_service.get().pending_upload_limit

        for camera in self._settings_service.get().cameras:
            self._trim_queue(camera, limit)

        with self._gate:
            self._shutting_down = True
            self._pause_until = 0.0
            self._catch_up_until = 0.0
            self._gate.notify_all()

        self._executor.shutdown(wait=True)

    def status(self, camera_key: str) -> dict:
        """Upload state of one camera for the UI."""

        with self._pending_lock:
            waiting = len(self._pending.get(camera_key, ()))

        with self._stats_lock:
            stats = dict(self._stats.get(camera_key, {}))

        return {
            "waiting_files": waiting,
            "uploads_ok": stats.get("uploads_ok", 0),
            "uploads_failed": stats.get("uploads_failed", 0),
            "dropped": stats.get("dropped", 0),
            "last_upload_at": stats.get("last_upload_at"),
            "last_upload_account": stats.get("last_upload_account"),
            "last_upload_bytes": stats.get("last_upload_bytes"),
            "last_failure_at": stats.get("last_failure_at"),
            "last_failure": stats.get("last_failure"),
        }

    def _note(self, camera_key: str, **changes) -> None:
        with self._stats_lock:
            entry = self._stats.setdefault(camera_key, {})
            for key, value in changes.items():
                if key.startswith("+"):
                    entry[key[1:]] = entry.get(key[1:], 0) + value
                else:
                    entry[key] = value

    def _enforce_pending_limit(
        self,
        camera: CameraConfig,
        limit: int,
    ) -> None:
        dropped: list[Path] = []

        with self._pending_lock:
            queue = self._pending.setdefault(
                camera.key,
                deque(),
            )

            while len(queue) >= limit:
                dropped.append(queue.popleft())

        for file_path in dropped:
            file_path.unlink(missing_ok=True)
            self._note(camera.key, **{"+dropped": 1})

            LOGGER.warning(
                "Too many segments waiting for upload; "
                "oldest deleted without upload [%s]: %s",
                camera.name,
                file_path,
            )

    def _upload_and_delete(
        self,
        camera: CameraConfig,
        file_path: Path,
    ) -> None:
        # During an upload pause the clip stays in the waiting list,
        # where the size limit can still see it.
        self._wait_for_pause_end()

        with self._pending_lock:
            queue = self._pending.get(camera.key)

            if queue is None or file_path not in queue:
                # Dropped by the pending limit before a worker got to it.
                return

            queue.remove(file_path)

        if self._skipping():
            # Still waiting when a "skip" pause began.
            self._skip(camera, file_path)
            return

        if not file_path.exists():
            LOGGER.warning(
                "Camera segment missing before upload [%s]: %s",
                camera.name,
                file_path,
            )
            return

        recorded_at = datetime.fromtimestamp(
            file_path.stat().st_mtime,
            tz=LOCAL_TIME_ZONE,
        )

        remote_key = clip_key(camera, recorded_at, file_path.suffix)

        try:
            self._restart_router_if_new_day(recorded_at)
        except Exception:
            # The restart must never cost a clip.
            LOGGER.exception("Router restart before the new day failed")

        LOGGER.info(
            "Camera upload started [%s]: %s -> %s",
            camera.name,
            file_path,
            remote_key,
        )

        size = file_path.stat().st_size

        self._begin_upload()

        try:
            destination = self._storage_provider.upload(
                file_path,
                remote_key,
                recorded_at,
            )

            LOGGER.info(
                "Camera upload successful [%s]: %s (%s)",
                camera.name,
                remote_key,
                destination,
            )

            self._note(
                camera.key,
                **{"+uploads_ok": 1},
                last_upload_at=datetime.now(LOCAL_TIME_ZONE).isoformat(timespec="seconds"),
                last_upload_account=destination,
                last_upload_bytes=size,
            )

            if self._stats_service is not None:
                self._stats_service.record(camera.key, "cloud", size, recorded_at)

        except Exception as error:
            LOGGER.exception(
                "Camera upload failed [%s]: %s",
                camera.name,
                file_path,
            )

            self._note(
                camera.key,
                **{"+uploads_failed": 1},
                last_failure_at=datetime.now(LOCAL_TIME_ZONE).isoformat(timespec="seconds"),
                last_failure=str(error).splitlines()[0][:160] if str(error) else type(error).__name__,
            )

        finally:
            self._end_upload()

            try:
                file_path.unlink(missing_ok=True)

                LOGGER.info(
                    "Camera segment deleted [%s]: %s",
                    camera.name,
                    file_path,
                )

            except Exception:
                LOGGER.exception(
                    "Unable to delete camera segment [%s]: %s",
                    camera.name,
                    file_path,
                )

    # ------------------------------------------------------------------
    # Holding uploads, and the nightly router restart
    # ------------------------------------------------------------------

    def _begin_upload(self) -> None:
        with self._gate:
            while not self._shutting_down:
                if self._uploads_held:
                    self._gate.wait()
                    continue

                remaining = self._pause_until - monotonic()

                if remaining > 0 and self._pause_mode == PAUSE_HOLD:
                    self._gate.wait(timeout=min(remaining, 5))
                    continue

                break

            self._uploads_running += 1

    def _end_upload(self) -> None:
        with self._gate:
            self._uploads_running -= 1
            self._gate.notify_all()

    def _restart_router_if_new_day(self, recorded_at: datetime) -> None:
        """
        Called before every upload. When this clip is the first of a
        new day, the next upload changes the Backblaze account. Just
        before that, restart the router once: let the uploads in
        progress finish, hold the rest, power-cycle the router, wait
        for the internet, then let everything continue.
        """

        if self._rotation_service is None or self._router_restart_service is None:
            return

        if not self._settings_service.get().router_restart_enabled:
            return

        with self._restart_lock:
            if not self._rotation_service.is_new_day(recorded_at):
                return

            day_key = recorded_at.astimezone(LOCAL_TIME_ZONE).date().isoformat()

            if self._restart_handled_day == day_key:
                return

            self._restart_handled_day = day_key

            # Only just after midnight. If the Pi was off at midnight,
            # the account changes later in the day without a restart,
            # so the internet is never cut in the middle of the day.
            now = datetime.now(LOCAL_TIME_ZONE)

            if now.hour != ROUTER_RESTART_HOUR:
                LOGGER.info(
                    "New day %s starts outside the router restart hour; "
                    "the account changes without a restart",
                    day_key,
                )
                return

            LOGGER.info(
                "First clip of %s: restarting the router before the "
                "Backblaze account changes",
                day_key,
            )

            with self._gate:
                self._uploads_held = True
                deadline = monotonic() + UPLOADS_FINISH_WAIT_SECONDS

                while self._uploads_running > 0 and monotonic() < deadline:
                    self._gate.wait(timeout=1)

            try:
                self._router_restart_service.restart()
            finally:
                with self._gate:
                    self._uploads_held = False
                    self._gate.notify_all()

    # ------------------------------------------------------------------
    # Pausing uploads for a while
    # ------------------------------------------------------------------

    def pause_uploads(self, mode: str = PAUSE_HOLD) -> dict:
        """
        Pause cloud uploads for upload_pause_minutes. Recording and the
        disk copy go on. mode "hold" keeps the clips for afterwards,
        mode "skip" deletes them. Pressing either again starts the time
        afresh, in the mode just pressed; going from "hold" to "skip"
        deletes the clips that were waiting.
        """

        if mode not in PAUSE_MODES:
            raise ValueError(f"Unknown pause mode: {mode}")

        minutes = self._settings_service.get().upload_pause_minutes

        with self._gate:
            self._pause_mode = mode
            self._pause_until = monotonic() + minutes * 60
            self._pause_until_wall = datetime.now(LOCAL_TIME_ZONE) + timedelta(
                minutes=minutes
            )
            self._catch_up_until = (
                self._pause_until + CATCH_UP_MAX_SECONDS
                if mode == PAUSE_HOLD
                else 0.0
            )
            self._pause_dropped = 0
            self._pause_skipped = 0
            self._gate.notify_all()

        LOGGER.info(
            "Cloud uploads paused for %s minutes (%s)",
            minutes,
            "clips wait in RAM" if mode == PAUSE_HOLD else "clips are skipped",
        )

        return self.pause_status()

    def resume_uploads(self) -> dict:
        """End the pause now; the waiting clips start uploading."""

        with self._gate:
            was_paused = monotonic() < self._pause_until
            self._pause_until = 0.0

            if was_paused and self._pause_mode == PAUSE_HOLD:
                self._catch_up_until = monotonic() + CATCH_UP_MAX_SECONDS

            self._gate.notify_all()

        if was_paused:
            LOGGER.info("Cloud uploads resumed by hand")

        return self.pause_status()

    def pause_status(self) -> dict:
        settings = self._settings_service.get()

        with self._gate:
            paused = monotonic() < self._pause_until
            until = self._pause_until_wall if paused else None
            mode = self._pause_mode
            dropped = self._pause_dropped
            skipped = self._pause_skipped

        catching_up = (not paused) and self._backlog_allowed(
            settings.pending_upload_limit
        )

        with self._pending_lock:
            files = [path for queue in self._pending.values() for path in queue]

        return {
            "paused": paused,
            "mode": mode,
            "until": until.isoformat(timespec="seconds") if until else None,
            "catching_up": catching_up,
            "minutes": settings.upload_pause_minutes,
            "buffer_limit_mb": settings.upload_pause_buffer_mb,
            "waiting_files": len(files),
            "waiting_mb": round(sum(self._size(path) for path in files) / 1e6, 1),
            "dropped": dropped,
            "skipped": skipped,
        }

    def _skipping(self) -> bool:
        """True during a "skip" pause: clips are deleted, not kept."""

        with self._gate:
            return (
                self._pause_mode == PAUSE_SKIP
                and monotonic() < self._pause_until
            )

    def _skip(self, camera: CameraConfig, file_path: Path) -> None:
        file_path.unlink(missing_ok=True)
        self._note(camera.key, **{"+dropped": 1})

        with self._gate:
            self._pause_skipped += 1

        LOGGER.info(
            "Uploads paused without keeping clips; segment deleted [%s]: %s",
            camera.name,
            file_path,
        )

    def _wait_for_pause_end(self) -> None:
        with self._gate:
            while not self._shutting_down:
                remaining = self._pause_until - monotonic()

                if remaining <= 0 or self._pause_mode != PAUSE_HOLD:
                    return

                self._gate.wait(timeout=min(remaining, 5))

    def _backlog_allowed(self, pending_limit: int) -> bool:
        """
        True while uploads are paused, and afterwards until the clips
        that waited have been uploaded. In that time the waiting clips
        are limited by size instead of by pending_upload_limit.
        """

        with self._gate:
            now = monotonic()

            if now < self._pause_until:
                return self._pause_mode == PAUSE_HOLD

            if now >= self._catch_up_until:
                return False

        with self._pending_lock:
            longest = max(
                (len(queue) for queue in self._pending.values()),
                default=0,
            )

        if longest < pending_limit:
            # Caught up: back to the normal rule.
            with self._gate:
                self._catch_up_until = 0.0

            return False

        return True

    def _enforce_pause_buffer(self, ram_directory: Path) -> None:
        """
        Keep the clips that wait during a pause within their limits,
        dropping the oldest clip of all cameras first:

        - at most upload_pause_buffer_mb in total, and
        - never so much that the RAM disk has less than twice
          archive_buffer_reserve_mb free. Below that the disk copy
          starts an early batch, and below once that figure it would
          drop its own clips. The disk copy is the primary recording,
          so the cloud clips give way first.
        """

        settings = self._settings_service.get()
        limit_bytes = settings.upload_pause_buffer_mb * 1024 * 1024
        ram_floor_bytes = 2 * settings.archive_buffer_reserve_mb * 1024 * 1024

        dropped: list[tuple[str, Path]] = []

        with self._pending_lock:
            waiting = sorted(
                (
                    (self._modified(path), camera_key, path)
                    for camera_key, queue in self._pending.items()
                    for path in queue
                ),
                key=lambda item: (item[0], str(item[2])),
            )

            total = sum(self._size(path) for _, _, path in waiting)

            # Always keep the newest clip, the one that just arrived.
            for _, camera_key, path in waiting[:-1]:
                if (
                    total <= limit_bytes
                    and self._ram_free_bytes(ram_directory) >= ram_floor_bytes
                ):
                    break

                total -= self._size(path)
                self._pending[camera_key].remove(path)
                path.unlink(missing_ok=True)
                dropped.append((camera_key, path))

        for camera_key, path in dropped:
            self._note(camera_key, **{"+dropped": 1})

            LOGGER.warning(
                "Upload pause: waiting clips passed their limit; "
                "oldest deleted without upload: %s",
                path,
            )

        if dropped:
            with self._gate:
                self._pause_dropped += len(dropped)

    def _trim_queue(self, camera: CameraConfig, limit: int) -> None:
        """Drop the oldest waiting clips of one camera down to limit."""

        dropped: list[Path] = []

        with self._pending_lock:
            queue = self._pending.get(camera.key)

            while queue and len(queue) > limit:
                dropped.append(queue.popleft())

        for file_path in dropped:
            file_path.unlink(missing_ok=True)
            self._note(camera.key, **{"+dropped": 1})

            LOGGER.warning(
                "Shutting down during an upload pause; waiting clip "
                "deleted without upload [%s]: %s",
                camera.name,
                file_path,
            )

    @staticmethod
    def _size(path: Path) -> int:
        try:
            return path.stat().st_size
        except OSError:
            return 0

    @staticmethod
    def _modified(path: Path) -> float:
        try:
            return path.stat().st_mtime
        except OSError:
            return 0.0

    @staticmethod
    def _ram_free_bytes(directory: Path) -> int:
        try:
            return shutil.disk_usage(directory).free
        except OSError:
            # Cannot tell; never drop clips on a guess.
            return 2**62
