import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from home_automation.api.routes import (
    automations,
    cameras,
    health,
    mics,
    relays,
    watering,
)
from home_automation.config.application import (
    AUTOMATION_PASSPHRASE_FILE,
    AUTOMATION_RUNTIME_DIRECTORY,
    AUTOMATION_TEMPLATE_DIRECTORY,
    CAMERA_PRESET_STATE_FILE,
    CAMERA_SETTINGS_FILE,
    CLOUD_ROTATION_STATE_FILE,
    DISK_ACTIVITY_LOG_FILE,
    RECORDING_STATS_FILE,
    FRONTEND_DIST_DIRECTORY,
    GO2RTC_CONFIG_FILE,
    GO2RTC_SERVICE_NAME,
    LIVE_VIEW_PORT,
    MIC_LISTEN_PORT,
    MIC_PASSPHRASE_FILE,
    MIC_SETTINGS_FILE,
    MIC_STORAGE_DIRECTORY,
    WATERING_SCHEDULE_STATE_FILE,
    WATERING_SETTINGS_FILE,
    BACKBLAZE_CREDENTIALS_FILE,
)
from home_automation.config.logging import configure_logging
from home_automation.services.archive_service import ArchiveService
from home_automation.services.disk_activity_log import DiskActivityLog
from home_automation.services.automation_passphrase_service import (
    AutomationPassphraseService,
)
from home_automation.services.automation_script_service import (
    AutomationScriptService,
)
from home_automation.services.camera_recorder_service import (
    CameraRecorderService,
)
from home_automation.services.camera_preset_service import (
    CameraPresetService,
)
from home_automation.services.camera_settings_service import (
    CameraSettingsService,
)
from home_automation.services.live_view_service import LiveViewService
from home_automation.services.mic_receiver_service import MicReceiverService
from home_automation.services.mic_settings_service import MicSettingsService
from home_automation.services.mic_store_service import MicStoreService
from home_automation.services.passphrase_service import PassphraseService
from home_automation.services.recording_stats_service import (
    RecordingStatsService,
)
from home_automation.services.relay_manager import RelayManager
from home_automation.services.router_restart_service import (
    RouterRestartService,
)
from home_automation.services.watering_scheduler_service import (
    WateringSchedulerService,
)
from home_automation.services.watering_service import WateringService
from home_automation.services.watering_settings_service import (
    WateringSettingsService,
)
from home_automation.services.camera_upload_service import (
    CameraUploadService,
)

from home_automation.services.backblaze_credentials_service import (
    BackblazeCredentialsService,
)

from home_automation.services.backblaze_b2_storage_provider import (
    BackblazeB2StorageProvider,
)
from home_automation.services.cloud_rotation_service import (
    CloudRotationService,
)

