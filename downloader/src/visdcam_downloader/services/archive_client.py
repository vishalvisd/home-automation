"""
Clips on the Pi's archive disk, read over the Pi's API.

Same interface as B2Client so the routes and jobs can use either. The
Pi wakes its disk when asked and parks it again a few minutes after
the last request.
"""

import json
import logging
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from threading import Event
from urllib.parse import quote
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from visdcam_downloader.services.b2_client import (
    B2NotConfiguredError,
    DownloadCancelled,
)
from visdcam_downloader.services.clips import (
    Clip,
    hour_prefixes,
    parse_clip,
    select_clips,
)
from visdcam_downloader.services.settings_service import SettingsService


LOGGER = logging.getLogger(__name__)

# Listing wakes the disk, which can take a few seconds to spin up.
LIST_TIMEOUT_SECONDS = 60
DOWNLOAD_TIMEOUT_SECONDS = 60
CHUNK_BYTES = 1024 * 1024


class ArchiveClient:
    def __init__(self, settings_service: SettingsService) -> None:
        self._settings_service = settings_service

    # ------------------------------------------------------------------

    def _base(self) -> str:
        pi_url = self._settings_service.get().pi_url.strip().rstrip("/")

        if not pi_url:
            raise B2NotConfiguredError("The Raspberry Pi address is not set")

        return pi_url + "/api/cameras/archive"

    def _get_json(self, path: str):
        try:
            with urlopen(Request(self._base() + path), timeout=LIST_TIMEOUT_SECONDS) as response:
                return json.loads(response.read())
        except Exception as error:
            detail = getattr(error, "reason", None) or str(error)
            try:
                detail = json.loads(error.read()).get("detail", detail)  # type: ignore[attr-defined]
            except Exception:
                pass
            raise RuntimeError(f"Pi archive: {detail}") from error

    # ------------------------------------------------------------------
    # Browsing
    # ------------------------------------------------------------------

    def list_cameras(self) -> list[str]:
        return self._get_json("/cameras")

    def list_days(self, camera: str) -> list[str]:
        return self._get_json(f"/days?camera={camera}")

    def _clips_for_day(self, camera: str, day: str) -> list[Clip]:
        settings = self._settings_service.get()
        timezone = ZoneInfo(settings.clip_timezone)
        clips: list[Clip] = []

        for item in self._get_json(f"/clips?camera={camera}&day={day}"):
            clip = parse_clip(
                item["key"],
                int(item["size"]),
                timezone,
                settings.segment_seconds,
                account="pi-disk",
            )
            if clip is not None:
                clips.append(clip)

        return clips

    def list_clips_for_day(self, camera: str, day: str) -> list[Clip]:
        clips = self._clips_for_day(camera, day)
        clips.sort(key=lambda clip: clip.end_time)
        return clips

    def list_clips(self, camera: str, start: datetime, end: datetime) -> list[Clip]:
        settings = self._settings_service.get()
        days = sorted(
            {prefix.split("/")[1] + "-" + prefix.split("/")[2] + "-" + prefix.split("/")[3]
             for prefix in hour_prefixes(camera, start, end, settings.segment_seconds)}
        )

        clips: list[Clip] = []
        for day in days:
            clips.extend(self._clips_for_day(camera, day))

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
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(destination.name + ".part")
        url = self._base() + "/file?key=" + quote(clip.key, safe="")

        try:
            with urlopen(Request(url), timeout=DOWNLOAD_TIMEOUT_SECONDS) as response:
                total = int(response.headers.get("Content-Length") or clip.size or 0)
                done = 0

                with open(temporary, "wb") as file:
                    while True:
                        if cancel_event is not None and cancel_event.is_set():
                            raise DownloadCancelled()

                        chunk = response.read(CHUNK_BYTES)
                        if not chunk:
                            break

                        file.write(chunk)
                        done += len(chunk)

                        if on_progress is not None:
                            on_progress(done, total)

            temporary.replace(destination)
            return destination

        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
