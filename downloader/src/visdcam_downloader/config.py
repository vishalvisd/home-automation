import os
import sys
from pathlib import Path

from pydantic import BaseModel, Field


# downloader/ folder inside the home-automation repository.
PROJECT_ROOT = Path(__file__).resolve().parents[2]

FRONTEND_DIST_DIRECTORY = PROJECT_ROOT / "frontend" / "dist"

# Everything machine-specific lives here. Gitignored.
RUNTIME_DIRECTORY = PROJECT_ROOT / "runtime"
SETTINGS_FILE = RUNTIME_DIRECTORY / "settings.json"
JOBS_FILE = RUNTIME_DIRECTORY / "jobs.json"
PREVIEW_CACHE_DIRECTORY = RUNTIME_DIRECTORY / "preview_cache"
TEMP_DIRECTORY = RUNTIME_DIRECTORY / "tmp"

HOST = "127.0.0.1"
PORT = 8800


def default_output_directory() -> Path:
    home = Path.home()

    if sys.platform == "win32":
        return home / "Videos" / "visdcam"

    if sys.platform == "darwin":
        return home / "Movies" / "visdcam"

    return home / "Videos" / "visdcam"


class Settings(BaseModel):
    """Persistent local settings. The application key never leaves this machine."""

    # Backblaze B2. Use an application key restricted to the bucket.
    b2_key_id: str = ""
    b2_application_key: str = ""
    b2_bucket: str = ""

    # Where joined videos and time-lapses go.
    output_directory: str = str(default_output_directory())

    # Clip names on the Pi use this timezone and carry the clip END time.
    clip_timezone: str = "Asia/Kolkata"
    segment_seconds: int = Field(default=180, ge=10)

    # Parallel downloads from B2.
    parallel_downloads: int = Field(default=4, ge=1, le=16)

    # Optional explicit ffmpeg location (Windows users often need this).
    ffmpeg_path: str = ""

    # Local archive: mirror every clip to a local disk before B2 deletes it.
    archive_enabled: bool = False
    archive_directory: str = str(default_output_directory() / "archive")
    archive_time: str = "03:00"
    archive_keep_days: int = Field(default=0, ge=0)  # 0 = keep forever

    def has_b2_credentials(self) -> bool:
        return bool(
            self.b2_key_id.strip()
            and self.b2_application_key.strip()
            and self.b2_bucket.strip()
        )

    def public_view(self) -> dict:
        """Settings as sent to the UI. The secret is never returned."""

        data = self.model_dump()
        data["b2_application_key"] = ""
        data["b2_application_key_set"] = bool(
            self.b2_application_key.strip()
        )
        return data


def ensure_runtime_directories() -> None:
    for directory in (
        RUNTIME_DIRECTORY,
        PREVIEW_CACHE_DIRECTORY,
        TEMP_DIRECTORY,
    ):
        directory.mkdir(parents=True, exist_ok=True)

    if os.name == "posix":
        try:
            RUNTIME_DIRECTORY.chmod(0o700)
        except OSError:
            pass
