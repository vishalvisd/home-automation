import logging
import re
import shutil
import subprocess
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from threading import Lock, Thread
from zoneinfo import ZoneInfo


LOGGER = logging.getLogger("home_automation")

LOCAL_TIME_ZONE = ZoneInfo("Asia/Kolkata")

FFMPEG_BINARY = shutil.which("ffmpeg")
# Making a download must not take the processor from the recorders.
NICE_BINARY = shutil.which("nice")

# MP3 of a download. Higher than the stored 32 kbps, because turning one
# lossy format into another loses a little again.
MP3_BITRATE = "48k"

# "Level the volume": four times louder first, as the stored sound is
# very quiet, then quiet parts are lifted more than loud ones. These are
# the settings of the test file the owner preferred on 28 Nov 2026.
LEVEL_FILTER = "volume=12dB,dynaudnorm=f=250:g=15:m=20"

FORMATS = {
    # name: (file ending, media type)
    "mp3": (".mp3", "audio/mpeg"),
    "opus": (".opus", "audio/ogg"),
}

READ_BYTES = 64 * 1024

# One download at a time: it keeps one core busy while it runs.
_one_at_a_time = Lock()


class DownloadBusyError(Exception):
    """Another download is being made."""


class DownloadFailedError(Exception):
    """ffmpeg could not make the file."""


def download_name(label: str, start: float, ending: str) -> str:
    """Module name and start time in India time, safe as a file name."""

    safe = re.sub(r"[^A-Za-z0-9_-]+", "_", label).strip("_") or "mic"
    moment = datetime.fromtimestamp(start, LOCAL_TIME_ZONE)

    return f"{safe}_{moment:%Y%m%d_%H%M%S}{ending}"


def concat_list(files: list[tuple[Path, float, float]]) -> str:
    """The list of files ffmpeg joins, in order."""

    lines = ["ffconcat version 1.0"]

    for path, _began, _seconds in files:
        # "file:" in front, or ffmpeg looks for the path inside the
        # pipe this list is handed to it through.
        lines.append(f"file 'file:{path}'")

    return "\n".join(lines) + "\n"


def cut(
    files: list[tuple[Path, float, float]],
    start: float,
    end: float,
) -> tuple[float, float]:
    """
    Where to cut the joined files (path, the moment the sound begins,
    its length) so that only the time asked for is left: how many
    seconds to skip at the front, and how many to keep after that.

    The files are joined without the holes between them, so what is
    kept is the sound that really exists between start and end, which
    is less than end - start when a hole lies between.
    """

    skip = max(0.0, start - files[0][1])
    keep = 0.0

    for _path, began, seconds in files:
        keep += max(0.0, min(end, began + seconds) - max(start, began))

    return skip, keep


def build_command(
    file_format: str,
    level: bool,
    skip: float,
    keep: float,
) -> list[str]:
    command = []

    if NICE_BINARY is not None:
        command += [NICE_BINARY, "-n", "10"]

    command += [
        FFMPEG_BINARY or "ffmpeg",
        "-hide_banner",
        "-nostats",
        "-loglevel", "error",
        "-f", "concat",
        "-safe", "0",
        "-protocol_whitelist", "file,pipe",
        "-i", "pipe:0",
        # After the input, so the cut is made on the sound itself and
        # is exact. (Asking the joiner to enter a file part way starts
        # up to a second early.)
        "-ss", f"{skip:.3f}",
        "-t", f"{keep:.3f}",
    ]

    if file_format == "opus":
        # The stored sound itself, joined, not converted.
        command += ["-c", "copy", "-f", "opus"]
    else:
        if level:
            command += ["-af", LEVEL_FILTER]

        command += [
            "-ar", "16000",
            "-ac", "1",
            "-c:a", "libmp3lame",
            "-b:a", MP3_BITRATE,
            "-f", "mp3",
        ]

    return command + ["pipe:1"]


class _Download:
    """
    The file ffmpeg is making, piece by piece.

    It always ends ffmpeg and lets the next download in: when the last
    piece has been read, when close() is called, and also when the
    browser goes away half way and this object is simply dropped.
    """

    def __init__(
        self,
        process: subprocess.Popen[bytes],
        first: bytes,
        errors: list[str],
    ) -> None:
        self._process = process
        self._first: bytes | None = first
        self._errors = errors
        self._closed = False

    def __iter__(self) -> "_Download":
        return self

    def __next__(self) -> bytes:
        if self._closed:
            raise StopIteration

        if self._first is not None:
            piece, self._first = self._first, None
            return piece

        assert self._process.stdout is not None
        piece = self._process.stdout.read(READ_BYTES)

        if piece:
            return piece

        if self._process.wait() != 0:
            LOGGER.warning(
                "Microphone download ended early: %s",
                self._errors[-1] if self._errors else "no details",
            )

        self.close()
        raise StopIteration

    def close(self) -> None:
        if self._closed:
            return

        self._closed = True
        _end(self._process)

    def __del__(self) -> None:
        self.close()


def _end(process: subprocess.Popen[bytes]) -> None:
    """End ffmpeg and let the next download in."""

    try:
        if process.poll() is None:
            process.kill()

        process.wait()

        for pipe in (process.stdin, process.stdout):
            if pipe is not None:
                try:
                    pipe.close()
                except OSError:
                    pass
    finally:
        _one_at_a_time.release()


def make_download(
    files: list[tuple[Path, float, float]],
    start: float,
    end: float,
    file_format: str,
    level: bool,
) -> Iterator[bytes]:
    """
    Start ffmpeg and return the file it makes, piece by piece. Raises
    before the first piece if another download is running or ffmpeg
    fails at once, so the page can be told properly.
    """

    if FFMPEG_BINARY is None:
        raise DownloadFailedError("ffmpeg is not installed.")

    if not _one_at_a_time.acquire(blocking=False):
        raise DownloadBusyError(
            "Another download is being made. Try again when it is done."
        )

    try:
        skip, keep = cut(files, start, end)

        process = subprocess.Popen(
            build_command(file_format, level, skip, keep),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except OSError as error:
        _one_at_a_time.release()
        raise DownloadFailedError(f"ffmpeg did not start: {error}") from error

    errors: list[str] = []

    def collect_errors() -> None:
        assert process.stderr is not None

        for raw_line in process.stderr:
            errors.append(raw_line.decode("utf-8", errors="replace").strip())
            del errors[:-10]

    Thread(target=collect_errors, daemon=True).start()

    try:
        assert process.stdin is not None and process.stdout is not None
        process.stdin.write(concat_list(files).encode("utf-8"))
        process.stdin.close()

        first = process.stdout.read(READ_BYTES)
    except Exception as error:
        _end(process)
        raise DownloadFailedError(str(error)) from error

    if not first:
        process.wait()
        detail = errors[-1] if errors else "no sound came out"
        _end(process)
        raise DownloadFailedError(f"ffmpeg could not make the file: {detail}")

    return _Download(process, first, errors)