LOGGER = logging.getLogger("home_automation")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """
    Create application services for the complete backend lifetime.
    """

    configure_logging()

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

    automation_passphrase_service = AutomationPassphraseService(
        AUTOMATION_PASSPHRASE_FILE
    )

    camera_settings_service = CameraSettingsService(
        CAMERA_SETTINGS_FILE
    )

    backblaze_credentials_service = (
        BackblazeCredentialsService(
            BACKBLAZE_CREDENTIALS_FILE
        )
    )

    # Old installs kept one key pair and the bucket name in cameras.json.
    # Fold them into a one-account list once.
    backblaze_credentials_service.migrate_single_key(
        _legacy_bucket_name(CAMERA_SETTINGS_FILE)
    )

    cloud_rotation_service = CloudRotationService(
        backblaze_credentials_service,
        CLOUD_ROTATION_STATE_FILE,
    )

    backblaze_b2_storage_provider = BackblazeB2StorageProvider(
        camera_settings_service,
        cloud_rotation_service,
    )

    recording_stats_service = RecordingStatsService(RECORDING_STATS_FILE)

    router_restart_service = RouterRestartService(
        camera_settings_service,
        relay_manager,
    )

    camera_upload_service = CameraUploadService(
        camera_settings_service,
        backblaze_b2_storage_provider,
        recording_stats_service,
        cloud_rotation_service,
        router_restart_service,
    )

    archive_service = ArchiveService(
        camera_settings_service,
        recording_stats_service,
        DiskActivityLog(DISK_ACTIVITY_LOG_FILE),
    )

    camera_recorder_service = CameraRecorderService(
        camera_settings_service,
        camera_upload_service,
        archive_service,
        recording_stats_service,
    )

    camera_preset_service = CameraPresetService(
        camera_settings_service,
        CAMERA_PRESET_STATE_FILE,
    )

    live_view_service = LiveViewService(
        camera_settings_service,
        GO2RTC_CONFIG_FILE,
        GO2RTC_SERVICE_NAME,
        LIVE_VIEW_PORT,
    )

    app.state.relay_manager = relay_manager
    app.state.watering_settings_service = watering_settings_service
    app.state.watering_service = watering_service
    app.state.watering_scheduler_service = watering_scheduler_service
    app.state.automation_script_service = automation_script_service
    app.state.automation_passphrase_service = automation_passphrase_service
    app.state.camera_settings_service = camera_settings_service
    app.state.camera_recorder_service = camera_recorder_service
    app.state.camera_upload_service = camera_upload_service
    app.state.archive_service = archive_service
    app.state.camera_preset_service = camera_preset_service
    app.state.backblaze_credentials_service = backblaze_credentials_service
    app.state.cloud_rotation_service = cloud_rotation_service
    app.state.router_restart_service = router_restart_service
    app.state.live_view_service = live_view_service

    mic_receiver_service, mic_store_service = _start_microphones(
        app,
        camera_settings_service,
    )

    watering_scheduler_service.start()
    camera_preset_service.start()
    archive_service.start()
    camera_recorder_service.start_if_enabled()

    # Keep go2rtc's camera list in step with ours. Harmless when go2rtc
    # is not installed: it only logs a warning.
    live_view_service.sync()

    try:
        yield

    finally:
        _stop_microphones(mic_receiver_service, mic_store_service)
        camera_recorder_service.shutdown()
        camera_preset_service.stop()
        camera_upload_service.shutdown()
        # After the recorders, so the last clips are on the disk.
        archive_service.shutdown()
        recording_stats_service.shutdown()
        watering_scheduler_service.stop()
        watering_service.shutdown()
        relay_manager.close()


def _start_microphones(
    app: FastAPI,
    camera_settings_service: CameraSettingsService,
) -> tuple[MicReceiverService | None, MicStoreService | None]:
    """
    Start the room microphone part. If it cannot start, the rest of the
    backend runs without it: the cameras must never wait for a
    microphone.
    """

    app.state.mic_settings_service = None
    app.state.mic_passphrase_service = None
    app.state.mic_receiver_service = None
    app.state.mic_store_service = None

    try:
        mic_settings_service = MicSettingsService(MIC_SETTINGS_FILE)

        mic_passphrase_service = PassphraseService(
            MIC_PASSPHRASE_FILE,
            label="Microphone",
        )

        mic_receiver_service = MicReceiverService(
            mic_settings_service,
            MIC_STORAGE_DIRECTORY,
            MIC_LISTEN_PORT,
        )

        mic_store_service = MicStoreService(
            mic_settings_service,
            MIC_STORAGE_DIRECTORY,
            mic_receiver_service.files_in_use,
            # The sound gives way a little before the disk copy would
            # drop a camera clip.
            lambda: camera_settings_service.get().archive_buffer_reserve_mb,
        )

        mic_receiver_service.start()
        mic_store_service.start()
    except Exception:
        LOGGER.exception(
            "The microphones could not be started; the rest of the "
            "backend runs without them"
        )
        return None, None

    app.state.mic_settings_service = mic_settings_service
    app.state.mic_passphrase_service = mic_passphrase_service
    app.state.mic_receiver_service = mic_receiver_service
    app.state.mic_store_service = mic_store_service

    return mic_receiver_service, mic_store_service


def _stop_microphones(
    mic_receiver_service: MicReceiverService | None,
    mic_store_service: MicStoreService | None,
) -> None:
    """Finish the files being written. Never holds up the shutdown."""

    try:
        if mic_receiver_service is not None:
            mic_receiver_service.stop()

        if mic_store_service is not None:
            mic_store_service.stop()
    except Exception:
        LOGGER.exception("Error while stopping the microphones")


def _legacy_bucket_name(settings_file) -> str:
    """b2_bucket from a cameras.json written before account rotation."""

    try:
        import json

        raw = json.loads(settings_file.read_text(encoding="utf-8"))
        return str(raw.get("b2_bucket", "") or "")
    except Exception:
        return ""


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""

    application = FastAPI(
        title="Home Automation",
        lifespan=lifespan,
    )
    application.include_router(health.router)
    application.include_router(relays.router)
    application.include_router(watering.router)
    application.include_router(automations.router)
    application.include_router(cameras.router)
    application.include_router(mics.router)
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