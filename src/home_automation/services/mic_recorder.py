import logging
import os
import re
import shutil
import subprocess
from pathlib import Path
from threading import RLock, Thread

from home_automation.services.mic_protocol import SAMPLE_RATE


LOGGER = logging.getLogger("home_automation")

FFMPEG_BINARY = shutil.which("ffmpeg")

SEGMENT_EXTENSION = ".opus"

# File names are the time the file was started, in this zone, like the
# camera clips. India has no summer time, so a name is never ambiguous.
FILE_TIME_ZONE = "Asia/Kolkata"
FILE_NAME_FORMAT = "%Y%m%d_%H%M%S"

STOP_TIMEOUT_SECONDS = 5

# Printed by ffmpeg's segment muxer every time it starts a new file.
SEGMENT_OPENED_PATTERN = re.compile(
    r"Opening '(?P<path>[^']+)' for writing"
)


class MicRecorderError(Exception):
    """ffmpeg is not running, so the sound cannot be stored."""


class MicRecorder:
    """
    Store one module's sound with ffmpeg.

    The raw sound is written to ffmpeg, which turns it into Opus and
    cuts it into one file a minute, on the minute, in the module's
    folder on the RAM disk. One recorder lives as long as one unbroken
    run of sound: when the module disconnects the recorder is stopped,
    and a new one is started when sound arrives again. So the time
    between two files of the same run is never lost, and a hole in the
    sound is always a hole between files.

    A file is named by the second it starts in. A module that calls
    again within the same second in which its last file began writes
    over that file; what is lost is the under one second it held.

    A file that was being written when the backend died is still
    playable up to its last second, so leftovers are kept.
    """

    def __init__(
        self,
        module_id: str,
        directory: Path,
        bitrate_kbps: int,
        segment_seconds: int = 60,
    ) -> None:
        self._module_id = module_id
        self._directory = directory
        self._bitrate_kbps = bitrate_kbps
        self._segment_seconds = segment_seconds

        self._lock = RLock()
        self._process: subprocess.Popen[bytes] | None = None
        self._reader_thread: Thread | None = None
        self._current_file: Path | None = None
        self._recent_stderr: list[str] = []

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def start(self) -> None:
        if FFMPEG_BINARY is None:
            raise MicRecorderError(
                "ffmpeg not found. Install with: sudo apt-get install ffmpeg"
            )

        # RAM directories can vanish; recreate on every start.
        self._directory.mkdir(parents=True, exist_ok=True)

        try:
            process = subprocess.Popen(
                self._build_command(),
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                env={**os.environ, "TZ": FILE_TIME_ZONE},
            )
        except OSError as error:
            raise MicRecorderError(f"ffmpeg did not start: {error}") from error

        with self._lock:
            self._process = process
            self._current_file = None
            self._recent_stderr = []

            self._reader_thread = Thread(
                target=self._read_stderr,
                args=(process,),
                name=f"mic-recorder-{self._module_id}",
                daemon=True,
            )
            self._reader_thread.start()

    def write(self, pcm: bytes) -> None:
        """Hand raw sound to ffmpeg. Raises when ffmpeg has gone."""

        process = self._process

        if process is None or process.stdin is None:
            raise MicRecorderError("the recorder is not running")

        try:
            process.stdin.write(pcm)
            process.stdin.flush()
        except (OSError, ValueError) as error:
            raise MicRecorderError(self._exit_detail(error)) from error

    def stop(self) -> None:
        """Let ffmpeg finish the file it is writing, then end it."""

        with self._lock:
            process = self._process
            reader_thread = self._reader_thread
            self._process = None

        if process is None:
            return

        # Closing its input is how ffmpeg is told the sound is over; it
        # then writes the end of the file and exits by itself.
        try:
            if process.stdin is not None:
                process.stdin.close()
        except OSError:
            pass

        try:
            process.wait(timeout=STOP_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            LOGGER.warning(
                "Microphone recorder did not stop in time; killing it: %s",
                self._module_id,
            )
            process.kill()
            process.wait(timeout=5)

        if reader_thread is not None:
            reader_thread.join(timeout=STOP_TIMEOUT_SECONDS)

        with self._lock:
            self._current_file = None

    @property
    def running(self) -> bool:
        process = self._process

        return process is not None and process.poll() is None

    @property
    def current_file(self) -> Path | None:
        """The file being written now. It must not be deleted."""

        with self._lock:
            return self._current_file

    # ------------------------------------------------------------------
    # ffmpeg
    # ------------------------------------------------------------------

    def _build_command(self) -> list[str]:
        output_pattern = (
            self._directory / f"{FILE_NAME_FORMAT}{SEGMENT_EXTENSION}"
        )

        return [
            FFMPEG_BINARY,
            "-hide_banner",
            "-nostats",
            "-loglevel", "info",
            # Raw sound needs no looking into. Without these two ffmpeg
            # waits for about three seconds of sound before it starts,
            # and the first file's name is three seconds late.
            "-probesize", "32",
            "-analyzeduration", "0",
            "-f", "s16le",
            "-ar", str(SAMPLE_RATE),
            "-ac", "1",
            "-i", "pipe:0",
            "-c:a", "libopus",
            "-b:a", f"{self._bitrate_kbps}k",
            "-f", "segment",
            "-segment_time", str(self._segment_seconds),
            # Cut on the clock (every full minute), not counted from
            # when this recorder happened to start.
            "-segment_atclocktime", "1",
            "-segment_format", "opus",
            "-reset_timestamps", "1",
            "-strftime", "1",
            str(output_pattern),
        ]

    def _read_stderr(self, process: subprocess.Popen[bytes]) -> None:
        assert process.stderr is not None

        try:
            for raw_line in process.stderr:
                line = raw_line.decode("utf-8", errors="replace").rstrip()

                if not line:
                    continue

                match = SEGMENT_OPENED_PATTERN.search(line)

                with self._lock:
                    if match is not None:
                        self._current_file = Path(match.group("path"))
                    else:
                        self._recent_stderr.append(line)
                        del self._recent_stderr[:-20]
        except (OSError, ValueError):
            pass
        finally:
            process.wait()

    def _exit_detail(self, error: Exception) -> str:
        with self._lock:
            recent = list(self._recent_stderr)

        detail = recent[-1] if recent else str(error)

        return f"ffmpeg stopped: {detail}"
