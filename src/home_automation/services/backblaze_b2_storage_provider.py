import time
from pathlib import Path

from b2sdk.v2 import (
    AbstractProgressListener,
    B2Api,
    InMemoryAccountInfo,
)

from home_automation.services.backblaze_credentials_service import (
    BackblazeCredentialsService,
)
from home_automation.services.camera_settings_service import (
    CameraSettingsService,
)


class RateLimitedProgressListener(AbstractProgressListener):
    def __init__(
        self,
        rate_kbps: int,
    ) -> None:
        super().__init__()

        self._bytes_per_second = rate_kbps * 1024
        self._started_at = time.monotonic()
        self._previous_byte_count = 0

    def set_total_bytes(
        self,
        total_byte_count: int,
    ) -> None:
        self._started_at = time.monotonic()
        self._previous_byte_count = 0

    def bytes_completed(
        self,
        byte_count: int,
    ) -> None:
        # Upload retries may restart the byte counter.
        if byte_count < self._previous_byte_count:
            self._started_at = time.monotonic()

        self._previous_byte_count = byte_count

        expected_elapsed = (
            byte_count / self._bytes_per_second
        )

        actual_elapsed = (
            time.monotonic() - self._started_at
        )

        delay = expected_elapsed - actual_elapsed

        if delay > 0:
            time.sleep(delay)


class BackblazeB2StorageProvider:
    def __init__(
        self,
        settings_service: CameraSettingsService,
        credentials_service: BackblazeCredentialsService,
    ) -> None:
        self._settings_service = settings_service
        self._credentials_service = credentials_service

    def upload(
        self,
        local_file: Path,
        remote_key: str,
    ) -> None:
        settings = self._settings_service.get()
        credentials = self._credentials_service.get()

        if credentials is None:
            raise RuntimeError(
                "Backblaze credentials are not configured"
            )

        account_info = InMemoryAccountInfo()

        b2_api = B2Api(
            account_info,
            max_upload_workers=1,
        )

        b2_api.authorize_account(
            "production",
            credentials.key_id,
            credentials.application_key,
        )

        bucket = b2_api.get_bucket_by_name(
            settings.b2_bucket
        )

        progress_listener = RateLimitedProgressListener(
            settings.b2_upload_rate_kbps
        )

        bucket.upload_local_file(
            local_file=str(local_file),
            file_name=remote_key,
            progress_listener=progress_listener,
        )