import json
import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from threading import Event, RLock
from urllib.request import Request, urlopen
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

PI_TIMEOUT_SECONDS = 8


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
    """
    b2sdk wrapper that understands the camera folder layout and looks
    in every Backblaze account the Pi knows about.

    The Pi rotates uploads between accounts, one account per day, and
    is the only place the account list lives. This client fetches the
    list from the Pi on every operation (no local copy), asks every
    account for the requested folders in parallel, and merges the
    answers. Each clip remembers which account it came from, so
    downloads go to the right place. B2 sessions are reused in memory
    while the program runs.
    """

    def __init__(self, settings_service: SettingsService) -> None:
        self._settings_service = settings_service
        self._lock = RLock()
        # (name, key_id, bucket) -> authorised bucket object
        self._buckets: dict[tuple[str, str, str], object] = {}

    # ------------------------------------------------------------------
    # Account list from the Pi
    # ------------------------------------------------------------------

    def _settings(self) -> Settings:
        return self._settings_service.get()

    def _accounts(self) -> list[dict]:
        settings = self._settings()
        pi_url = settings.pi_url.strip().rstrip("/")

        if not pi_url:
            raise B2NotConfiguredError("The Raspberry Pi address is not set")

        request = Request(f"{pi_url}/api/cameras/backblaze/accounts/export")

        try:
            with urlopen(request, timeout=PI_TIMEOUT_SECONDS) as response:
                data = json.loads(response.read())
        except Exception as error:
            raise B2NotConfiguredError(
                f"Could not get the account list from the Pi at {pi_url}: {error}"
            ) from error

        accounts = [
            account
            for account in data.get("accounts", [])
            if account.get("key_id") and account.get("application_key")
            and account.get("bucket")
        ]

        if not accounts:
            raise B2NotConfiguredError(
                "The Pi has no Backblaze account configured yet"
            )

        return accounts

    def _bucket_for(self, account: dict):
        identity = (
            str(account["name"]),
            str(account["key_id"]),
            str(account["bucket"]),
        )

        with self._lock:
            bucket = self._buckets.get(identity)
            if bucket is not None:
                return bucket

        api = B2Api(InMemoryAccountInfo())
        api.authorize_account(
            "production",
            str(account["key_id"]),
            str(account["application_key"]),
        )
        bucket = api.get_bucket_by_name(str(account["bucket"]))

        with self._lock:
            self._buckets[identity] = bucket

        return bucket

    def _each_bucket(self) -> list[tuple[str, object]]:
        """(account name, bucket) for every account that authorises."""

        pairs: list[tuple[str, object]] = []
        failures: list[str] = []

        for account in self._accounts():
            try:
                pairs.append((str(account["name"]), self._bucket_for(account)))
            except Exception as error:
                failures.append(f"{account.get('name')}: {error}")

        if not pairs:
            raise B2NotConfiguredError(
                "No Backblaze account could be reached: " + "; ".join(failures)
            )

        for failure in failures:
            LOGGER.warning("Backblaze account skipped: %s", failure)

        return pairs

    def _across(self, work: Callable[[str, object], list]) -> list:
        """Run work(name, bucket) for every account in parallel, flattened."""

        pairs = self._each_bucket()

        with ThreadPoolExecutor(max_workers=max(1, len(pairs))) as pool:
            results = list(pool.map(lambda pair: work(*pair), pairs))

        return [item for result in results for item in result]

    def reset(self) -> None:
        with self._lock:
            self._buckets.clear()

    def test_connection(self) -> dict:
        """Check every account the Pi lists, one result per account."""

        self.reset()
        accounts = self._accounts()
        results = []

        for account in accounts:
            name = str(account.get("name"))
            try:
                bucket = self._bucket_for(account)
                cameras = sorted(
                    folder for folder in self._folders_in(bucket, "")
                    if folder.startswith("cam")
                )
                results.append(
                    {"name": name, "ok": True, "bucket": bucket.name, "cameras": cameras}
                )
            except Exception as error:
                results.append({"name": name, "ok": False, "detail": str(error)})

        return {
            "pi_url": self._settings().pi_url,
            "accounts": results,
        }

    # ------------------------------------------------------------------
    # Browsing
    # ------------------------------------------------------------------

    @staticmethod
    def _folders_in(bucket, prefix: str) -> list[str]:
        """Immediate sub-folder names under prefix in one bucket."""

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

        return names

    def _folders(self, prefix: str) -> list[str]:
        """Sub-folder names under prefix across all accounts, deduplicated."""

        names = self._across(lambda _name, bucket: self._folders_in(bucket, prefix))
        return sorted(set(names))

    def list_cameras(self) -> list[str]:
        return [
            name for name in self._folders("")
            if name.startswith("cam") and name[3:].isdigit()
        ]

    def list_days(self, camera: str) -> list[str]:
        """Days with clips in any account, as YYYY-MM-DD, newest first."""

        def days_in(_name: str, bucket) -> list[str]:
            found: list[str] = []
            for year in self._folders_in(bucket, f"{camera}/"):
                for month in self._folders_in(bucket, f"{camera}/{year}/"):
                    for day in self._folders_in(bucket, f"{camera}/{year}/{month}/"):
                        found.append(f"{year}-{month}-{day}")
            return found

        return sorted(set(self._across(days_in)), reverse=True)

    def _clips_under(self, prefix: str) -> list[Clip]:
        settings = self._settings()
        timezone = ZoneInfo(settings.clip_timezone)

        def clips_in(name: str, bucket) -> list[Clip]:
            found: list[Clip] = []
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
                    account=name,
                )
                if clip is not None:
                    found.append(clip)
            return found

        # The same key could exist in two accounts only if the Pi
        # uploaded it twice; keep the first one seen.
        unique: dict[str, Clip] = {}
        for clip in self._across(clips_in):
            unique.setdefault(clip.key, clip)

        return list(unique.values())

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

    def _candidate_buckets(self, clip: Clip) -> list[object]:
        pairs = self._each_bucket()

        if clip.account:
            named = [bucket for name, bucket in pairs if name == clip.account]
            if named:
                return named

        # Unknown account (for example a preview by key alone): try
        # every account until one has the file.
        return [bucket for _name, bucket in pairs]

    def download(
        self,
        clip: Clip,
        destination: Path,
        on_progress: Callable[[int, int], None] | None = None,
        cancel_event: Event | None = None,
    ) -> Path:
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(destination.name + ".part")
        last_error: Exception | None = None

        for bucket in self._candidate_buckets(clip):
            try:
                downloaded = bucket.download_file_by_name(
                    clip.key,
                    progress_listener=_ProgressListener(on_progress, cancel_event),
                )
                downloaded.save_to(str(temporary))
                temporary.replace(destination)
                return destination

            except DownloadCancelled:
                temporary.unlink(missing_ok=True)
                raise

            except Exception as error:
                temporary.unlink(missing_ok=True)
                last_error = error
                continue

        raise RuntimeError(
            f"{clip.filename} was not found in any account"
            + (f": {last_error}" if last_error else "")
        )
