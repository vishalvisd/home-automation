from fastapi import Request

from home_automation.services.relay_manager import RelayManager
from home_automation.services.watering_service import WateringService

def get_relay_manager(request: Request) -> RelayManager:
    """Return the application-wide relay manager."""

    return request.app.state.relay_manager

def get_watering_service(request: Request) -> WateringService:
    """Return the application-wide watering service."""

    return request.app.state.watering_service