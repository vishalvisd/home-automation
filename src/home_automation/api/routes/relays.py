from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from home_automation.api.dependencies import (
    get_relay_manager,
    get_router_restart_service,
)
from home_automation.services.relay_manager import (
    RelayManager,
    UnknownRelayError,
)
from home_automation.services.router_restart_service import (
    RouterRestartService,
)


router = APIRouter(
    prefix="/api/relays",
    tags=["relays"],
)


RelayManagerDependency = Annotated[
    RelayManager,
    Depends(get_relay_manager),
]


RouterRestartServiceDependency = Annotated[
    RouterRestartService,
    Depends(get_router_restart_service),
]


@router.post("/router_power/restart")
def restart_router(
    router_restart_service: RouterRestartServiceDependency,
) -> dict:
    """
    Cut the router's power and restore it by itself.

    Switching the router relay on with /router_power/on cuts the power
    until someone switches it off again, and with the router off nobody
    on the home network can reach the Pi to do that. This one always
    brings the power back.
    """

    started = router_restart_service.power_cycle()

    if started is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The router is already being restarted.",
        )

    return {
        "relay": "router_power",
        "command": "restart",
        **started,
    }


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