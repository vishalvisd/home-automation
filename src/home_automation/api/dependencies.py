from fastapi import Request

from home_automation.services.relay_manager import RelayManager
from home_automation.services.watering_service import WateringService
from home_automation.services.automation_script_service import (
    AutomationScriptService,
)
from home_automation.services.watering_scheduler_service import (
    WateringSchedulerService,
)
from home_automation.services.watering_settings_service import (
    WateringSettingsService,
)

from home_automation.services.camera_recorder_service import (
    CameraRecorderService,
)
from home_automation.services.camera_settings_service import (
    CameraSettingsService,
)
from home_automation.services.backblaze_credentials_service import (
    BackblazeCredentialsService,
)


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

def get_camera_settings_service(
    request: Request,
) -> CameraSettingsService:
    return request.app.state.camera_settings_service

def get_camera_recorder_service(
    request: Request,
) -> CameraRecorderService:
    return request.app.state.camera_recorder_service

def get_backblaze_credentials_service(
    request: Request,
) -> BackblazeCredentialsService:
    return request.app.state.backblaze_credentials_service