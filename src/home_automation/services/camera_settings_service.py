from pathlib import Path
from threading import RLock

from home_automation.config.camera_settings import CameraSettings


class CameraSettingsService:
    """Persistent runtime configuration for CCTV."""

    def __init__(self, settings_file: Path) -> None:
        self._settings_file = settings_file
        self._lock = RLock()

        self._settings_file.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        with self._lock:
            if not self._settings_file.exists():
                self._write(CameraSettings())

            self._read()

    def get(self) -> CameraSettings:
        with self._lock:
            return self._read()

    def save(
        self,
        settings: CameraSettings,
    ) -> CameraSettings:
        with self._lock:
            self._write(settings)

        return settings

    def _read(self) -> CameraSettings:
        return CameraSettings.model_validate_json(
            self._settings_file.read_text(
                encoding="utf-8"
            )
        )

    def _write(
        self,
        settings: CameraSettings,
    ) -> None:
        temporary_file = (
            self._settings_file.with_suffix(".tmp")
        )

        temporary_file.write_text(
            settings.model_dump_json(indent=2) + "\n",
            encoding="utf-8",
        )

        temporary_file.replace(
            self._settings_file
        )