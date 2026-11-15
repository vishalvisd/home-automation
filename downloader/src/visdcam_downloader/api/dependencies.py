from fastapi import Request

from visdcam_downloader.services.b2_client import B2Client
from visdcam_downloader.services.job_service import JobService
from visdcam_downloader.services.settings_service import SettingsService
from visdcam_downloader.services.workflows import Workflows


def get_settings_service(request: Request) -> SettingsService:
    return request.app.state.settings_service


def get_b2_client(request: Request) -> B2Client:
    return request.app.state.b2_client


def get_job_service(request: Request) -> JobService:
    return request.app.state.job_service


def get_workflows(request: Request) -> Workflows:
    return request.app.state.workflows

