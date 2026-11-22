from collections import deque
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import logging
from pathlib import Path
from threading import Lock
from zoneinfo import ZoneInfo

from home_automation.config.camera_settings import CameraConfig
from home_automation.services.camera_settings_service import (
    CameraSettingsService,
)
from home_automation.services.camera_storage_provider import (
    CameraStorageProvider,
)
from home_automation.services.clip_naming import clip_key
from home_automation.services.recording_stats_service import (
    RecordingStatsService,
)


LOGGER = logging.getLogger("home_automation")

LOCAL_TIME_ZONE = ZoneInfo("Asia/Kolkata")


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
    ) -> None:
        self._settings_service = settings_service
        self._storage_provider = storage_provider
        self._stats_service = stats_service

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

        LOGGER.info(
            "Camera upload started [%s]: %s -> %s",
            camera.name,
            file_path,
            remote_key,
        )

        size = file_path.stat().st_size

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
