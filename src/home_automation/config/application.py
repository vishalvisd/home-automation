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
BACKBLAZE_CREDENTIALS_FILE = (
    RUNTIME_DIRECTORY / "backblaze_credentials.json"
)