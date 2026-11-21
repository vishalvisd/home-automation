from collections import defaultdict
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from visdcam_downloader.api.dependencies import get_source_client
from visdcam_downloader.api.errors import http_error


router = APIRouter(prefix="/api/browse", tags=["browse"])

# Every browse call takes ?source=cloud|disk and talks to that source.
B2Dependency = Annotated[object, Depends(get_source_client)]


@router.get("/cameras")
def cameras(b2: B2Dependency) -> list[str]:
    try:
        return b2.list_cameras()
    except Exception as error:
        raise http_error(error) from error


@router.get("/days")
def days(b2: B2Dependency, camera: str = Query(pattern=r"^cam\d+$")) -> list[str]:
    try:
        return b2.list_days(camera)
    except Exception as error:
        raise http_error(error) from error


@router.get("/clips")
def clips(
    b2: B2Dependency,
    camera: str = Query(pattern=r"^cam\d+$"),
    day: str = Query(pattern=r"^\d{4}-\d{2}-\d{2}$"),
) -> dict:
    try:
        found = b2.list_clips_for_day(camera, day)
    except Exception as error:
        raise http_error(error) from error

    hours: dict[int, dict] = defaultdict(lambda: {"count": 0, "bytes": 0})

    for clip in found:
        bucket = hours[clip.end_time.hour]
        bucket["count"] += 1
        bucket["bytes"] += clip.size

    return {
        "camera": camera,
        "day": day,
        "count": len(found),
        "bytes": sum(clip.size for clip in found),
        "hours": [
            {"hour": hour, **summary}
            for hour, summary in sorted(hours.items())
        ],
        "clips": [clip.to_dict() for clip in found],
    }
