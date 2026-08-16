from typing import Annotated

from fastapi import APIRouter, Depends

from home_automation.api.dependencies import (
    get_camera_recorder_service,
    get_camera_settings_service,
)
from home_automation.config.camera_settings import (
    CameraSettings,
)
from home_automation.services.camera_recorder_service import (
    CameraRecorderService,
)
from home_automation.services.camera_settings_service import (
    CameraSettingsService,
)

from pydantic import BaseModel, Field

from home_automation.api.dependencies import (
    get_backblaze_credentials_service,
)
from home_automation.config.backblaze_credentials import (
    BackblazeCredentials,
)
from home_automation.services.backblaze_credentials_service import (
    BackblazeCredentialsService,
)

router = APIRouter(
    prefix="/api/cameras",
    tags=["cameras"],
)


CameraSettingsDependency = Annotated[
    CameraSettingsService,
    Depends(get_camera_settings_service),
]

CameraRecorderDependency = Annotated[
    CameraRecorderService,
    Depends(get_camera_recorder_service),
]

class BackblazeCredentialsRequest(BaseModel):
    key_id: str = Field(min_length=1)
    application_key: str = Field(min_length=1)


BackblazeCredentialsDependency = Annotated[
    BackblazeCredentialsService,
    Depends(get_backblaze_credentials_service),
]

@router.get("/settings")
def get_settings(
    service: CameraSettingsDependency,
) -> CameraSettings:
    return service.get()


@router.put("/settings")
def save_settings(
    settings: CameraSettings,
    service: CameraSettingsDependency,
) -> CameraSettings:
    """
    Persist camera settings.

    Recording pipeline changes take effect the next time
    recording is started.
    """

    return service.save(settings)


@router.get("/recording/status")
def recording_status(
    recorder: CameraRecorderDependency,
) -> dict:
    return recorder.status()


@router.post("/recording/start")
def start_recording(
    recorder: CameraRecorderDependency,
) -> dict:
    return recorder.start()


@router.post("/recording/stop")
def stop_recording(
    recorder: CameraRecorderDependency,
) -> dict:
    return recorder.stop()

@router.get(
    "/backblaze/credentials"
)
def get_backblaze_credentials(
    service: BackblazeCredentialsDependency,
) -> dict:
    return service.status()


@router.put(
    "/backblaze/credentials"
)
def save_backblaze_credentials(
    request: BackblazeCredentialsRequest,
    service: BackblazeCredentialsDependency,
) -> dict:
    service.save(
        BackblazeCredentials(
            key_id=request.key_id.strip(),
            application_key=(
                request.application_key.strip()
            ),
        )
    )

    return service.status()