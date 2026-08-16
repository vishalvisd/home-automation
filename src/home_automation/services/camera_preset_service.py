import json
import logging
from datetime import datetime, time
from pathlib import Path
from threading import Event, Lock, Thread
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from home_automation.config.camera_settings import CameraConfig
from home_automation.services.camera_settings_service import (
    CameraSettingsService,
)


LOGGER = logging.getLogger("home_automation")

CAMERA_PRESET_CHECK_SECONDS = 30 * 60
CAMERA_API_TIMEOUT_SECONDS = 5
CAMERA_TIME_ZONE = ZoneInfo("Asia/Kolkata")


class CameraPresetService:
    """Apply camera day/night presets according to wall-clock time."""

    def __init__(
        self,
        settings_service: CameraSettingsService,
        state_file: Path,
    ) -> None:
        self._settings_service = settings_service
        self._state_file = state_file

        self._state_lock = Lock()
        self._stop_event = Event()
        self._thread: Thread | None = None

        self._state_file.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        if not self._state_file.exists():
            self._write_state({"cameras": {}})

    def start(self) -> None:
        self._stop_event.clear()

        self._thread = Thread(
            target=self._run_loop,
            name="camera-preset",
            daemon=True,
        )
        self._thread.start()

        LOGGER.info("Camera preset service started")

    def stop(self) -> None:
        self._stop_event.set()

        if self._thread is not None:
            self._thread.join(
                timeout=CAMERA_API_TIMEOUT_SECONDS + 2
            )

        LOGGER.info("Camera preset service stopped")

    def status(self) -> dict[str, object]:
        settings = self._settings_service.get()
        state = self._read_state()
        camera_state = state.get("cameras", {})
        now = datetime.now(CAMERA_TIME_ZONE)

        return {
            "timezone": str(CAMERA_TIME_ZONE),
            "check_interval_seconds": CAMERA_PRESET_CHECK_SECONDS,
            "day_mode_time": settings.day_mode_time,
            "night_mode_time": settings.night_mode_time,
            "desired_preset": self._desired_preset(
                now,
                settings.day_mode_time,
                settings.night_mode_time,
            ),
            "cameras": [
                {
                    "key": camera.key,
                    "name": camera.name,
                    "host": camera.host,
                    "enabled": camera.enabled,
                    "preset": camera_state.get(
                        camera.key,
                        {},
                    ).get("preset"),
                    "applied_at": camera_state.get(
                        camera.key,
                        {},
                    ).get("applied_at"),
                }
                for camera in settings.cameras
            ],
        }

    def _run_loop(self) -> None:
        # Give cameras and recording streams time to settle after backend
        # startup before making control API requests.
        if self._stop_event.wait(timeout=30):
            return

        while not self._stop_event.is_set():
            try:
                self._check_presets()
            except Exception:
                LOGGER.exception(
                    "Unexpected camera preset service error"
                )

            self._stop_event.wait(
                timeout=CAMERA_PRESET_CHECK_SECONDS
            )

    def _check_presets(self) -> None:
        settings = self._settings_service.get()
        now = datetime.now(CAMERA_TIME_ZONE)
        desired_preset = self._desired_preset(
            now,
            settings.day_mode_time,
            settings.night_mode_time,
        )

        state = self._read_state()
        camera_state = state.get("cameras", {})

        for camera in settings.cameras:
            if self._stop_event.is_set():
                return

            if not camera.enabled:
                continue

            current_preset = camera_state.get(
                camera.key,
                {},
            ).get("preset")

            if current_preset == desired_preset:
                continue

            if not self._apply_preset(
                camera,
                desired_preset,
            ):
                continue

            camera_state[camera.key] = {
                "preset": desired_preset,
                "applied_at": now.isoformat(),
            }

            state["cameras"] = camera_state
            self._write_state(state)

            LOGGER.info(
                "Camera preset applied [%s]: %s",
                camera.name,
                desired_preset,
            )

    def _apply_preset(
        self,
        camera: CameraConfig,
        preset: str,
    ) -> bool:
        url = (
            f"http://{camera.host}:"
            f"{camera.control_port}/{preset}"
        )

        try:
            request = Request(
                url,
                method="GET",
            )

            with urlopen(
                request,
                timeout=CAMERA_API_TIMEOUT_SECONDS,
            ) as response:
                return 200 <= response.status < 300

        except Exception as error:
            LOGGER.warning(
                "Camera preset request failed [%s]: %s",
                camera.name,
                error,
            )
            return False

    @staticmethod
    def _desired_preset(
        now: datetime,
        day_mode_time: str,
        night_mode_time: str,
    ) -> str:
        current_time = now.time().replace(
            second=0,
            microsecond=0,
        )
        day_time = time.fromisoformat(day_mode_time)
        night_time = time.fromisoformat(night_mode_time)

        if day_time < night_time:
            if day_time <= current_time < night_time:
                return "day"
            return "night"

        if current_time >= day_time or current_time < night_time:
            return "day"

        return "night"

    def _read_state(self) -> dict:
        with self._state_lock:
            return json.loads(
                self._state_file.read_text(
                    encoding="utf-8"
                )
            )

    def _write_state(self, state: dict) -> None:
        with self._state_lock:
            temporary_file = (
                self._state_file.with_suffix(".tmp")
            )

            temporary_file.write_text(
                json.dumps(
                    state,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )

            temporary_file.replace(
                self._state_file
            )