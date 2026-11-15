from pathlib import Path


# Repository root containing frontend/, src/, and scripts/.
PROJECT_ROOT = Path(__file__).resolve().parents[3]

FRONTEND_DIST_DIRECTORY = PROJECT_ROOT / "frontend" / "dist"

RUNTIME_DIRECTORY = PROJECT_ROOT / "runtime"

WATERING_SETTINGS_FILE = (
    RUNTIME_DIRECTORY / "watering.json"
)

WATERING_SCHEDULE_STATE_FILE = (
    RUNTIME_DIRECTORY / "watering_schedule_state.json"
)

AUTOMATION_TEMPLATE_DIRECTORY = (
    PROJECT_ROOT / "automation_templates"
)

AUTOMATION_RUNTIME_DIRECTORY = (
    RUNTIME_DIRECTORY / "automations"
)

CAMERA_SETTINGS_FILE = RUNTIME_DIRECTORY / "cameras.json"
CAMERA_PRESET_STATE_FILE = (
    RUNTIME_DIRECTORY / "camera_preset_state.json"
)
BACKBLAZE_CREDENTIALS_FILE = (
    RUNTIME_DIRECTORY / "backblaze_credentials.json"
)
# Live view in the browser is served by go2rtc, a separate systemd
# service on the Pi (scripts/install_go2rtc.sh). The backend writes its
# config file from the camera list and restarts it when that changes.
GO2RTC_CONFIG_FILE = RUNTIME_DIRECTORY / "go2rtc.yaml"
GO2RTC_SERVICE_NAME = "go2rtc"
LIVE_VIEW_PORT = 1984
