from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from home_automation.api.routes import health, relays, watering
from home_automation.services.watering_service import WateringService
from home_automation.services.relay_manager import RelayManager
from fastapi.staticfiles import StaticFiles
from home_automation.config.logging import configure_logging

from home_automation.api.routes import (
    automations,
    health,
    relays,
    watering,
)

from home_automation.config.application import (
    AUTOMATION_RUNTIME_DIRECTORY,
    AUTOMATION_TEMPLATE_DIRECTORY,
    FRONTEND_DIST_DIRECTORY,
    WATERING_SCHEDULE_STATE_FILE,
    WATERING_SETTINGS_FILE,
)

from home_automation.services.automation_script_service import (
    AutomationScriptService,
)
from home_automation.services.watering_scheduler_service import (
    WateringSchedulerService,
)
from home_automation.services.watering_settings_service import (
    WateringSettingsService,
)

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """
    Create one relay manager for the complete backend lifetime.

    This ensures that only one process owns and controls the General-Purpose
    Input/Output pins.
    """

    relay_manager = RelayManager()

    watering_settings_service = WateringSettingsService(
        WATERING_SETTINGS_FILE
    )

    watering_service = WateringService(
        relay_manager,
        watering_settings_service,
    )

    watering_scheduler_service = WateringSchedulerService(
        watering_settings_service,
        watering_service,
        WATERING_SCHEDULE_STATE_FILE,
    )

    automation_script_service = AutomationScriptService(
        AUTOMATION_TEMPLATE_DIRECTORY,
        AUTOMATION_RUNTIME_DIRECTORY,
    )

    app.state.relay_manager = relay_manager
    app.state.watering_settings_service = watering_settings_service
    app.state.watering_service = watering_service
    app.state.watering_scheduler_service = watering_scheduler_service
    app.state.automation_script_service = automation_script_service

    watering_scheduler_service.start()

    try:
        yield

    finally:
        watering_scheduler_service.stop()
        watering_service.shutdown()
        relay_manager.close()


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    configure_logging()

    application = FastAPI(
        title="Home Automation",
        lifespan=lifespan,
    )
    application.include_router(health.router)
    application.include_router(relays.router)
    application.include_router(watering.router)
    application.include_router(automations.router)
    # Mount the compiled React application last so API routes and
    # FastAPI documentation routes continue to take precedence.
    if FRONTEND_DIST_DIRECTORY.is_dir():
        application.mount(
            "/",
            StaticFiles(
                directory=FRONTEND_DIST_DIRECTORY,
                html=True,
            ),
            name="frontend",
        )

    return application


app = create_app()