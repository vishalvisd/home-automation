from pathlib import Path
from typing import Protocol


class CameraStorageProvider(Protocol):
    """Cloud storage provider for completed CCTV segments."""

    def upload(
        self,
        local_file: Path,
        remote_key: str,
    ) -> None:
        """Upload one completed segment."""
        ...