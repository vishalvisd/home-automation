import json
import logging
import re
import shutil
import signal
import subprocess
from collections.abc import Callable
from pathlib import Path
from threading import Event, RLock, Thread
from time import monotonic
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from home_automation.config.camera_settings import (
    CameraConfig,
    CameraSettings,
)


LOGGER = logging.getLogger(__name__)

FFMPEG_BINARY = shutil.which("ffmpeg")
FFPROBE_BINARY = shutil.which("ffprobe")

# Commercial cameras usually send G.711 audio, which MP4 cannot hold.
# Audio is small, so converting it to AAC costs almost no CPU. The
# cloud copy uses a smaller mono setting; the archive keeps stereo.
AUDIO_BITRATE = "32k"
CLOUD_AUDIO_BITRATE = "24k"

# One recorder records one stream of a camera for one purpose.
#   cloud:   the clip is uploaded to Backblaze (sub stream when set)
#   archive: the clip is kept on the USB disk (always the main stream)
RecorderRole = str

# If the camera stops sending for this long, ffmpeg exits. The recorder
# service then restarts it after the configured delay.
SOCKET_TIMEOUT_SECONDS = 15

PROBE_TIMEOUT_SECONDS = 20
STOP_TIMEOUT_SECONDS = 10
WATCHDOG_CHECK_SECONDS = 5

# Printed by ffmpeg's segment muxer every time it starts a new file.
SEGMENT_OPENED_PATTERN = re.compile(
    r"Opening '(?P<path>[^']+)' for writing"
)

SEGMENT_EXTENSION = ".mp4"


