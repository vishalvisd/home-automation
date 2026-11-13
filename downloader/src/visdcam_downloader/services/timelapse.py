from collections.abc import Callable
from pathlib import Path
from threading import Event

from visdcam_downloader.services.ffmpeg_tools import (
    FfmpegCancelled,
    FfmpegFailed,
    FfmpegTools,
)


def timelapse_output_name(source: Path, speed: int) -> str:
    return f"{source.stem}_{speed}x.mp4"


def remux_arguments(source: Path, output: Path, tools: FfmpegTools) -> list[str]:
    """Copy streams into MP4 so browsers and phones can play the file."""

    arguments = ["-fflags", "+genpts", "-i", str(source), "-c", "copy"]

    if tools.video_codec(source) == "hevc":
        arguments += ["-tag:v", "hvc1"]

    arguments += ["-movflags", "+faststart", "-f", "mp4", "-y", str(output)]
    return arguments


def make_timelapse(
    source: Path,
    output: Path,
    tools: FfmpegTools,
    *,
    speed: int,
    fps: int,
    prefer_hevc: bool = False,
    on_progress: Callable[[float], None] | None = None,
    on_log: Callable[[str], None] | None = None,
    cancel_event: Event | None = None,
) -> dict:
    """
    speed == 1: remux only, audio kept.
    speed  > 1: video sped up, audio dropped, hardware encoder when
                available with software fallback.
    """

    if speed < 1 or speed > 100:
        raise ValueError("Speed must be between 1 and 100")

    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".part.mp4")
    duration = tools.duration_seconds(source)

    try:
        if speed == 1:
            tools.run(
                remux_arguments(source, temporary, tools),
                expected_duration=duration,
                on_progress=on_progress,
                on_log=on_log,
                cancel_event=cancel_event,
            )
            temporary.replace(output)
            return {"encoder": "copy"}

        expected = duration / speed if duration else None
        candidates = tools.video_encoder_candidates(prefer_hevc=prefer_hevc)

        if not candidates:
            raise FfmpegFailed("No usable video encoder found in ffmpeg")

        last_error: Exception | None = None

        for encoder in candidates:
            if on_log is not None:
                on_log(f"Trying encoder {encoder}")

            arguments = [
                "-fflags", "+genpts",
                "-i", str(source),
                "-vf", f"setpts=PTS/{speed},fps={fps}",
                "-an",
                "-c:v", encoder,
                "-pix_fmt", "yuv420p",
                *_quality_arguments(encoder),
                "-movflags", "+faststart",
                "-f", "mp4",
                "-y", str(temporary),
            ]

            try:
                tools.run(
                    arguments,
                    expected_duration=expected,
                    on_progress=on_progress,
                    on_log=on_log,
                    cancel_event=cancel_event,
                )
                temporary.replace(output)
                return {"encoder": encoder}

            except FfmpegCancelled:
                raise

            except FfmpegFailed as error:
                last_error = error
                temporary.unlink(missing_ok=True)
                if on_log is not None:
                    on_log(f"{encoder} failed: {error}")

        raise FfmpegFailed(f"All encoders failed. Last error: {last_error}")

    finally:
        temporary.unlink(missing_ok=True)


def _quality_arguments(encoder: str) -> list[str]:
    if encoder == "libx264":
        return ["-preset", "veryfast", "-crf", "20"]
    if encoder == "libx265":
        return ["-preset", "fast", "-crf", "24", "-tag:v", "hvc1"]
    # Hardware encoders are driven by bitrate.
    bitrate = "8M" if "hevc" in encoder else "10M"
    extra = ["-tag:v", "hvc1"] if "hevc" in encoder else []
    return ["-b:v", bitrate, *extra]
