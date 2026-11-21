from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse

from home_automation.api.dependencies import (
    get_archive_service,
    get_camera_preset_service,
    get_camera_recorder_service,
    get_camera_settings_service,
    get_live_view_service,
)
from home_automation.config.camera_settings import (
    CameraSettings,
)
from home_automation.services.camera_recorder_service import (
    CameraRecorderService,
)
from home_automation.services.camera_preset_service import (
    CameraPresetService,
)
from home_automation.services.camera_settings_service import (
    CameraSettingsService,
)
from home_automation.services.live_view_service import LiveViewService
from home_automation.services.archive_service import ArchiveService

from pydantic import BaseModel, Field

from home_automation.api.dependencies import (
    get_backblaze_credentials_service,
    get_cloud_rotation_service,
)
from home_automation.services.backblaze_b2_storage_provider import (
    test_account,
)
from home_automation.services.backblaze_credentials_service import (
    BackblazeCredentialsService,
)
from home_automation.services.cloud_rotation_service import (
    CloudRotationService,
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

CameraPresetDependency = Annotated[
    CameraPresetService,
    Depends(get_camera_preset_service),
]

LiveViewDependency = Annotated[
    LiveViewService,
    Depends(get_live_view_service),
]

ArchiveDependency = Annotated[
    ArchiveService,
    Depends(get_archive_service),
]

class BackblazeAccountRequest(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    key_id: str = Field(min_length=1)
    # Empty keeps the key already stored for an account of this name.
    application_key: str = ""
    bucket: str = Field(min_length=1)
    enabled: bool = True


class BackblazeAccountsRequest(BaseModel):
    accounts: list[BackblazeAccountRequest]


BackblazeCredentialsDependency = Annotated[
    BackblazeCredentialsService,
    Depends(get_backblaze_credentials_service),
]

CloudRotationDependency = Annotated[
    CloudRotationService,
    Depends(get_cloud_rotation_service),
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
    live_view: LiveViewDependency,
) -> CameraSettings:
    """
    Persist camera settings.

    Recording pipeline changes take effect the next time
    recording is started. Live view (go2rtc) is updated at once.
    """

    saved = service.save(settings)
    live_view.sync()
    return saved


@router.get("/archive")
def archive_status(
    archive: ArchiveDependency,
) -> dict:
    return archive.status()


@router.post("/archive/flush")
def archive_flush(
    archive: ArchiveDependency,
) -> dict:
    """Run one batch now: mount, copy waiting clips, park."""

    return archive.flush(reason="manual")


@router.get("/archive/cameras")
def archive_cameras(archive: ArchiveDependency) -> list[str]:
    """Cameras with clips on the disk. Wakes the disk."""

    try:
        return archive.list_cameras()
    except Exception as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


@router.get("/archive/days")
def archive_days(
    archive: ArchiveDependency,
    camera: str = Query(pattern=r"^cam\d+$"),
) -> list[str]:
    try:
        return archive.list_days(camera)
    except Exception as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


@router.get("/archive/clips")
def archive_clips(
    archive: ArchiveDependency,
    camera: str = Query(pattern=r"^cam\d+$"),
    day: str = Query(pattern=r"^\d{4}-\d{2}-\d{2}$"),
) -> list[dict]:
    try:
        return archive.list_clips(camera, day)
    except Exception as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


@router.get("/archive/file")
def archive_file(
    archive: ArchiveDependency,
    key: str = Query(),
) -> FileResponse:
    """One clip from the disk, for the downloader."""

    try:
        path = archive.clip_path(key)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Clip not on the disk")
    except Exception as error:
        raise HTTPException(status_code=503, detail=str(error)) from error

    return FileResponse(path, media_type="video/mp4", filename=path.name)


@router.get("/live")
def live_view_status(
    live_view: LiveViewDependency,
) -> dict:
    return live_view.status()


@router.post("/live/sync")
def live_view_sync(
    live_view: LiveViewDependency,
) -> dict:
    return live_view.sync()


@router.get("/preset/status")
def preset_status(
    service: CameraPresetDependency,
) -> dict:
    return service.status()


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

@router.get("/backblaze/accounts")
def get_backblaze_accounts(
    service: BackblazeCredentialsDependency,
) -> dict:
    """Account list without the application keys."""

    return service.status()


@router.get("/backblaze/accounts/export")
def export_backblaze_accounts(
    service: BackblazeCredentialsDependency,
) -> dict:
    """
    The full account list including application keys, for the
    downloader on the Mac, which looks in every account for a day's
    clips. This is the one endpoint that returns secrets. The Pi API
    has no login yet (camera passwords are likewise visible in
    /settings); the planned passphrase login will cover both.
    """

    return service.get().model_dump()


@router.put("/backblaze/accounts")
def save_backblaze_accounts(
    request: BackblazeAccountsRequest,
    service: BackblazeCredentialsDependency,
) -> dict:
    try:
        service.save_from_request(
            [account.model_dump() for account in request.accounts]
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    return service.status()


@router.post("/backblaze/accounts/test")
def test_backblaze_account(
    request: BackblazeAccountRequest,
    service: BackblazeCredentialsDependency,
) -> dict:
    """
    Authorise one account and look up its bucket, uploading nothing.
    An empty application key means the one stored under that name.
    """

    try:
        account = service.account_from_request(request.model_dump())
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    return test_account(account)


@router.get("/backblaze/rotation")
def backblaze_rotation(
    rotation: CloudRotationDependency,
) -> dict:
    """Which account each recent day went to, and today's."""

    return rotation.status()
