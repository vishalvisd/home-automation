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
    """Persistent local settings."""

    # The Raspberry Pi running home-automation. It holds the list of
    # Backblaze accounts (and their keys); this app fetches that list
    # from the Pi on every operation and keeps no copy of it.
    pi_url: str = "http://192.168.1.31:8000"

    # Where joined videos and time-lapses go.
    output_directory: str = str(default_output_directory())

    # Clip names on the Pi use this timezone and carry the clip END time.
    clip_timezone: str = "Asia/Kolkata"
    segment_seconds: int = Field(default=180, ge=10)

    # Parallel downloads from B2.
    parallel_downloads: int = Field(default=4, ge=1, le=16)

    # Optional explicit ffmpeg location (Windows users often need this).
    ffmpeg_path: str = ""

    def has_pi(self) -> bool:
        return bool(self.pi_url.strip())

    def public_view(self) -> dict:
        """Settings as sent to the UI."""

        return self.model_dump()


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