class RtspFfmpegRecorder:
    """
    Record one RTSP camera with ffmpeg.

    Video is copied as-is (no re-encoding). Audio is converted to AAC
    unless it already is AAC. ffmpeg cuts the recording into MP4 files
    of segment_seconds each. When a file is finished it is handed to
    on_fragment_closed, exactly like the ESP32 recorder does.
    """

    def __init__(
        self,
        camera: CameraConfig,
        settings: CameraSettings,
        on_fragment_closed: Callable[
            [CameraConfig, Path],
            None,
        ]
        | None = None,
        *,
        role: RecorderRole = "cloud",
    ) -> None:
        self._camera = camera
        self._settings = settings
        self._on_fragment_closed = on_fragment_closed
        self._role = role

        self._lock = RLock()
        self._stop_event = Event()

        self._process: subprocess.Popen[str] | None = None
        self._reader_thread: Thread | None = None
        self._watchdog_thread: Thread | None = None

        self._running = False
        self._connected = False
        self._last_error: str | None = None
        self._current_fragment: str | None = None
        self._last_completed_fragment: str | None = None
        self._last_segment_opened_at = 0.0
        self._recent_stderr: list[str] = []

        self._video_codec: str | None = None
        self._audio_codec: str | None = None

        if role == "cloud" and camera.sub_stream_url.strip():
            self._stream_url = camera.sub_stream_url.strip()
        else:
            self._stream_url = camera.stream_url.strip()

        self._display_url = self._redact_url(self._stream_url)

        base_directory = (
            Path(settings.archive_buffer_directory)
            if role == "archive"
            else Path(settings.recording_directory)
        )
        self._camera_directory = base_directory / camera.key

    @property
    def role(self) -> RecorderRole:
        return self._role

    @property
    def label(self) -> str:
        return f"{self._camera.name} ({self._role})"

    # ------------------------------------------------------------------
    # Public interface (same shape as CameraRecorder)
    # ------------------------------------------------------------------

    def start(self) -> None:
        if FFMPEG_BINARY is None or FFPROBE_BINARY is None:
            raise RuntimeError(
                "ffmpeg/ffprobe not found. Install with: "
                "sudo apt-get install ffmpeg"
            )

        with self._lock:
            if self._running:
                return

            camera_directory = self._camera_directory

            camera_directory.mkdir(
                parents=True,
                exist_ok=True,
            )

            self._discard_leftover_files(camera_directory)

            try:
                video_codec, audio_codec = self._probe()

                self._video_codec = video_codec
                self._audio_codec = audio_codec

                command = self._build_command(
                    camera_directory,
                    video_codec,
                    audio_codec,
                )

                self._stop_event.clear()
                self._last_error = None
                self._connected = False
                self._current_fragment = None
                self._recent_stderr = []
                self._last_segment_opened_at = monotonic()

                self._process = subprocess.Popen(
                    command,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    text=True,
                    bufsize=1,
                )

                self._running = True

                self._reader_thread = Thread(
                    target=self._read_stderr,
                    name=f"rtsp-recorder-{self._camera.key}",
                    daemon=True,
                )
                self._reader_thread.start()

                self._watchdog_thread = Thread(
                    target=self._watchdog,
                    name=f"rtsp-watchdog-{self._camera.key}",
                    daemon=True,
                )
                self._watchdog_thread.start()

                LOGGER.info(
                    "Camera recorder started: %s (%s, video=%s, audio=%s)",
                    self.label,
                    self._display_url,
                    video_codec,
                    audio_codec or "none",
                )

            except Exception as error:
                self._last_error = str(error)
                self._running = False
                self._process = None
                raise

    def stop(self) -> None:
        with self._lock:
            self._stop_event.set()
            process = self._process
            reader_thread = self._reader_thread

        if process is not None and process.poll() is None:
            # SIGINT lets ffmpeg finish the current file cleanly.
            try:
                process.send_signal(signal.SIGINT)
                process.wait(timeout=STOP_TIMEOUT_SECONDS)
            except subprocess.TimeoutExpired:
                LOGGER.warning(
                    "ffmpeg did not stop in time; killing it: %s",
                    self.label,
                )
                process.kill()
                process.wait(timeout=5)
            except Exception:
                LOGGER.exception(
                    "Error while stopping ffmpeg: %s",
                    self._camera.name,
                )

        if reader_thread is not None:
            reader_thread.join(timeout=STOP_TIMEOUT_SECONDS + 5)

    def status(self) -> dict[str, object]:
        with self._lock:
            return {
                "key": self._camera.key,
                "name": self._camera.name,
                "role": self._role,
                "host": self._display_url,
                "source_type": self._camera.source_type,
                "running": self._running,
                "last_error": self._last_error,
                "current_fragment": self._current_fragment,
                "last_completed_fragment": (
                    self._last_completed_fragment
                ),
                "stream_connected": self._connected,
                "stream_reconnect_count": 0,
                "last_stream_error": None,
                "video_codec": self._video_codec,
                "audio_codec": self._audio_codec,
            }

    # ------------------------------------------------------------------
    # ffmpeg command
    # ------------------------------------------------------------------

    def _probe(self) -> tuple[str, str | None]:
        """Ask ffprobe which codecs the camera sends."""

        command = [
            FFPROBE_BINARY,
            "-v", "error",
            "-rtsp_transport", "tcp",
            "-show_entries", "stream=codec_type,codec_name",
            "-of", "json",
            self._stream_url,
        ]

        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=PROBE_TIMEOUT_SECONDS,
                check=False,
            )
        except subprocess.TimeoutExpired as error:
            raise RuntimeError(
                "Camera did not answer the codec probe within "
                f"{PROBE_TIMEOUT_SECONDS} seconds"
            ) from error

        if result.returncode != 0:
            detail = self._redact(result.stderr.strip()) or "no details"
            raise RuntimeError(f"Cannot open camera stream: {detail}")

        streams = json.loads(result.stdout or "{}").get("streams", [])

        video_codec = None
        audio_codec = None

        for stream in streams:
            if stream.get("codec_type") == "video" and video_codec is None:
                video_codec = stream.get("codec_name")
            if stream.get("codec_type") == "audio" and audio_codec is None:
                audio_codec = stream.get("codec_name")

        if video_codec is None:
            raise RuntimeError("Camera stream has no video")

        return video_codec, audio_codec

    def _build_command(
        self,
        camera_directory: Path,
        video_codec: str,
        audio_codec: str | None,
    ) -> list[str]:
        command = [
            FFMPEG_BINARY,
            "-nostdin",
            "-hide_banner",
            "-nostats",
            "-loglevel", "info",
            "-rtsp_transport", "tcp",
            "-timeout", str(SOCKET_TIMEOUT_SECONDS * 1_000_000),
            "-i", self._stream_url,
            "-c:v", "copy",
        ]

        # Apple players need the hvc1 tag to play H.265 in MP4.
        if video_codec == "hevc":
            command += ["-tag:v", "hvc1"]

        if audio_codec is None:
            command += ["-an"]
        elif self._role == "cloud":
            # Small mono track for the evidence copy.
            command += ["-c:a", "aac", "-ac", "1", "-b:a", CLOUD_AUDIO_BITRATE]
        elif audio_codec == "aac":
            command += ["-c:a", "copy"]
        else:
            command += ["-c:a", "aac", "-b:a", AUDIO_BITRATE]

        output_pattern = (
            camera_directory / f"%Y%m%d_%H%M%S{SEGMENT_EXTENSION}"
        )

        command += [
            "-f", "segment",
            "-segment_time", str(self._settings.segment_seconds),
            "-reset_timestamps", "1",
            "-segment_format", "mp4",
            "-segment_format_options", "movflags=+faststart",
            "-strftime", "1",
            str(output_pattern),
        ]

        return command

    # ------------------------------------------------------------------
    # Process monitoring
    # ------------------------------------------------------------------

    def _read_stderr(self) -> None:
        process = self._process
        assert process is not None and process.stderr is not None

        try:
            for raw_line in process.stderr:
                line = raw_line.rstrip()

                if not line:
                    continue

                match = SEGMENT_OPENED_PATTERN.search(line)

                if match is not None:
                    self._handle_segment_opened(Path(match.group("path")))
                    continue

                line = self._redact(line)

                with self._lock:
                    self._recent_stderr.append(line)
                    del self._recent_stderr[:-20]

                LOGGER.debug("ffmpeg [%s]: %s", self._camera.name, line)

        finally:
            return_code = process.wait()
            self._handle_process_exit(return_code)

    def _handle_segment_opened(self, path: Path) -> None:
        with self._lock:
            previous = self._current_fragment
            self._current_fragment = str(path)
            self._last_segment_opened_at = monotonic()

            if not self._connected:
                self._connected = True
                LOGGER.info(
                    "Camera stream connected: %s",
                    self.label,
                )

        if previous is not None:
            self._finish_fragment(Path(previous))

    def _handle_process_exit(self, return_code: int) -> None:
        with self._lock:
            stop_requested = self._stop_event.is_set()
            current = self._current_fragment
            self._current_fragment = None
            self._running = False
            self._connected = False
            self._process = None
            recent = list(self._recent_stderr)

        # ffmpeg finished the last file before exiting.
        if current is not None:
            self._finish_fragment(Path(current))

        if stop_requested:
            LOGGER.info(
                "Camera recorder stopped: %s",
                self.label,
            )
            return

        detail = recent[-1] if recent else "no output from ffmpeg"

        with self._lock:
            self._last_error = (
                f"ffmpeg exited with code {return_code}: {detail}"
            )

        LOGGER.error(
            "Camera recorder error [%s]: %s",
            self.label,
            self._last_error,
        )

    def _watchdog(self) -> None:
        """Kill ffmpeg if no new segment starts for far too long."""

        limit = (
            self._settings.segment_seconds
            + SOCKET_TIMEOUT_SECONDS
            + 30
        )

        while not self._stop_event.wait(timeout=WATCHDOG_CHECK_SECONDS):
            with self._lock:
                process = self._process
                running = self._running
                idle = monotonic() - self._last_segment_opened_at

            if not running or process is None:
                return

            if idle > limit and process.poll() is None:
                LOGGER.warning(
                    "No new segment for %.0f seconds; killing ffmpeg: %s",
                    idle,
                    self.label,
                )
                process.kill()
                return

    # ------------------------------------------------------------------
    # Segment files
    # ------------------------------------------------------------------

    def _finish_fragment(self, file_path: Path) -> None:
        if not file_path.exists() or file_path.stat().st_size == 0:
            file_path.unlink(missing_ok=True)

            LOGGER.info(
                "Empty camera segment discarded [%s]: %s",
                self.label,
                file_path,
            )
            return

        # A clip cut short by a kill or a double signal has no index and
        # cannot be played or joined. Better to lose it here, loudly,
        # than to upload or archive garbage.
        if not self._playable(file_path):
            file_path.unlink(missing_ok=True)

            LOGGER.error(
                "Unplayable camera segment discarded [%s]: %s",
                self.label,
                file_path,
            )
            return

        with self._lock:
            self._last_completed_fragment = str(file_path)

        LOGGER.info(
            "Camera segment created [%s]: %s",
            self.label,
            file_path,
        )

        if self._on_fragment_closed is not None:
            try:
                self._on_fragment_closed(self._camera, file_path)
            except Exception:
                LOGGER.exception(
                    "Camera segment callback failed [%s]: %s",
                    self.label,
                    file_path,
                )

    @staticmethod
    def _playable(file_path: Path) -> bool:
        """True when ffprobe can read the file's header and duration."""

        try:
            result = subprocess.run(
                [
                    FFPROBE_BINARY, "-v", "error",
                    "-show_entries", "format=duration",
                    "-of", "csv=p=0", str(file_path),
                ],
                capture_output=True,
                text=True,
                timeout=PROBE_TIMEOUT_SECONDS,
                check=False,
            )
        except Exception:
            return False

        return result.returncode == 0 and result.stdout.strip() not in ("", "N/A")

    def _discard_leftover_files(self, camera_directory: Path) -> None:
        """
        Files left from a previous run are unfinished MP4s with no
        index, so they will not play. Nothing is kept.
        """

        leftovers = list(camera_directory.glob(f"*{SEGMENT_EXTENSION}"))

        for leftover in leftovers:
            leftover.unlink(missing_ok=True)

        if leftovers:
            LOGGER.warning(
                "Discarded %s leftover segment(s) [%s]",
                len(leftovers),
                self.label,
            )

    # ------------------------------------------------------------------
    # Never let a camera password reach the logs or the UI
    # ------------------------------------------------------------------

    @staticmethod
    def _redact_url(url: str) -> str:
        try:
            parts = urlsplit(url)
        except ValueError:
            return "rtsp://<invalid url>"

        if parts.password is None and parts.username is None:
            return url

        host = parts.hostname or ""
        if parts.port is not None:
            host = f"{host}:{parts.port}"

        user = parts.username or ""
        netloc = f"{user}:***@{host}" if user else f"***@{host}"

        return urlunsplit(
            (parts.scheme, netloc, parts.path, parts.query, parts.fragment)
        )

    def _redact(self, text: str) -> str:
        if self._stream_url and self._stream_url in text:
            return text.replace(self._stream_url, self._display_url)
        return text
