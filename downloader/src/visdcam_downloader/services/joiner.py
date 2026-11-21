import shutil
from collections.abc import Callable
from pathlib import Path
from threading import Event

from visdcam_downloader.services.ffmpeg_tools import (
    FfmpegCancelled,
    FfmpegTools,
    concat_list_entry,
)


class MixedClipTypesError(ValueError):
    pass


def join_clips(
    clip_files: list[Path],
    output: Path,
    tools: FfmpegTools,
    *,
    expected_duration: float | None = None,
    on_progress: Callable[[float], None] | None = None,
    on_log: Callable[[str], None] | None = None,
    cancel_event: Event | None = None,
) -> Path:
    """
    Join downloaded clips into one file.

    .ts clips (ESP32-CAM) are MPEG-TS and can simply be concatenated.
    .mp4 clips (RTSP cameras) each carry their own index, so they are
    joined with ffmpeg's concat demuxer, copying the streams untouched.
    """

    if not clip_files:
        raise ValueError("No clips to join")

    # A clip cut short on the Pi (no index) would make ffmpeg refuse the
    # whole join. Leave it out and say so, rather than fail everything.
    readable: list[Path] = []
    for path in clip_files:
        if path.suffix.lower() == ".mp4" and tools.available() and tools.duration_seconds(path) is None:
            if on_log is not None:
                on_log(f"Skipping {path.name}: file is damaged (no index)")
            continue
        readable.append(path)

    if not readable:
        raise ValueError("Every clip in the window is damaged")

    clip_files = readable

    extensions = {path.suffix.lower() for path in clip_files}

    if len(extensions) != 1:
        raise MixedClipTypesError(
            "The window contains both .ts and .mp4 clips. Pick a window on "
            "one side of the camera change."
        )

    extension = extensions.pop()
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".part")

    try:
        if extension == ".ts":
            _concatenate_bytes(clip_files, temporary, on_progress, cancel_event)
        else:
            _concatenate_with_ffmpeg(
                clip_files, temporary, tools,
                expected_duration, on_progress, on_log, cancel_event,
            )
        temporary.replace(output)

    except BaseException:
        temporary.unlink(missing_ok=True)
        raise

    return output


def _concatenate_bytes(
    clip_files: list[Path],
    output: Path,
    on_progress: Callable[[float], None] | None,
    cancel_event: Event | None,
) -> None:
    total = sum(path.stat().st_size for path in clip_files) or 1
    done = 0

    with output.open("wb") as target:
        for path in clip_files:
            with path.open("rb") as source:
                while True:
                    if cancel_event is not None and cancel_event.is_set():
                        raise FfmpegCancelled()
                    chunk = source.read(1024 * 1024)
                    if not chunk:
                        break
                    target.write(chunk)
                    done += len(chunk)
                    if on_progress is not None:
                        on_progress(done / total)


def _concatenate_with_ffmpeg(
    clip_files: list[Path],
    output: Path,
    tools: FfmpegTools,
    expected_duration: float | None,
    on_progress: Callable[[float], None] | None,
    on_log: Callable[[str], None] | None,
    cancel_event: Event | None,
) -> None:
    list_file = output.with_name(output.name + ".txt")
    list_file.write_text(
        "".join(concat_list_entry(path) for path in clip_files),
        encoding="utf-8",
    )

    try:
        tools.run(
            [
                "-f", "concat", "-safe", "0",
                "-i", str(list_file),
                "-c", "copy",
                "-movflags", "+faststart",
                "-f", "mp4",
                "-y", str(output),
            ],
            expected_duration=expected_duration,
            on_progress=on_progress,
            on_log=on_log,
            cancel_event=cancel_event,
        )
    finally:
        list_file.unlink(missing_ok=True)


def copy_single(source: Path, output: Path) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, output)
    return output
