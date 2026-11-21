import hashlib
import re
from pathlib import Path
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse

from visdcam_downloader.api.dependencies import (
    get_settings_service,
    get_source_client,
    get_workflows,
)
from visdcam_downloader.api.errors import http_error
from visdcam_downloader.config import PREVIEW_CACHE_DIRECTORY
from visdcam_downloader.services.clips import parse_clip
from visdcam_downloader.services.settings_service import SettingsService
from visdcam_downloader.services.timelapse import remux_arguments
from visdcam_downloader.services.workflows import Workflows


router = APIRouter(prefix="/api/preview", tags=["preview"])

B2Dependency = Annotated[object, Depends(get_source_client)]
SettingsDependency = Annotated[SettingsService, Depends(get_settings_service)]
WorkflowsDependency = Annotated[Workflows, Depends(get_workflows)]

CACHE_LIMIT_BYTES = 1024 * 1024 * 1024  # 1 GB of previews on disk
KEY_PATTERN = re.compile(r"^cam\d+/\d{4}/\d{2}/\d{2}/\d{2}/[\w.]+\.(ts|mp4)$")


def _trim_cache() -> None:
    files = sorted(
        (p for p in PREVIEW_CACHE_DIRECTORY.iterdir() if p.is_file()),
        key=lambda p: p.stat().st_mtime,
    )
    total = sum(p.stat().st_size for p in files)
    while files and total > CACHE_LIMIT_BYTES:
        oldest = files.pop(0)
        total -= oldest.stat().st_size
        oldest.unlink(missing_ok=True)


@router.get("")
def preview_clip(
    b2: B2Dependency,
    settings: SettingsDependency,
    workflows: WorkflowsDependency,
    key: str = Query(),
    account: str = Query(""),
    source: str = Query("cloud", pattern=r"^(cloud|disk)$"),
) -> FileResponse:
    """Download one clip into the local cache (converting .ts to MP4) and serve it."""

    if not KEY_PATTERN.match(key):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Not a clip key")

    current = settings.get()
    clip = parse_clip(
        key, 0, ZoneInfo(current.clip_timezone), current.segment_seconds, account=account,
    )
    if clip is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Not a clip key")

    # Cloud and disk copies of a clip differ (sub vs main stream).
    digest = hashlib.sha1(f"{source}:{key}".encode()).hexdigest()[:16]
    cached = PREVIEW_CACHE_DIRECTORY / f"{digest}.mp4"

    if not cached.exists():
        PREVIEW_CACHE_DIRECTORY.mkdir(parents=True, exist_ok=True)
        raw = PREVIEW_CACHE_DIRECTORY / f"{digest}.{clip.extension}"

        try:
            b2.download(clip, raw)
        except Exception as error:
            raise http_error(error) from error

        if clip.extension == "mp4":
            raw.replace(cached)
        else:
            tools = workflows.tools()
            try:
                tools.require()
                tools.run(remux_arguments(raw, cached, tools))
            except Exception as error:
                raise http_error(error) from error
            finally:
                raw.unlink(missing_ok=True)

        _trim_cache()

    cached.touch()
    return FileResponse(cached, media_type="video/mp4", filename=f"{clip.filename.rsplit('.', 1)[0]}.mp4")
