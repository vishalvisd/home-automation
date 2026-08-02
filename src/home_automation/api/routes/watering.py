from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from home_automation.api.dependencies import get_watering_service
from home_automation.services.watering_service import (
    WateringAlreadyRunningError,
    WateringService,
)


router = APIRouter(
    prefix="/api/watering",
    tags=["watering"],
)


WateringServiceDependency = Annotated[
    WateringService,
    Depends(get_watering_service),
]


@router.post("/start")
def start_watering(
    service: WateringServiceDependency,
) -> dict[str, str]:
    """Start solar-panel cleaning and plant watering."""

    try:
        service.start()
    except WateringAlreadyRunningError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(error),
        ) from error

    return {"command": "watering_started"}


@router.post("/stop")
def stop_watering(
    service: WateringServiceDependency,
) -> dict[str, str]:
    """Request safe termination of watering."""

    service.stop()
    return {"command": "watering_stop_requested"}


@router.get("/status")
def watering_status(
    service: WateringServiceDependency,
) -> dict[str, str | bool | None]:
    """Return watering-process status."""

    return service.status()