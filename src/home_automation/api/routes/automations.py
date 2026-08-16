from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from home_automation.api.dependencies import (
    get_automation_script_service,
)
from home_automation.services.automation_script_service import (
    AutomationAlreadyRunningError,
    AutomationScriptService,
    UnknownAutomationError,
)


router = APIRouter(
    prefix="/api/automations",
    tags=["automations"],
)


AutomationServiceDependency = Annotated[
    AutomationScriptService,
    Depends(get_automation_script_service),
]


class AutomationSourceUpdate(BaseModel):
    source: str = Field(min_length=1)


@router.get("")
def list_automations(
    service: AutomationServiceDependency,
) -> list[dict]:
    return service.list()


@router.get("/{key}")
def get_automation(
    key: str,
    service: AutomationServiceDependency,
) -> dict:
    try:
        return service.get(key)
    except UnknownAutomationError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(error),
        ) from error


@router.put("/{key}")
def save_automation(
    key: str,
    update: AutomationSourceUpdate,
    service: AutomationServiceDependency,
) -> dict:
    try:
        return service.save(
            key,
            update.source,
        )
    except UnknownAutomationError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(error),
        ) from error


@router.post("/{key}/restore")
def restore_automation(
    key: str,
    service: AutomationServiceDependency,
) -> dict:
    try:
        return service.restore(key)
    except UnknownAutomationError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(error),
        ) from error


@router.post("/{key}/run")
def run_automation(
    key: str,
    service: AutomationServiceDependency,
) -> dict:
    try:
        return service.run(key)

    except UnknownAutomationError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(error),
        ) from error

    except AutomationAlreadyRunningError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(error),
        ) from error