import logging
from datetime import datetime
from pathlib import Path
from threading import RLock
from zoneinfo import ZoneInfo

from home_automation.config.mic_settings import (
    MAX_MODULES,
    MicModuleConfig,
    MicSettings,
)


LOGGER = logging.getLogger("home_automation")

LOCAL_TIME_ZONE = ZoneInfo("Asia/Kolkata")


class MicSettingsService:
    """
    Persistent runtime configuration for the room microphones,
    in runtime/mics.json.

    Unlike the other settings files, a damaged file here does not stop
    the backend: it is put aside and the defaults are used, because the
    cameras must never fail to start over a microphone file.
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
                self._write(MicSettings())

            self._settings = self._read_or_reset()

    def get(self) -> MicSettings:
        with self._lock:
            return self._settings.model_copy(deep=True)

    def save(self, settings: MicSettings) -> MicSettings:
        with self._lock:
            self._write(settings)
            self._settings = settings.model_copy(deep=True)

        return settings

    def register_module(
        self,
        module_id: str,
    ) -> tuple[MicModuleConfig | None, bool]:
        """
        The module's entry, added first if the Pi has never seen it.

        Returns the entry and whether it is new. The entry is None when
        the module is unknown and the list is full.
        """

        with self._lock:
            known = self._settings.module(module_id)

            if known is not None:
                return known.model_copy(), False

            if len(self._settings.modules) >= MAX_MODULES:
                return None, False

            module = MicModuleConfig(
                id=module_id,
                first_seen_at=datetime.now(LOCAL_TIME_ZONE).isoformat(
                    timespec="seconds"
                ),
            )

            updated = self._settings.model_copy(deep=True)
            updated.modules.append(module)

            self._write(updated)
            self._settings = updated

            return module.model_copy(), True

    def _read_or_reset(self) -> MicSettings:
        try:
            return MicSettings.model_validate_json(
                self._settings_file.read_text(encoding="utf-8")
            )
        except Exception as error:
            aside = self._settings_file.with_suffix(".damaged")

            LOGGER.error(
                "Microphone settings file is damaged (%s). It is kept "
                "as %s and the defaults are used.",
                error,
                aside.name,
            )

            try:
                self._settings_file.replace(aside)
            except OSError:
                pass

            settings = MicSettings()
            self._write(settings)

            return settings

    def _write(self, settings: MicSettings) -> None:
        temporary_file = self._settings_file.with_suffix(".tmp")

        temporary_file.write_text(
            settings.model_dump_json(indent=2) + "\n",
            encoding="utf-8",
        )

        temporary_file.replace(self._settings_file)
