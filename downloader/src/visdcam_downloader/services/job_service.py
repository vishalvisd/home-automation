import json
import logging
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from threading import Event, RLock, Thread


LOGGER = logging.getLogger(__name__)

MAX_LOG_LINES = 300
MAX_HISTORY = 200


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


@dataclass
class Job:
    id: str
    kind: str
    title: str
    params: dict
    status: str = "queued"          # queued | running | done | failed | cancelled
    progress: float = 0.0
    message: str = ""
    log: list[str] = field(default_factory=list)
    result: dict = field(default_factory=dict)
    error: str | None = None
    created_at: str = field(default_factory=_now)
    started_at: str | None = None
    finished_at: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


class JobContext:
    """What a running job can do: report progress, log, check for cancel."""

    def __init__(self, service: "JobService", job: Job, cancel_event: Event) -> None:
        self._service = service
        self._job = job
        self.cancel_event = cancel_event

    @property
    def job(self) -> Job:
        return self._job

    def log(self, line: str) -> None:
        self._service._append_log(self._job, line)

    def progress(self, value: float, message: str | None = None) -> None:
        self._service._set_progress(self._job, value, message)

    def cancelled(self) -> bool:
        return self.cancel_event.is_set()


class JobCancelled(RuntimeError):
    pass


JobHandler = Callable[[JobContext], dict]


class JobService:
    """One background worker runs jobs one at a time, in order."""

    def __init__(self, history_file: Path) -> None:
        self._history_file = history_file
        self._lock = RLock()
        self._jobs: dict[str, Job] = {}
        self._order: list[str] = []
        self._handlers: dict[str, JobHandler] = {}
        self._cancel_events: dict[str, Event] = {}
        self._wake = Event()
        self._shutdown = Event()

        self._load_history()

        self._thread = Thread(target=self._worker, name="jobs", daemon=True)
        self._thread.start()

    def register(self, kind: str, handler: JobHandler) -> None:
        self._handlers[kind] = handler

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def submit(self, kind: str, title: str, params: dict) -> Job:
        if kind not in self._handlers:
            raise ValueError(f"Unknown job kind: {kind}")

        job = Job(id=uuid.uuid4().hex[:12], kind=kind, title=title, params=params)

        with self._lock:
            self._jobs[job.id] = job
            self._order.append(job.id)
            self._cancel_events[job.id] = Event()
            self._trim_history()
            self._save_history()

        self._wake.set()
        return job

    def list(self) -> list[dict]:
        with self._lock:
            return [self._jobs[job_id].to_dict() for job_id in reversed(self._order)]

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def has_active(self, kind: str | None = None) -> bool:
        with self._lock:
            return any(
                job.status in ("queued", "running")
                and (kind is None or job.kind == kind)
                for job in self._jobs.values()
            )

    def cancel(self, job_id: str) -> Job | None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None

            if job.status == "queued":
                job.status = "cancelled"
                job.finished_at = _now()
                job.message = "Cancelled before it started"
                self._save_history()

            elif job.status == "running":
                self._cancel_events[job_id].set()
                job.message = "Cancelling..."

            return job

    def delete(self, job_id: str) -> bool:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.status == "running":
                return False
            self._jobs.pop(job_id)
            self._order.remove(job_id)
            self._cancel_events.pop(job_id, None)
            self._save_history()
            return True

    def shutdown(self) -> None:
        self._shutdown.set()
        self._wake.set()
        for event in self._cancel_events.values():
            event.set()
        self._thread.join(timeout=10)

    # ------------------------------------------------------------------
    # Worker
    # ------------------------------------------------------------------

    def _next_queued(self) -> Job | None:
        with self._lock:
            for job_id in self._order:
                job = self._jobs[job_id]
                if job.status == "queued":
                    return job
        return None

    def _worker(self) -> None:
        while not self._shutdown.is_set():
            job = self._next_queued()

            if job is None:
                self._wake.wait(timeout=2)
                self._wake.clear()
                continue

            self._run(job)

    def _run(self, job: Job) -> None:
        with self._lock:
            job.status = "running"
            job.started_at = _now()
            job.message = "Starting"
            cancel_event = self._cancel_events.setdefault(job.id, Event())
            self._save_history()

        context = JobContext(self, job, cancel_event)
        handler = self._handlers[job.kind]

        try:
            result = handler(context)

            with self._lock:
                if cancel_event.is_set():
                    job.status = "cancelled"
                    job.message = "Cancelled"
                else:
                    job.status = "done"
                    job.progress = 1.0
                    job.result = result or {}
                    job.message = "Done"

        except JobCancelled:
            with self._lock:
                job.status = "cancelled"
                job.message = "Cancelled"

        except Exception as error:
            LOGGER.exception("Job failed: %s", job.title)
            with self._lock:
                if cancel_event.is_set():
                    job.status = "cancelled"
                    job.message = "Cancelled"
                else:
                    job.status = "failed"
                    job.error = str(error)
                    job.message = f"Failed: {error}"
                    self._append_log(job, f"ERROR: {error}", save=False)

        finally:
            with self._lock:
                job.finished_at = _now()
                self._save_history()

    # ------------------------------------------------------------------
    # Updates from running jobs
    # ------------------------------------------------------------------

    def _append_log(self, job: Job, line: str, save: bool = True) -> None:
        with self._lock:
            job.log.append(f"{datetime.now():%H:%M:%S} {line}")
            del job.log[:-MAX_LOG_LINES]

    def _set_progress(self, job: Job, value: float, message: str | None) -> None:
        with self._lock:
            job.progress = max(0.0, min(1.0, float(value)))
            if message is not None:
                job.message = message

    # ------------------------------------------------------------------
    # History on disk (so finished jobs survive a restart)
    # ------------------------------------------------------------------

    def _trim_history(self) -> None:
        finished = [
            job_id for job_id in self._order
            if self._jobs[job_id].status in ("done", "failed", "cancelled")
        ]
        while len(self._order) > MAX_HISTORY and finished:
            oldest = finished.pop(0)
            self._order.remove(oldest)
            self._jobs.pop(oldest, None)
            self._cancel_events.pop(oldest, None)

    def _save_history(self) -> None:
        try:
            data = [self._jobs[job_id].to_dict() for job_id in self._order]
            temporary = self._history_file.with_suffix(".tmp")
            temporary.write_text(json.dumps(data, indent=1), encoding="utf-8")
            temporary.replace(self._history_file)
        except Exception:
            LOGGER.exception("Unable to save job history")

    def _load_history(self) -> None:
        if not self._history_file.exists():
            return

        try:
            data = json.loads(self._history_file.read_text(encoding="utf-8"))
        except Exception:
            LOGGER.exception("Unable to read job history; starting empty")
            return

        for item in data:
            try:
                job = Job(**item)
            except TypeError:
                continue

            # Anything that was running when the app closed did not finish.
            if job.status in ("queued", "running"):
                job.status = "failed"
                job.error = "The app was closed before this job finished"
                job.message = job.error
                job.finished_at = job.finished_at or _now()

            self._jobs[job.id] = job
            self._order.append(job.id)
            self._cancel_events[job.id] = Event()
