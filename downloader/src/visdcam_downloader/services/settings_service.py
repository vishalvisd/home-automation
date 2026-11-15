import json
import os
from pathlib import Path
from threading import RLock

from visdcam_downloader.config import Settings


class SettingsService:
    """Read and write the local settings file atomically."""

    def __init__(self, settings_file: Path) -> None:
        self._settings_file = settings_file
        self._lock = RLock()

        self._settings_file.parent.mkdir(parents=True, exist_ok=True)

        with self._lock:
            if not self._settings_file.exists():
                self._write(Settings())

            self._read()

    def get(self) -> Settings:
        with self._lock:
            return self._read()

    def save(self, settings: Settings) -> Settings:
        with self._lock:
            self._write(settings)

        return settings

    def update(self, changes: dict) -> Settings:
        """Apply a partial update; unknown keys are ignored."""

        with self._lock:
            current = self._read()
            data = current.model_dump()

            for key, value in changes.items():
                if key in data:
                    data[key] = value

            settings = Settings.model_validate(data)
            self._write(settings)

        return settings

    def _read(self) -> Settings:
        return Settings.model_validate_json(
            self._settings_file.read_text(encoding="utf-8")
        )

    def _write(self, settings: Settings) -> None:
        temporary_file = self._settings_file.with_suffix(".tmp")

        temporary_file.write_text(
            settings.model_dump_json(indent=2) + "\n",
            encoding="utf-8",
        )

        temporary_file.replace(self._settings_file)

        if os.name == "posix":
            try:
                self._settings_file.chmod(0o600)
            except OSError:
                pass
