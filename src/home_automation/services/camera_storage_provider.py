from datetime import datetime
from pathlib import Path
from typing import Protocol


class CameraStorageProvider(Protocol):
    """Cloud storage provider for completed CCTV segments."""

    def upload(
        self,
        local_file: Path,
        remote_key: str,
        recorded_at: datetime,
    ) -> str:
        """
        Upload one completed segment. recorded_at is the moment the
        clip closed; it decides which account the clip goes to.
        Returns a short label for where it went, used in the log.
        """
        ...
