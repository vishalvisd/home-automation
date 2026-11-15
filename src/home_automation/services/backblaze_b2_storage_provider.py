import logging
import time
from datetime import datetime
from pathlib import Path
from threading import Lock

from b2sdk.v2 import (
    AbstractProgressListener,
    B2Api,
    InMemoryAccountInfo,
)

from home_automation.config.backblaze_credentials import BackblazeAccount
from home_automation.services.cloud_rotation_service import (
    CloudRotationService,
)
from home_automation.services.camera_settings_service import (
    CameraSettingsService,
)


LOGGER = logging.getLogger("home_automation")


class SharedUploadRateLimiter:
    """
    One upload speed limit for the whole Pi.

    Every upload reports the bytes it has sent and sleeps until the
    shared budget allows them. Three cameras uploading at once share
    the limit instead of each getting its own.
    """

    def __init__(self, settings_service: CameraSettingsService) -> None:
        self._settings_service = settings_service
        self._lock = Lock()
        self._tokens = 0.0
        self._last_refill = time.monotonic()

    def consume(self, byte_count: int) -> None:
        if byte_count <= 0:
            return

        rate = self._settings_service.get().b2_upload_rate_kb_s * 1024

        with self._lock:
            now = time.monotonic()
            # Up to one second of unused budget may be carried over,
            # so short pauses between chunks are not wasted.
            self._tokens = min(
                float(rate),
                self._tokens + (now - self._last_refill) * rate,
            )
            self._last_refill = now
            self._tokens -= byte_count
            deficit = -self._tokens if self._tokens < 0 else 0.0

        if deficit > 0:
            time.sleep(deficit / rate)


class SharedRateProgressListener(AbstractProgressListener):
    """b2sdk progress callback that feeds the shared limiter."""

    def __init__(self, limiter: SharedUploadRateLimiter) -> None:
        super().__init__()
        self._limiter = limiter
        self._previous_byte_count = 0

    def set_total_bytes(self, total_byte_count: int) -> None:
        self._previous_byte_count = 0

    def bytes_completed(self, byte_count: int) -> None:
        # Upload retries may restart the byte counter.
        if byte_count < self._previous_byte_count:
            self._previous_byte_count = 0

        delta = byte_count - self._previous_byte_count
        self._previous_byte_count = byte_count

        self._limiter.consume(delta)


def test_account(account: BackblazeAccount) -> dict:
    """
    Check an account without uploading anything: authorise with its
    key and look up its bucket. Returns a small result for the UI.
    """

    try:
        b2_api = B2Api(InMemoryAccountInfo(), max_upload_workers=1)
        b2_api.authorize_account(
            "production",
            account.key_id,
            account.application_key,
        )
    except Exception as error:
        return {
            "ok": False,
            "detail": f"Authorisation failed: {error}",
        }

    try:
        bucket = b2_api.get_bucket_by_name(account.bucket)
    except Exception as error:
        return {
            "ok": False,
            "detail": (
                f"Authorised, but bucket '{account.bucket}' was not "
                f"found or the key cannot see it: {error}"
            ),
        }

    allowed = b2_api.account_info.get_allowed() or {}
    capabilities = allowed.get("capabilities") or []
    missing = [
        capability
        for capability in ("writeFiles", "listBuckets")
        if capability not in capabilities
    ]

    if "writeFiles" in missing:
        return {
            "ok": False,
            "detail": "The key cannot write files (missing writeFiles)",
        }

    return {
        "ok": True,
        "detail": (
            f"OK: bucket '{bucket.name}' reachable, key can write files"
        ),
    }


class BackblazeB2StorageProvider:
    """
    Upload clips to Backblaze B2, to the account chosen for the clip's
    day by CloudRotationService.
    """

    def __init__(
        self,
        settings_service: CameraSettingsService,
        rotation_service: CloudRotationService,
    ) -> None:
        self._settings_service = settings_service
        self._rotation_service = rotation_service
        self._limiter = SharedUploadRateLimiter(settings_service)

        # One authorised API object per account, reused between
        # uploads. Keyed by account name; the key ID is kept so a
        # changed key is noticed.
        self._apis: dict[str, tuple[str, B2Api]] = {}
        self._apis_lock = Lock()

    def upload(
        self,
        local_file: Path,
        remote_key: str,
        recorded_at: datetime,
    ) -> str:
        """Upload one clip. Returns the account name used."""

        account = self._rotation_service.account_for(recorded_at)
        b2_api = self._api_for(account)

        bucket = b2_api.get_bucket_by_name(account.bucket)

        bucket.upload_local_file(
            local_file=str(local_file),
            file_name=remote_key,
            progress_listener=SharedRateProgressListener(self._limiter),
        )

        return account.name

    def _api_for(self, account: BackblazeAccount) -> B2Api:
        with self._apis_lock:
            cached = self._apis.get(account.name)

            if cached is not None and cached[0] == account.key_id:
                return cached[1]

            b2_api = B2Api(
                InMemoryAccountInfo(),
                max_upload_workers=1,
            )

            b2_api.authorize_account(
                "production",
                account.key_id,
                account.application_key,
            )

            self._apis[account.name] = (account.key_id, b2_api)

            LOGGER.info(
                "Backblaze account authorised: %s (bucket %s)",
                account.name,
                account.bucket,
            )

            return b2_api
