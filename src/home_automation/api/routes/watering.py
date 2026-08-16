from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from home_automation.api.dependencies import (
    get_watering_scheduler_service,
    get_watering_service,
    get_watering_settings_service,
)
from home_automation.config.watering_settings import WateringSettings
from home_automation.services.watering_scheduler_service import (
    WateringSchedulerService,
)
from home_automation.services.watering_service import (
    WateringAlreadyRunningError,
    WateringService,
)
from home_automation.services.watering_settings_service import (
    WateringSettingsService,
)


router = APIRouter(
    prefix="/api/watering",
    tags=["watering"],
)


WateringServiceDependency = Annotated[
    WateringService,
    Depends(get_watering_service),
]

SettingsServiceDependency = Annotated[
    WateringSettingsService,
    Depends(get_watering_settings_service),
]

SchedulerServiceDependency = Annotated[
    WateringSchedulerService,
    Depends(get_watering_scheduler_service),
]


@router.post("/start")
def start_watering(
    service: WateringServiceDependency,
) -> dict[str, str]:
    """
    Start watering manually.

    Manual execution is allowed even when scheduled watering is disabled.
    """

    try:
        service.start()
    except WateringAlreadyRunningError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(error),
        ) from error

    return {
        "command": "watering_started",
    }


@router.post("/stop")
def stop_watering(
    service: WateringServiceDependency,
) -> dict[str, str]:
    service.stop()

    return {
        "command": "watering_stop_requested",
    }


@router.get("/status")
def watering_status(
    service: WateringServiceDependency,
    scheduler: SchedulerServiceDependency,
) -> dict:
    process_status = service.status()

    return {
        **process_status,
        "schedule": scheduler.status(),
    }


@router.get("/settings")
def get_settings(
    service: SettingsServiceDependency,
) -> WateringSettings:
    return service.get()


@router.put("/settings")
def save_settings(
    settings: WateringSettings,
    service: SettingsServiceDependency,
) -> WateringSettings:
    return service.save(settings)