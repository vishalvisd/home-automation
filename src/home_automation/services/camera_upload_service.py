from collections import deque
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import logging
from pathlib import Path
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


class CameraUploadService:
    """
    Upload finished segments once, then delete them.

    Segments live in RAM (/dev/shm). Nothing is ever kept: a failed
    upload is logged and the file is deleted. If uploads fall behind,
    the oldest waiting segment is dropped so RAM cannot fill up.
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

        self._enforce_pending_limit(
            camera,
            settings.pending_upload_limit,
        )

        with self._pending_lock:
            self._pending.setdefault(
                camera.key,
                deque(),
            ).append(file_path)

        self._executor.submit(
            self._upload_and_delete,
            camera,
            file_path,
        )

    def shutdown(self) -> None:
        # Do not sit out a router restart while shutting down.
        if self._router_restart_service is not None:
            self._router_restart_service.abort()

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
        with self._pending_lock:
            queue = self._pending.get(camera.key)

            if queue is None or file_path not in queue:
                # Dropped by the pending limit before a worker got to it.
                return

            queue.remove(file_path)

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
            while self._uploads_held:
                self._gate.wait()

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
