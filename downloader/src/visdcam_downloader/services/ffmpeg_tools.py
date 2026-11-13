import json
import logging
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from threading import Event


LOGGER = logging.getLogger(__name__)


class FfmpegNotFoundError(RuntimeError):
    pass


class FfmpegCancelled(RuntimeError):
    pass


class FfmpegFailed(RuntimeError):
    pass


# Hardware encoders to try, in order, per platform. Software last.
HARDWARE_ENCODERS = {
    "darwin": ["h264_videotoolbox", "hevc_videotoolbox"],
    "win32": [
        "h264_nvenc", "hevc_nvenc",
        "h264_qsv", "hevc_qsv",
        "h264_amf", "hevc_amf",
    ],
    "linux": ["h264_vaapi", "h264_nvenc"],
}

SOFTWARE_ENCODERS = ["libx264", "libx265"]


def find_binary(name: str, configured_path: str = "") -> str | None:
    """Locate ffmpeg or ffprobe. configured_path may be a file or a folder."""

    if configured_path.strip():
        candidate = Path(configured_path.strip()).expanduser()

        if candidate.is_dir():
            for filename in (name, f"{name}.exe"):
                if (candidate / filename).is_file():
                    return str(candidate / filename)

        elif candidate.is_file():
            if candidate.stem.lower() == name:
                return str(candidate)
            sibling = candidate.with_name(
                name + ("".join(candidate.suffixes) or "")
            )
            if sibling.is_file():
                return str(sibling)

    found = shutil.which(name)
    if found:
        return found

    for folder in ("/opt/homebrew/bin", "/usr/local/bin"):
        if Path(folder, name).is_file():
            return str(Path(folder, name))

    return None


class FfmpegTools:
    def __init__(self, ffmpeg_path: str = "") -> None:
        self.ffmpeg = find_binary("ffmpeg", ffmpeg_path)
        self.ffprobe = find_binary("ffprobe", ffmpeg_path)
        self._encoders: set[str] | None = None

    def available(self) -> bool:
        return self.ffmpeg is not None and self.ffprobe is not None

    def require(self) -> None:
        if not self.available():
            raise FfmpegNotFoundError(
                "ffmpeg and ffprobe were not found. Install ffmpeg "
                "(Mac: brew install ffmpeg, Windows: winget install ffmpeg) "
                "or set its path in Settings."
            )

    def version(self) -> str | None:
        if self.ffmpeg is None:
            return None
        try:
            output = subprocess.run(
                [self.ffmpeg, "-version"],
                capture_output=True, text=True, timeout=10, check=False,
            ).stdout
        except Exception:
            return None
        first = output.splitlines()[0] if output else ""
        match = re.search(r"ffmpeg version (\S+)", first)
        return match.group(1) if match else first

    def encoders(self) -> set[str]:
        if self._encoders is not None:
            return self._encoders

        self.require()
        output = subprocess.run(
            [self.ffmpeg, "-hide_banner", "-encoders"],
            capture_output=True, text=True, timeout=20, check=False,
        ).stdout

        found = set()
        for line in output.splitlines():
            match = re.match(r"\s*V[\w.]*\s+(\S+)", line)
            if match:
                found.add(match.group(1))

        self._encoders = found
        return found

    def video_encoder_candidates(self, prefer_hevc: bool = False) -> list[str]:
        """Encoders to try in order: hardware first, software last."""

        available = self.encoders()
        hardware = HARDWARE_ENCODERS.get(sys.platform, [])

        ordered = [
            name for name in hardware
            if name in available
            and (("hevc" in name) == prefer_hevc)
        ]
        ordered += [
            name for name in hardware
            if name in available and name not in ordered
        ]

        software = ["libx265", "libx264"] if prefer_hevc else ["libx264", "libx265"]
        ordered += [name for name in software if name in available]

        return ordered

    def probe(self, path: Path) -> dict:
        self.require()
        result = subprocess.run(
            [
                self.ffprobe, "-v", "error",
                "-show_entries", "format=duration,size:stream=codec_type,codec_name,width,height,avg_frame_rate",
                "-of", "json", str(path),
            ],
            capture_output=True, text=True, timeout=60, check=False,
        )
        if result.returncode != 0:
            raise FfmpegFailed(result.stderr.strip() or "ffprobe failed")
        return json.loads(result.stdout or "{}")

    def duration_seconds(self, path: Path) -> float | None:
        try:
            info = self.probe(path)
            return float(info.get("format", {}).get("duration"))
        except Exception:
            return None

    def video_codec(self, path: Path) -> str | None:
        try:
            for stream in self.probe(path).get("streams", []):
                if stream.get("codec_type") == "video":
                    return stream.get("codec_name")
        except Exception:
            return None
        return None

    def run(
        self,
        arguments: list[str],
        *,
        expected_duration: float | None = None,
        on_progress: Callable[[float], None] | None = None,
        on_log: Callable[[str], None] | None = None,
        cancel_event: Event | None = None,
    ) -> None:
        """
        Run ffmpeg. Progress (0..1) is derived from ffmpeg's own progress
        output when the expected duration is known.
        """

        self.require()

        command = [
            self.ffmpeg, "-hide_banner", "-nostdin", "-nostats",
            "-loglevel", "warning",
            "-progress", "pipe:1",
            *arguments,
        ]

        creation_flags = 0
        if sys.platform == "win32":
            creation_flags = subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]

        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            creationflags=creation_flags,
        )

        stderr_lines: list[str] = []

        def read_stderr() -> None:
            assert process.stderr is not None
            for line in process.stderr:
                line = line.rstrip()
                if line:
                    stderr_lines.append(line)
                    del stderr_lines[:-30]
                    if on_log is not None:
                        on_log(line)

        from threading import Thread

        stderr_thread = Thread(target=read_stderr, daemon=True)
        stderr_thread.start()

        assert process.stdout is not None

        try:
            for line in process.stdout:
                if cancel_event is not None and cancel_event.is_set():
                    process.kill()
                    raise FfmpegCancelled()

                line = line.strip()

                if line.startswith("out_time_us=") and expected_duration:
                    try:
                        seconds = int(line.split("=", 1)[1]) / 1_000_000
                    except ValueError:
                        continue
                    if on_progress is not None:
                        on_progress(max(0.0, min(1.0, seconds / expected_duration)))

        finally:
            return_code = process.wait()
            stderr_thread.join(timeout=5)

        if cancel_event is not None and cancel_event.is_set():
            raise FfmpegCancelled()

        if return_code != 0:
            detail = "\n".join(stderr_lines[-5:]) or f"exit code {return_code}"
            raise FfmpegFailed(detail)

        if on_progress is not None:
            on_progress(1.0)


def concat_list_entry(path: Path) -> str:
    """One line of an ffmpeg concat list; single quotes must be escaped."""

    escaped = str(path).replace("'", "'\\''")
    return f"file '{escaped}'\n"


def open_in_file_manager(path: Path) -> None:
    target = path if path.is_dir() else path.parent

    if sys.platform == "win32":
        os.startfile(str(target))  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(target)])
    else:
        subprocess.Popen(["xdg-open", str(target)])
