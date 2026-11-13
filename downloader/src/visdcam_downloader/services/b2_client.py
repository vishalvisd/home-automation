import logging
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from threading import Event, RLock
from zoneinfo import ZoneInfo

from b2sdk.v2 import (
    AbstractProgressListener,
    B2Api,
    InMemoryAccountInfo,
)

from visdcam_downloader.config import Settings
from visdcam_downloader.services.clips import (
    Clip,
    hour_prefixes,
    parse_clip,
    select_clips,
)
from visdcam_downloader.services.settings_service import SettingsService


LOGGER = logging.getLogger(__name__)


class DownloadCancelled(RuntimeError):
    pass


class B2NotConfiguredError(RuntimeError):
    pass


class _ProgressListener(AbstractProgressListener):
    def __init__(
        self,
        on_progress: Callable[[int, int], None] | None,
        cancel_event: Event | None,
    ) -> None:
        super().__init__()
        self._on_progress = on_progress
        self._cancel_event = cancel_event
        self._total = 0

    def set_total_bytes(self, total_byte_count: int) -> None:
        self._total = total_byte_count

    def bytes_completed(self, byte_count: int) -> None:
        if self._cancel_event is not None and self._cancel_event.is_set():
            raise DownloadCancelled()

        if self._on_progress is not None:
            self._on_progress(byte_count, self._total)

    def close(self) -> None:
        pass


class B2Client:
    """Thin wrapper over b2sdk that understands the camera folder layout."""

    def __init__(self, settings_service: SettingsService) -> None:
        self._settings_service = settings_service
        self._lock = RLock()
        self._api: B2Api | None = None
        self._bucket = None
        self._authorized_with: tuple[str, str, str] | None = None

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    def _settings(self) -> Settings:
        return self._settings_service.get()

    def _get_bucket(self):
        settings = self._settings()

        if not settings.has_b2_credentials():
            raise B2NotConfiguredError(
                "Backblaze key ID, application key and bucket are not set"
            )

        identity = (
            settings.b2_key_id.strip(),
            settings.b2_application_key.strip(),
            settings.b2_bucket.strip(),
        )

        with self._lock:
            if self._bucket is not None and self._authorized_with == identity:
                return self._bucket

            api = B2Api(InMemoryAccountInfo())
            api.authorize_account("production", identity[0], identity[1])
            bucket = api.get_bucket_by_name(identity[2])

            self._api = api
            self._bucket = bucket
            self._authorized_with = identity

            return bucket

    def reset(self) -> None:
        with self._lock:
            self._api = None
            self._bucket = None
            self._authorized_with = None

    def test_connection(self) -> dict:
        self.reset()
        bucket = self._get_bucket()
        cameras = self.list_cameras()

        return {
            "ok": True,
            "bucket": bucket.name,
            "cameras": cameras,
        }

    # ------------------------------------------------------------------
    # Browsing
    # ------------------------------------------------------------------

    def _folders(self, prefix: str) -> list[str]:
        """Immediate sub-folder names under prefix, without the prefix."""

        bucket = self._get_bucket()
        names: list[str] = []

        for _file_version, folder_name in bucket.ls(
            folder_to_list=prefix,
            latest_only=True,
            recursive=False,
        ):
            if folder_name is None:
                continue
            name = folder_name[len(prefix):].strip("/")
            if name:
                names.append(name)

        return sorted(names)

    def list_cameras(self) -> list[str]:
        return [
            name for name in self._folders("")
            if name.startswith("cam") and name[3:].isdigit()
        ]

    def list_days(self, camera: str) -> list[str]:
        """Days with clips, as YYYY-MM-DD, newest first."""

        days: list[str] = []

        for year in self._folders(f"{camera}/"):
            for month in self._folders(f"{camera}/{year}/"):
                for day in self._folders(f"{camera}/{year}/{month}/"):
                    days.append(f"{year}-{month}-{day}")

        return sorted(days, reverse=True)

    def _clips_under(self, prefix: str) -> list[Clip]:
        settings = self._settings()
        timezone = ZoneInfo(settings.clip_timezone)
        bucket = self._get_bucket()
        clips: list[Clip] = []

        for file_version, _folder_name in bucket.ls(
            folder_to_list=prefix,
            latest_only=True,
            recursive=True,
        ):
            clip = parse_clip(
                file_version.file_name,
                file_version.size,
                timezone,
                settings.segment_seconds,
            )
            if clip is not None:
                clips.append(clip)

        return clips

    def list_clips_for_day(self, camera: str, day: str) -> list[Clip]:
        year, month, day_number = day.split("-")
        clips = self._clips_under(f"{camera}/{year}/{month}/{day_number}/")
        clips.sort(key=lambda clip: clip.end_time)
        return clips

    def list_clips(
        self,
        camera: str,
        start: datetime,
        end: datetime,
    ) -> list[Clip]:
        settings = self._settings()
        clips: list[Clip] = []

        for prefix in hour_prefixes(
            camera,
            start,
            end,
            settings.segment_seconds,
        ):
            clips.extend(self._clips_under(prefix))

        return select_clips(clips, start, end)

    # ------------------------------------------------------------------
    # Downloading
    # ------------------------------------------------------------------

    def download(
        self,
        clip: Clip,
        destination: Path,
        on_progress: Callable[[int, int], None] | None = None,
        cancel_event: Event | None = None,
    ) -> Path:
        bucket = self._get_bucket()
        destination.parent.mkdir(parents=True, exist_ok=True)

        temporary = destination.with_name(destination.name + ".part")

        try:
            downloaded = bucket.download_file_by_name(
                clip.key,
                progress_listener=_ProgressListener(on_progress, cancel_event),
            )
            downloaded.save_to(str(temporary))
            temporary.replace(destination)

        except BaseException:
            temporary.unlink(missing_ok=True)
            raise

        return destination
