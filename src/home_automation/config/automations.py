from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AutomationDefinition:
    key: str
    name: str
    description: str
    filename: str


AUTOMATIONS = {
    "restart_router": AutomationDefinition(
        key="restart_router",
        name="Restart Router",
        description="Power-cycle the main router.",
        filename="restart_router.py",
    ),
    "restart_cameras": AutomationDefinition(
        key="restart_cameras",
        name="Restart Cameras",
        description="Power-cycle the camera power line.",
        filename="restart_cameras.py",
    ),
    "restart_router_and_cameras": AutomationDefinition(
        key="restart_router_and_cameras",
        name="Restart Router + Cameras",
        description=(
            "Restart the router and camera power line together."
        ),
        filename="restart_router_and_cameras.py",
    ),
}