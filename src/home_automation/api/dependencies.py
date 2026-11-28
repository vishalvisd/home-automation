from fastapi import HTTPException, Request

from home_automation.services.relay_manager import RelayManager
from home_automation.services.watering_service import WateringService
from home_automation.services.automation_script_service import (
    AutomationScriptService,
)
from home_automation.services.automation_passphrase_service import (
    AutomationPassphraseService,
)
from home_automation.services.watering_scheduler_service import (
    WateringSchedulerService,
)
from home_automation.services.watering_settings_service import (
    WateringSettingsService,
)

from home_automation.services.camera_upload_service import (
    CameraUploadService,
)
from home_automation.services.camera_recorder_service import (
    CameraRecorderService,
)
from home_automation.services.camera_settings_service import (
    CameraSettingsService,
)
from home_automation.services.camera_preset_service import (
    CameraPresetService,
)
from home_automation.services.backblaze_credentials_service import (
    BackblazeCredentialsService,
)
from home_automation.services.live_view_service import LiveViewService
from home_automation.services.archive_service import ArchiveService
from home_automation.services.cloud_rotation_service import (
    CloudRotationService,
)
from home_automation.services.router_restart_service import (
    RouterRestartService,
)
from home_automation.services.mic_receiver_service import MicReceiverService
from home_automation.services.mic_settings_service import MicSettingsService
from home_automation.services.mic_store_service import MicStoreService
from home_automation.services.passphrase_service import PassphraseService


def get_relay_manager(request: Request) -> RelayManager:
    """Return the application-wide relay manager."""

    return request.app.state.relay_manager

def get_watering_service(request: Request) -> WateringService:
    """Return the application-wide watering service."""

    return request.app.state.watering_service

def get_watering_settings_service(
    request: Request,
) -> WateringSettingsService:
    return request.app.state.watering_settings_service


def get_watering_scheduler_service(
    request: Request,
) -> WateringSchedulerService:
    return request.app.state.watering_scheduler_service


def get_automation_script_service(
    request: Request,
) -> AutomationScriptService:
    return request.app.state.automation_script_service


def get_automation_passphrase_service(
    request: Request,
) -> AutomationPassphraseService:
    return request.app.state.automation_passphrase_service

def get_camera_settings_service(
    request: Request,
) -> CameraSettingsService:
    return request.app.state.camera_settings_service

def get_camera_recorder_service(
    request: Request,
) -> CameraRecorderService:
    return request.app.state.camera_recorder_service


def get_camera_upload_service(
    request: Request,
) -> CameraUploadService:
    return request.app.state.camera_upload_service

def get_camera_preset_service(
    request: Request,
) -> CameraPresetService:
    return request.app.state.camera_preset_service

def get_backblaze_credentials_service(
    request: Request,
) -> BackblazeCredentialsService:
    return request.app.state.backblaze_credentials_service

def get_live_view_service(
    request: Request,
) -> LiveViewService:
    return request.app.state.live_view_service


def get_cloud_rotation_service(
    request: Request,
) -> CloudRotationService:
    return request.app.state.cloud_rotation_service


def get_archive_service(
    request: Request,
) -> ArchiveService:
    return request.app.state.archive_service


def get_router_restart_service(
    request: Request,
) -> RouterRestartService:
    return request.app.state.router_restart_service


def _mic_service(request: Request, name: str):
    """
    A microphone service, or "503" when that part did not start. The
    backend runs without the microphones rather than not at all.
    """

    service = getattr(request.app.state, name, None)

    if service is None:
        raise HTTPException(
            status_code=503,
            detail=(
                "The microphone part of the backend did not start. "
                "See the backend log."
            ),
        )

    return service


def get_mic_settings_service(
    request: Request,
) -> MicSettingsService:
    return _mic_service(request, "mic_settings_service")


def get_mic_passphrase_service(
    request: Request,
) -> PassphraseService:
    return _mic_service(request, "mic_passphrase_service")


def get_mic_receiver_service(
    request: Request,
) -> MicReceiverService:
    return _mic_service(request, "mic_receiver_service")


def get_mic_store_service(
    request: Request,
) -> MicStoreService:
    return _mic_service(request, "mic_store_service")
