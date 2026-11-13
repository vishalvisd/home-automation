"""The actual work behind each job kind: download, timelapse, archive."""

import logging
import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from pathlib import Path
from threading import Lock
from zoneinfo import ZoneInfo

from visdcam_downloader.config import TEMP_DIRECTORY
from visdcam_downloader.services.b2_client import B2Client, DownloadCancelled
from visdcam_downloader.services.clips import Clip, output_name
from visdcam_downloader.services.ffmpeg_tools import FfmpegCancelled, FfmpegTools
from visdcam_downloader.services.job_service import JobCancelled, JobContext
from visdcam_downloader.services.joiner import join_clips
from visdcam_downloader.services.settings_service import SettingsService
from visdcam_downloader.services.timelapse import make_timelapse, timelapse_output_name


LOGGER = logging.getLogger(__name__)


def _human_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    return f"{value:.1f} GB"


class Workflows:
    def __init__(
        self,
        settings_service: SettingsService,
        b2_client: B2Client,
    ) -> None:
        self._settings_service = settings_service
        self._b2 = b2_client

    def tools(self) -> FfmpegTools:
        return FfmpegTools(self._settings_service.get().ffmpeg_path)

    # ------------------------------------------------------------------
    # Shared: download a list of clips in parallel into a folder
    # ------------------------------------------------------------------

    def _download_many(
        self,
        context: JobContext,
        clips: list[Clip],
        destination_for: "callable",
        *,
        skip_existing: bool = False,
        progress_span: tuple[float, float] = (0.0, 1.0),
    ) -> list[Path]:
        settings = self._settings_service.get()
        total_bytes = sum(clip.size for clip in clips) or 1
        done_bytes: dict[str, int] = {}
        done_count = 0
        lock = Lock()
        span_start, span_end = progress_span
        results: dict[str, Path] = {}

        def report() -> None:
            fraction = sum(done_bytes.values()) / total_bytes
            context.progress(
                span_start + (span_end - span_start) * fraction,
                f"Downloading {done_count}/{len(clips)} clips",
            )

        def fetch(clip: Clip) -> Path:
            nonlocal done_count
            destination = destination_for(clip)

            if skip_existing and destination.exists() and destination.stat().st_size == clip.size:
                with lock:
                    done_bytes[clip.key] = clip.size
                    done_count += 1
                    report()
                return destination

            def on_progress(completed: int, _total: int) -> None:
                with lock:
                    done_bytes[clip.key] = completed
                    report()

            self._b2.download(
                clip, destination,
                on_progress=on_progress,
                cancel_event=context.cancel_event,
            )

            with lock:
                done_bytes[clip.key] = clip.size
                done_count += 1
                report()
                context.log(f"Downloaded {clip.filename} ({_human_size(clip.size)})")

            return destination

        with ThreadPoolExecutor(max_workers=settings.parallel_downloads) as pool:
            futures = {pool.submit(fetch, clip): clip for clip in clips}

            try:
                for future in as_completed(futures):
                    clip = futures[future]
                    results[clip.key] = future.result()
            except DownloadCancelled:
                context.cancel_event.set()
                raise JobCancelled()

        return [results[clip.key] for clip in clips]

    # ------------------------------------------------------------------
    # Download + join one time window
    # ------------------------------------------------------------------

    def download_job(self, context: JobContext) -> dict:
        params = context.job.params
        settings = self._settings_service.get()
        timezone = ZoneInfo(settings.clip_timezone)

        camera = str(params["camera"])
        start = datetime.fromisoformat(params["start"])
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone)
        duration_seconds = int(params["duration_seconds"])
        end = start + timedelta(seconds=duration_seconds)

        context.progress(0.0, "Listing clips")
        clips = self._b2.list_clips(camera, start, end)

        if not clips:
            raise RuntimeError(
                f"No clips found for {camera} between "
                f"{start:%Y-%m-%d %H:%M} and {end:%H:%M}"
            )

        context.log(
            f"{len(clips)} clip(s), {_human_size(sum(c.size for c in clips))}, "
            f"{clips[0].start_time:%H:%M:%S} to {clips[-1].end_time:%H:%M:%S}"
        )

        work_dir = TEMP_DIRECTORY / context.job.id
        work_dir.mkdir(parents=True, exist_ok=True)

        try:
            files = self._download_many(
                context, clips,
                lambda clip: work_dir / clip.filename,
                progress_span=(0.0, 0.85),
            )

            if context.cancelled():
                raise JobCancelled()

            extension = clips[0].extension
            output = Path(settings.output_directory).expanduser() / output_name(
                camera, clips[0].start_time, duration_seconds, extension,
            )

            context.progress(0.85, "Joining clips")
            tools = self.tools()
            expected = len(clips) * settings.segment_seconds

            try:
                join_clips(
                    files, output, tools,
                    expected_duration=expected,
                    on_progress=lambda p: context.progress(0.85 + 0.15 * p),
                    on_log=context.log,
                    cancel_event=context.cancel_event,
                )
            except FfmpegCancelled:
                raise JobCancelled()

            duration = tools.duration_seconds(output) if tools.available() else None
            context.log(f"Saved {output}")

            return {
                "output_path": str(output),
                "clips": len(clips),
                "bytes": output.stat().st_size,
                "duration_seconds": duration,
            }

        finally:
            shutil.rmtree(work_dir, ignore_errors=True)

    # ------------------------------------------------------------------
    # Time-lapse of a local file
    # ------------------------------------------------------------------

    def timelapse_job(self, context: JobContext) -> dict:
        params = context.job.params
        source = Path(params["source_path"]).expanduser()
        speed = int(params.get("speed", 10))
        fps = int(params.get("fps", 30))
        prefer_hevc = bool(params.get("prefer_hevc", False))

        if not source.is_file():
            raise RuntimeError(f"File not found: {source}")

        output = source.with_name(timelapse_output_name(source, speed))
        tools = self.tools()
        tools.require()

        context.progress(0.0, f"Encoding {speed}x")

        try:
            info = make_timelapse(
                source, output, tools,
                speed=speed, fps=fps, prefer_hevc=prefer_hevc,
                on_progress=lambda p: context.progress(p),
                on_log=context.log,
                cancel_event=context.cancel_event,
            )
        except FfmpegCancelled:
            raise JobCancelled()

        context.log(f"Saved {output} using {info['encoder']}")

        return {
            "output_path": str(output),
            "encoder": info["encoder"],
            "bytes": output.stat().st_size,
        }

    # ------------------------------------------------------------------
    # Local archive: mirror everything in the bucket
    # ------------------------------------------------------------------

    def archive_job(self, context: JobContext) -> dict:
        settings = self._settings_service.get()
        archive_root = Path(settings.archive_directory).expanduser()
        archive_root.mkdir(parents=True, exist_ok=True)

        context.progress(0.0, "Listing bucket")
        cameras = self._b2.list_cameras()
        clips: list[Clip] = []

        for camera in cameras:
            for day in self._b2.list_days(camera):
                clips.extend(self._b2.list_clips_for_day(camera, day))

        context.log(f"{len(clips)} clip(s) in bucket across {len(cameras)} camera(s)")

        if clips:
            self._download_many(
                context, clips,
                lambda clip: archive_root / clip.key,
                skip_existing=True,
                progress_span=(0.0, 0.95),
            )

        pruned = self._prune_archive(archive_root, settings.archive_keep_days, context)

        return {
            "clips_in_bucket": len(clips),
            "bytes_in_bucket": sum(clip.size for clip in clips),
            "pruned_files": pruned,
            "archive_directory": str(archive_root),
        }

    def _prune_archive(self, root: Path, keep_days: int, context: JobContext) -> int:
        if keep_days <= 0:
            return 0

        cutoff = datetime.now() - timedelta(days=keep_days)
        removed = 0

        for day_dir in root.glob("cam*/*/*/*"):
            if not day_dir.is_dir():
                continue
            try:
                parts = day_dir.relative_to(root).parts  # camN, YYYY, MM, DD
                day = datetime(int(parts[1]), int(parts[2]), int(parts[3]))
            except (ValueError, IndexError):
                continue

            if day < cutoff.replace(hour=0, minute=0, second=0, microsecond=0):
                count = sum(1 for _ in day_dir.rglob("*") if _.is_file())
                shutil.rmtree(day_dir, ignore_errors=True)
                removed += count
                context.log(f"Pruned {day_dir.relative_to(root)} ({count} files)")

        # Remove empty month/year folders left behind.
        for folder in sorted(root.glob("cam*/*/*"), reverse=True):
            if folder.is_dir() and not any(folder.iterdir()):
                folder.rmdir()
        for folder in sorted(root.glob("cam*/*"), reverse=True):
            if folder.is_dir() and not any(folder.iterdir()):
                folder.rmdir()

        return removed
