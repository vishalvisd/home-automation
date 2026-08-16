import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from threading import Lock
from zoneinfo import ZoneInfo

import boto3
from boto3.s3.transfer import TransferConfig

from home_automation.config.camera_settings import (
    CameraConfig,
    CameraSettings,
)
from home_automation.services.camera_settings_service import (
    CameraSettingsService,
)
from home_automation.services.backblaze_credentials_service import (
    BackblazeCredentialsService,
)


LOGGER = logging.getLogger(__name__)

LOCAL_TIMEZONE = ZoneInfo("Asia/Kolkata")


class CameraUploadService:
    """Upload completed CCTV segments to Backblaze B2."""

    def __init__(
        self,
        settings_service: CameraSettingsService,
        credentials_service: BackblazeCredentialsService,
    ) -> None:
        self._settings_service = settings_service
        self._credentials_service = credentials_service
        self._lock = Lock()
        self._shutdown = False

        # Old system had one uploader per camera.
        self._executor = ThreadPoolExecutor(
            max_workers=2,
            thread_name_prefix="camera-b2-upload",
        )

    def submit(
        self,
        camera: CameraConfig,
        file_path: Path,
    ) -> None:
        settings = self._settings_service.get()

        if not settings.b2_upload_enabled:
            return

        with self._lock:
            if self._shutdown:
                return

        self._executor.submit(
            self._upload_and_delete,
            camera,
            file_path,
            settings,
        )

    def shutdown(self) -> None:
        with self._lock:
            self._shutdown = True

        self._executor.shutdown(
            wait=True,
            cancel_futures=False,
        )

    def _upload_and_delete(
        self,
        camera: CameraConfig,
        file_path: Path,
        settings: CameraSettings,
    ) -> None:
        try:
            if not file_path.exists():
                LOGGER.warning(
                    "Camera upload skipped; file missing [%s]: %s",
                    camera.name,
                    file_path,
                )
                return

            object_key = self._build_object_key(
                camera,
                file_path,
            )

            endpoint_url = (
                f"https://s3.{settings.b2_region}"
                ".backblazeb2.com"
            )

            LOGGER.info(
                "Camera upload started [%s]: %s -> "
                "s3://%s/%s",
                camera.name,
                file_path,
                settings.b2_bucket,
                object_key,
            )

            credentials = self._credentials_service.get()

            if credentials is None:
                raise RuntimeError(
                    "Backblaze credentials are not configured"
                )

            session = boto3.Session(
                aws_access_key_id=credentials.key_id,
                aws_secret_access_key=(
                    credentials.application_key
                ),
                region_name=settings.b2_region,
            )

            client = session.client(
                "s3",
                endpoint_url=endpoint_url,
            )

            transfer_config = TransferConfig(
                use_threads=False,
                max_bandwidth=(
                    settings.b2_upload_rate_kbps
                    * 1024
                ),
                preferred_transfer_client="classic",
            )

            client.upload_file(
                str(file_path),
                settings.b2_bucket,
                object_key,
                Config=transfer_config,
            )

            LOGGER.info(
                "Camera upload successful [%s]: "
                "s3://%s/%s",
                camera.name,
                settings.b2_bucket,
                object_key,
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

            except OSError:
                LOGGER.exception(
                    "Unable to delete camera segment [%s]: %s",
                    camera.name,
                    file_path,
                )

    @staticmethod
    def _build_object_key(
        camera: CameraConfig,
        file_path: Path,
    ) -> str:
        modified_time = datetime.fromtimestamp(
            file_path.stat().st_mtime,
            tz=LOCAL_TIMEZONE,
        )

        camera_number = camera.key.removeprefix(
            "cam"
        )

        file_name = (
            f"cam_{camera_number}_"
            f"{modified_time:%Y_%m_%d_%H_%M_%S}"
            f"{file_path.suffix}"
        )

        return (
            f"{camera.key}/"
            f"{modified_time:%Y/%m/%d/%H}/"
            f"{file_name}"
        )