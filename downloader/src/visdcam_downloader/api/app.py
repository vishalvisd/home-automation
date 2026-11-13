import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from visdcam_downloader.api.routes import archive, browse, jobs, library, preview, settings
from visdcam_downloader.config import (
    FRONTEND_DIST_DIRECTORY,
    JOBS_FILE,
    RUNTIME_DIRECTORY,
    SETTINGS_FILE,
    ensure_runtime_directories,
)
from visdcam_downloader.services.archive_service import ArchiveService
from visdcam_downloader.services.b2_client import B2Client
from visdcam_downloader.services.job_service import JobService
from visdcam_downloader.services.settings_service import SettingsService
from visdcam_downloader.services.workflows import Workflows


LOGGER = logging.getLogger("visdcam_downloader")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    ensure_runtime_directories()

    settings_service = SettingsService(SETTINGS_FILE)
    b2_client = B2Client(settings_service)
    workflows = Workflows(settings_service, b2_client)

    job_service = JobService(JOBS_FILE)
    job_service.register("download", workflows.download_job)
    job_service.register("timelapse", workflows.timelapse_job)
    job_service.register("archive", workflows.archive_job)

    archive_service = ArchiveService(
        settings_service,
        job_service,
        RUNTIME_DIRECTORY / "archive_state.json",
    )

    app.state.settings_service = settings_service
    app.state.b2_client = b2_client
    app.state.workflows = workflows
    app.state.job_service = job_service
    app.state.archive_service = archive_service

    archive_service.start()
    LOGGER.info("visdcam downloader ready")

    try:
        yield
    finally:
        archive_service.stop()
        job_service.shutdown()


def create_app() -> FastAPI:
    application = FastAPI(title="visdcam downloader", lifespan=lifespan)

    application.include_router(settings.router)
    application.include_router(browse.router)
    application.include_router(jobs.router)
    application.include_router(library.router)
    application.include_router(preview.router)
    application.include_router(archive.router)

    @application.get("/health")
    def health() -> dict:
        return {"status": "healthy"}

    if FRONTEND_DIST_DIRECTORY.is_dir():
        application.mount(
            "/",
            StaticFiles(directory=FRONTEND_DIST_DIRECTORY, html=True),
            name="frontend",
        )

    return application


app = create_app()
