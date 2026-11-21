from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from visdcam_downloader.api.dependencies import get_job_service
from visdcam_downloader.services.job_service import JobService


router = APIRouter(prefix="/api/jobs", tags=["jobs"])

JobsDependency = Annotated[JobService, Depends(get_job_service)]


class DownloadRequest(BaseModel):
    camera: str = Field(pattern=r"^cam\d+$")
    start: str
    duration_seconds: int = Field(ge=60, le=24 * 3600)
    # "cloud" (Backblaze) or "disk" (the Pi's archive disk)
    source: str = Field(default="cloud", pattern=r"^(cloud|disk)$")


class TimelapseRequest(BaseModel):
    source_path: str = Field(min_length=1)
    speed: int = Field(default=10, ge=1, le=100)
    fps: int = Field(default=30, ge=1, le=120)
    prefer_hevc: bool = False


@router.get("")
def list_jobs(jobs: JobsDependency) -> list[dict]:
    return jobs.list()


@router.post("/download")
def start_download(request: DownloadRequest, jobs: JobsDependency) -> dict:
    try:
        start = datetime.fromisoformat(request.start)
    except ValueError as error:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid start time") from error

    minutes = round(request.duration_seconds / 60)
    where = "Pi disk" if request.source == "disk" else "cloud"
    title = f"{request.camera} {start:%Y-%m-%d %H:%M} for {minutes} min ({where})"

    return jobs.submit("download", title, request.model_dump()).to_dict()


@router.post("/timelapse")
def start_timelapse(request: TimelapseRequest, jobs: JobsDependency) -> dict:
    name = request.source_path.replace("\\", "/").rsplit("/", 1)[-1]
    label = "Convert to MP4" if request.speed == 1 else f"Time-lapse {request.speed}x"
    return jobs.submit("timelapse", f"{label}: {name}", request.model_dump()).to_dict()


@router.post("/{job_id}/cancel")
def cancel_job(job_id: str, jobs: JobsDependency) -> dict:
    job = jobs.cancel(job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown job")
    return job.to_dict()


@router.delete("/{job_id}")
def delete_job(job_id: str, jobs: JobsDependency) -> dict:
    if not jobs.delete(job_id):
        raise HTTPException(status.HTTP_409_CONFLICT, "Job is running or unknown")
    return {"deleted": job_id}
