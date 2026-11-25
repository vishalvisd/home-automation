from typing import Annotated
from urllib.parse import unquote

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field

from home_automation.api.dependencies import (
    get_automation_passphrase_service,
    get_automation_script_service,
)
from home_automation.services.automation_passphrase_service import (
    AutomationPassphraseService,
    InvalidPassphraseError,
    PassphraseAlreadySetError,
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


PassphraseServiceDependency = Annotated[
    AutomationPassphraseService,
    Depends(get_automation_passphrase_service),
]


class AutomationSourceUpdate(BaseModel):
    source: str = Field(min_length=1)


class PassphraseBody(BaseModel):
    passphrase: str


def require_passphrase(
    passphrases: PassphraseServiceDependency,
    x_automations_passphrase: Annotated[str | None, Header()] = None,
) -> None:
    """
    Guard for every address that shows, edits or runs a script.

    The page sends the passphrase with each request in the
    X-Automations-Passphrase header, percent-encoded because a header
    cannot carry every character.
    """

    if not passphrases.is_set():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Set a passphrase for the automation scripts first.",
        )

    given = unquote(x_automations_passphrase or "")

    if not passphrases.check(given):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Wrong passphrase.",
        )


PassphraseRequired = Depends(require_passphrase)


# The three passphrase addresses come before "/{key}", or "passphrase"
# would be taken for the name of a script.

@router.get("/passphrase")
def passphrase_state(
    passphrases: PassphraseServiceDependency,
) -> dict:
    """Open to anyone: says only whether a passphrase has been set."""

    return {"set": passphrases.is_set()}


@router.post("/passphrase")
def set_passphrase(
    body: PassphraseBody,
    passphrases: PassphraseServiceDependency,
) -> dict:
    """Sets the passphrase the first time. Refused once one is set."""

    try:
        passphrases.set_first(body.passphrase)
    except InvalidPassphraseError as error:
        raise HTTPException(
            status_code=422,
            detail=str(error),
        ) from error
    except PassphraseAlreadySetError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(error),
        ) from error

    return {"set": True}


@router.post("/passphrase/check", dependencies=[PassphraseRequired])
def check_passphrase() -> dict:
    """Answers 200 when the passphrase in the header is right."""

    return {"ok": True}


@router.get("", dependencies=[PassphraseRequired])
def list_automations(
    service: AutomationServiceDependency,
) -> list[dict]:
    return service.list()


@router.get("/{key}", dependencies=[PassphraseRequired])
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


@router.put("/{key}", dependencies=[PassphraseRequired])
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


@router.post("/{key}/restore", dependencies=[PassphraseRequired])
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


@router.post("/{key}/run", dependencies=[PassphraseRequired])
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