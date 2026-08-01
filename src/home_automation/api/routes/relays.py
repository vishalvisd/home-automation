from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from home_automation.api.dependencies import get_relay_manager
from home_automation.services.relay_manager import (
    RelayManager,
    UnknownRelayError,
)


router = APIRouter(
    prefix="/api/relays",
    tags=["relays"],
)


RelayManagerDependency = Annotated[
    RelayManager,
    Depends(get_relay_manager),
]


@router.post("/{relay_key}/on")
def turn_relay_on(
    relay_key: str,
    relay_manager: RelayManagerDependency,
) -> dict[str, str]:
    """Energise a relay channel."""

    try:
        relay_manager.turn_on(relay_key)
    except UnknownRelayError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(error),
        ) from error

    return {
        "relay": relay_key,
        "command": "on",
    }


@router.post("/{relay_key}/off")
def turn_relay_off(
    relay_key: str,
    relay_manager: RelayManagerDependency,
) -> dict[str, str]:
    """Release a relay channel."""

    try:
        relay_manager.turn_off(relay_key)
    except UnknownRelayError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(error),
        ) from error

    return {
        "relay": relay_key,
        "command": "off",
    }