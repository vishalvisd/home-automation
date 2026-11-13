from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from visdcam_downloader.api.dependencies import get_archive_service
from visdcam_downloader.services.archive_service import ArchiveService


router = APIRouter(prefix="/api/archive", tags=["archive"])

ArchiveDependency = Annotated[ArchiveService, Depends(get_archive_service)]


@router.get("/status")
def archive_status(service: ArchiveDependency) -> dict:
    return service.status()


@router.post("/run")
def run_archive(service: ArchiveDependency) -> dict:
    try:
        return service.run_now()
    except RuntimeError as error:
        raise HTTPException(status.HTTP_409_CONFLICT, str(error)) from error
