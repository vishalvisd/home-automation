import json
import logging
from datetime import datetime
from pathlib import Path
from threading import Event, Lock, Thread

from visdcam_downloader.services.job_service import JobService
from visdcam_downloader.services.settings_service import SettingsService


LOGGER = logging.getLogger(__name__)

CHECK_SECONDS = 30


class ArchiveService:
    """Run the archive job once a day at the configured local time."""

    def __init__(
        self,
        settings_service: SettingsService,
        job_service: JobService,
        state_file: Path,
    ) -> None:
        self._settings_service = settings_service
        self._job_service = job_service
        self._state_file = state_file
        self._lock = Lock()
        self._stop = Event()
        self._thread: Thread | None = None

        if not self._state_file.exists():
            self._write_state({"last_run_date": None, "last_job_id": None})

    def start(self) -> None:
        self._thread = Thread(target=self._loop, name="archive-scheduler", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=CHECK_SECONDS + 2)

    def run_now(self) -> dict:
        if self._job_service.has_active("archive"):
            raise RuntimeError("An archive job is already queued or running")

        job = self._job_service.submit("archive", "Archive all clips", {})
        self._write_state({
            "last_run_date": datetime.now().date().isoformat(),
            "last_job_id": job.id,
        })
        return job.to_dict()

    def status(self) -> dict:
        settings = self._settings_service.get()
        state = self._read_state()
        return {
            "enabled": settings.archive_enabled,
            "archive_time": settings.archive_time,
            "archive_directory": settings.archive_directory,
            "archive_keep_days": settings.archive_keep_days,
            "last_run_date": state.get("last_run_date"),
            "last_job_id": state.get("last_job_id"),
            "running": self._job_service.has_active("archive"),
        }

    def _loop(self) -> None:
        while not self._stop.wait(timeout=CHECK_SECONDS):
            try:
                self._check()
            except Exception:
                LOGGER.exception("Archive scheduler error")

    def _check(self) -> None:
        settings = self._settings_service.get()
        if not settings.archive_enabled:
            return

        now = datetime.now()
        if now.strftime("%H:%M") != settings.archive_time:
            return

        state = self._read_state()
        if state.get("last_run_date") == now.date().isoformat():
            return

        if self._job_service.has_active("archive"):
            return

        LOGGER.info("Scheduled archive starting")
        self.run_now()

    def _read_state(self) -> dict:
        with self._lock:
            try:
                return json.loads(self._state_file.read_text(encoding="utf-8"))
            except Exception:
                return {"last_run_date": None, "last_job_id": None}

    def _write_state(self, state: dict) -> None:
        with self._lock:
            temporary = self._state_file.with_suffix(".tmp")
            temporary.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
            temporary.replace(self._state_file)
