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

# Salted hash of the passphrase that guards the automation scripts.
# Delete this file on the Pi to set a new passphrase.
AUTOMATION_PASSPHRASE_FILE = (
    RUNTIME_DIRECTORY / "automation_passphrase.json"
)

CAMERA_SETTINGS_FILE = RUNTIME_DIRECTORY / "cameras.json"
CAMERA_PRESET_STATE_FILE = (
    RUNTIME_DIRECTORY / "camera_preset_state.json"
)
BACKBLAZE_CREDENTIALS_FILE = (
    RUNTIME_DIRECTORY / "backblaze_credentials.json"
)
CLOUD_ROTATION_STATE_FILE = (
    RUNTIME_DIRECTORY / "cloud_rotation_state.json"
)
# Hourly clip counters per camera and copy, saved at most once an hour.
RECORDING_STATS_FILE = RUNTIME_DIRECTORY / "recording_stats.json"
# When the USB disk was woken and parked, while the study is switched on.
DISK_ACTIVITY_LOG_FILE = RUNTIME_DIRECTORY / "disk_activity.csv"
# Live view in the browser is served by go2rtc, a separate systemd
# service on the Pi (scripts/install_go2rtc.sh). The backend writes its
# config file from the camera list and restarts it when that changes.
GO2RTC_CONFIG_FILE = RUNTIME_DIRECTORY / "go2rtc.yaml"
GO2RTC_SERVICE_NAME = "go2rtc"
LIVE_VIEW_PORT = 1984

# Room microphones. The module list and the limits, edited from the UI.
MIC_SETTINGS_FILE = RUNTIME_DIRECTORY / "mics.json"
# Salted hash of the passphrase that guards everything about the
# microphones. Delete this file on the Pi to set a new passphrase.
MIC_PASSPHRASE_FILE = RUNTIME_DIRECTORY / "mic_passphrase.json"
# The stored sound: RAM only, like the camera clips, one folder per
# module. It must be on the same RAM disk as the camera clips, because
# the sound gives way when that disk runs short.
MIC_STORAGE_DIRECTORY = Path("/dev/shm/home-automation/mics")
# The port every module calls. The firmware has the Pi's address and
# this number built in; change both together.
MIC_LISTEN_PORT = 3334
