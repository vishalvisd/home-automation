import sys
from typing import Annotated

from fastapi import APIRouter, Depends

from visdcam_downloader.api.dependencies import (
    get_b2_client,
    get_settings_service,
    get_workflows,
)
from visdcam_downloader.api.errors import http_error
from visdcam_downloader.services.b2_client import B2Client
from visdcam_downloader.services.settings_service import SettingsService
from visdcam_downloader.services.workflows import Workflows


router = APIRouter(prefix="/api", tags=["settings"])

SettingsDependency = Annotated[SettingsService, Depends(get_settings_service)]
B2Dependency = Annotated[B2Client, Depends(get_b2_client)]
WorkflowsDependency = Annotated[Workflows, Depends(get_workflows)]


@router.get("/settings")
def get_settings(service: SettingsDependency) -> dict:
    return service.get().public_view()


@router.put("/settings")
def update_settings(
    changes: dict,
    service: SettingsDependency,
    b2: B2Dependency,
) -> dict:
    try:
        settings = service.update(changes)
    except Exception as error:
        raise http_error(ValueError(str(error))) from error

    b2.reset()
    return settings.public_view()


@router.post("/settings/test")
def test_connection(b2: B2Dependency) -> dict:
    try:
        return b2.test_connection()
    except Exception as error:
        raise http_error(error) from error


@router.get("/system")
def system_info(
    service: SettingsDependency,
    workflows: WorkflowsDependency,
) -> dict:
    settings = service.get()
    tools = workflows.tools()

    encoders: list[str] = []
    if tools.available():
        try:
            encoders = tools.video_encoder_candidates()
        except Exception:
            encoders = []

    return {
        "platform": sys.platform,
        "ffmpeg_available": tools.available(),
        "ffmpeg_path": tools.ffmpeg,
        "ffmpeg_version": tools.version(),
        "video_encoders": encoders,
        "b2_configured": settings.has_b2_credentials(),
        "output_directory": settings.output_directory,
    }
