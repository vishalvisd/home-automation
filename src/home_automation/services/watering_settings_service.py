from pathlib import Path
from threading import RLock

from home_automation.config.watering_settings import WateringSettings


class WateringSettingsService:
    """
    Read and write the persistent watering configuration.

    The JSON file is the authoritative runtime configuration.
    Python defaults are used only when creating the file for the first time.
    """

    def __init__(self, settings_file: Path) -> None:
        self._settings_file = settings_file
        self._lock = RLock()

        self._settings_file.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        with self._lock:
            if not self._settings_file.exists():
                self._write(WateringSettings())

            # Validate the existing file immediately at application startup.
            self._read()

    def get(self) -> WateringSettings:
        """Read the latest settings directly from disk."""

        with self._lock:
            return self._read()

    def save(self, settings: WateringSettings) -> WateringSettings:
        """Atomically replace the persistent settings file."""

        with self._lock:
            self._write(settings)

        return settings

    def _read(self) -> WateringSettings:
        contents = self._settings_file.read_text(
            encoding="utf-8"
        )

        return WateringSettings.model_validate_json(contents)

    def _write(self, settings: WateringSettings) -> None:
        temporary_file = self._settings_file.with_suffix(".tmp")

        temporary_file.write_text(
            settings.model_dump_json(indent=2) + "\n",
            encoding="utf-8",
        )

        temporary_file.replace(self._settings_file)