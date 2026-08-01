from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from home_automation.api.routes import health, relays
from home_automation.services.relay_manager import RelayManager


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

    return application


app = create_app()