from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import logging
from pathlib import Path
from zoneinfo import ZoneInfo

from home_automation.config.camera_settings import CameraConfig
from home_automation.services.camera_settings_service import (
    CameraSettingsService,
)
from home_automation.services.camera_storage_provider import (
    CameraStorageProvider,
)


LOGGER = logging.getLogger("home_automation")

LOCAL_TIME_ZONE = ZoneInfo("Asia/Kolkata")


class CameraUploadService:
    def __init__(
        self,
        settings_service: CameraSettingsService,
        storage_provider: CameraStorageProvider,
    ) -> None:
        self._settings_service = settings_service
        self._storage_provider = storage_provider

        # One upload worker per camera.
        self._executor = ThreadPoolExecutor(
            max_workers=2,
            thread_name_prefix="camera-upload",
        )

    def submit(
        self,
        camera: CameraConfig,
        file_path: Path,
    ) -> None:
        settings = self._settings_service.get()

        if not settings.b2_upload_enabled:
            return

        self._executor.submit(
            self._upload_and_delete,
            camera,
            file_path,
        )

    def shutdown(self) -> None:
        self._executor.shutdown(wait=True)

    def _upload_and_delete(
        self,
        camera: CameraConfig,
        file_path: Path,
    ) -> None:
        if not file_path.exists():
            LOGGER.warning(
                "Camera segment missing before upload [%s]: %s",
                camera.name,
                file_path,
            )
            return

        remote_key = self._build_remote_key(
            camera,
            file_path,
        )

        LOGGER.info(
            "Camera upload started [%s]: %s -> %s",
            camera.name,
            file_path,
            remote_key,
        )

        try:
            self._storage_provider.upload(
                file_path,
                remote_key,
            )

            LOGGER.info(
                "Camera upload successful [%s]: %s",
                camera.name,
                remote_key,
            )

        except Exception:
            LOGGER.exception(
                "Camera upload failed [%s]: %s",
                camera.name,
                file_path,
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

    @staticmethod
    def _build_remote_key(
        camera: CameraConfig,
        file_path: Path,
    ) -> str:
        timestamp = datetime.fromtimestamp(
            file_path.stat().st_mtime,
            tz=LOCAL_TIME_ZONE,
        )

        camera_number = camera.key.removeprefix("cam")

        return (
            f"{camera.key}/"
            f"{timestamp:%Y/%m/%d/%H}/"
            f"cam_{camera_number}_{timestamp:%Y_%m_%d_%H_%M_%S}.ts"
        )