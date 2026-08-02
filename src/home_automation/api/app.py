from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from home_automation.api.routes import health, relays
from home_automation.services.relay_manager import RelayManager
from fastapi.staticfiles import StaticFiles

from home_automation.config.application import FRONTEND_DIST_DIRECTORY

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """
    Create one relay manager for the complete backend lifetime.

    This ensures that only one process owns and controls the General-Purpose
    Input/Output pins.
    """

    relay_manager = RelayManager()
    app.state.relay_manager = relay_manager

    try:
        yield
    finally:
        relay_manager.close()


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""

    application = FastAPI(
        title="Home Automation",
        lifespan=lifespan,
    )

    application.include_router(health.router)
    application.include_router(relays.router)

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