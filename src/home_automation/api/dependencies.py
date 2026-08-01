from fastapi import Request

from home_automation.services.relay_manager import RelayManager


def get_relay_manager(request: Request) -> RelayManager:
    """Return the application-wide relay manager."""

    return request.app.state.relay_manager