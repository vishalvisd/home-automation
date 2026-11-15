import json
import logging
import subprocess
from pathlib import Path
from threading import RLock
from urllib.request import urlopen

from home_automation.config.camera_settings import CameraConfig
from home_automation.services.camera_settings_service import (
    CameraSettingsService,
)


LOGGER = logging.getLogger("home_automation")

GO2RTC_BINARY = Path("/usr/local/bin/go2rtc")
STATUS_TIMEOUT_SECONDS = 2
RESTART_TIMEOUT_SECONDS = 20


class LiveViewService:
    """
    Keep go2rtc in step with the camera list.

    Browsers cannot play RTSP. go2rtc (a separate systemd service on the
    Pi) takes each camera's RTSP stream and serves it to the browser over
    WebRTC or MSE without re-encoding. This service writes go2rtc's
    config file from runtime/cameras.json and restarts go2rtc whenever
    that file changes. Nothing here touches recording.
    """

    def __init__(
        self,
        settings_service: CameraSettingsService,
        config_file: Path,
        service_name: str,
        port: int,
    ) -> None:
        self._settings_service = settings_service
        self._config_file = config_file
        self._service_name = service_name
        self._port = port
        self._lock = RLock()
        self._last_error: str | None = None

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def sync(self) -> dict:
        """Rewrite the go2rtc config if needed and restart go2rtc."""

        with self._lock:
            text = self._render_config()

            self._config_file.parent.mkdir(parents=True, exist_ok=True)

            current = (
                self._config_file.read_text(encoding="utf-8")
                if self._config_file.exists()
                else None
            )

            if current == text:
                return self.status()

            temporary_file = self._config_file.with_suffix(".tmp")
            temporary_file.write_text(text, encoding="utf-8")
            temporary_file.replace(self._config_file)

            LOGGER.info("go2rtc config written: %s", self._config_file)

            self._restart()

        return self.status()

    def status(self) -> dict:
        settings = self._settings_service.get()
        loaded = self._loaded_streams()

        cameras = []

        for camera in settings.cameras:
            source = self._live_source(camera)

            cameras.append(
                {
                    "key": camera.key,
                    "name": camera.name,
                    "enabled": camera.enabled,
                    "source_type": camera.source_type,
                    # "sub" when a separate live stream URL is set,
                    # "main" when live view falls back to the recording
                    # stream, "none" for cameras go2rtc cannot serve.
                    "live_source": source,
                    "loaded": (
                        loaded is not None and camera.key in loaded
                    ),
                }
            )

        return {
            "port": self._port,
            "installed": GO2RTC_BINARY.exists(),
            "running": loaded is not None,
            "config_file": str(self._config_file),
            "last_error": self._last_error,
            "cameras": cameras,
        }

    # ------------------------------------------------------------------
    # Config file
    # ------------------------------------------------------------------

    def _render_config(self) -> str:
        settings = self._settings_service.get()

        lines = [
            "# Written by home-automation from runtime/cameras.json.",
            "# Do not edit by hand: it is rewritten whenever camera",
            "# settings are saved, and go2rtc is restarted.",
            "api:",
            f'  listen: ":{self._port}"',
            "rtsp:",
            # The RTSP server is not needed; the Pi records with ffmpeg.
            '  listen: ""',
            "streams:",
        ]

        for camera in settings.cameras:
            url = self._live_url(camera)

            if url is None:
                continue

            lines.append(f"  {camera.key}: {self._yaml_string(url)}")

        return "\n".join(lines) + "\n"

    @staticmethod
    def _live_source(camera: CameraConfig) -> str:
        if camera.source_type != "rtsp":
            return "none"

        if camera.live_stream_url.strip():
            return "sub"

        if camera.stream_url.strip():
            return "main"

        return "none"

    @classmethod
    def _live_url(cls, camera: CameraConfig) -> str | None:
        source = cls._live_source(camera)

        if source == "sub":
            url = camera.live_stream_url.strip()
        elif source == "main":
            url = camera.stream_url.strip()
        else:
            return None

        # Two-way audio is never used; some cameras misbehave when
        # go2rtc asks for it.
        if "#" not in url:
            url += "#backchannel=0"

        return url

    @staticmethod
    def _yaml_string(value: str) -> str:
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'

    # ------------------------------------------------------------------
    # go2rtc process
    # ------------------------------------------------------------------

    def _restart(self) -> None:
        """
        Restart the go2rtc systemd unit. scripts/install_go2rtc.sh adds
        a sudoers rule so the service user may run exactly this command
        without a password.
        """

        command = [
            "sudo",
            "-n",
            "systemctl",
            "restart",
            self._service_name,
        ]

        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=RESTART_TIMEOUT_SECONDS,
                check=False,
            )
        except Exception as error:
            self._last_error = f"Could not restart go2rtc: {error}"
            LOGGER.warning(self._last_error)
            return

        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip() or "no details"
            self._last_error = (
                f"go2rtc restart failed (is it installed? run "
                f"scripts/install_go2rtc.sh): {detail}"
            )
            LOGGER.warning(self._last_error)
            return

        self._last_error = None
        LOGGER.info("go2rtc restarted")

    def _loaded_streams(self) -> set[str] | None:
        """Names of streams go2rtc currently knows, or None if it is down."""

        try:
            with urlopen(
                f"http://127.0.0.1:{self._port}/api/streams",
                timeout=STATUS_TIMEOUT_SECONDS,
            ) as response:
                data = json.loads(response.read() or b"{}")
        except Exception:
            return None

        return set(data.keys()) if isinstance(data, dict) else set()
