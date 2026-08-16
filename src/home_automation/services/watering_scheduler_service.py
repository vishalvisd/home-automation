import json
import logging

from datetime import date, datetime, time, timedelta
from pathlib import Path
from threading import Event, Lock, Thread
from zoneinfo import ZoneInfo

from home_automation.config.watering_settings import WateringSettings
from home_automation.services.watering_service import (
    WateringAlreadyRunningError,
    WateringService,
)
from home_automation.services.watering_settings_service import (
    WateringSettingsService,
)


LOGGER = logging.getLogger(__name__)

SCHEDULER_CHECK_SECONDS = 10


class WateringSchedulerService:
    """Run watering automatically according to runtime configuration."""

    def __init__(
        self,
        settings_service: WateringSettingsService,
        watering_service: WateringService,
        state_file: Path,
    ) -> None:
        self._settings_service = settings_service
        self._watering_service = watering_service
        self._state_file = state_file

        self._state_lock = Lock()
        self._stop_event = Event()
        self._thread: Thread | None = None

        self._state_file.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        if not self._state_file.exists():
            self._write_state(
                {
                    "last_scheduled_run_date": None,
                }
            )

    def start(self) -> None:
        self._stop_event.clear()

        self._thread = Thread(
            target=self._run_loop,
            name="watering-scheduler",
            daemon=True,
        )
        self._thread.start()

        LOGGER.info("Watering scheduler started")

    def stop(self) -> None:
        self._stop_event.set()

        if self._thread is not None:
            self._thread.join(
                timeout=SCHEDULER_CHECK_SECONDS + 2
            )

        LOGGER.info("Watering scheduler stopped")

    def status(self) -> dict[str, object]:
        settings = self._settings_service.get()
        state = self._read_state()

        return {
            "enabled": settings.enabled,
            "run_time": settings.run_time,
            "frequency_days": settings.frequency_days,
            "timezone": settings.timezone,
            "last_scheduled_run_date": state.get(
                "last_scheduled_run_date"
            ),
            "next_scheduled_run": self._calculate_next_run(
                settings,
                state,
            ),
        }

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self._check_schedule()
            except Exception:
                LOGGER.exception(
                    "Unexpected watering scheduler error"
                )

            self._stop_event.wait(
                timeout=SCHEDULER_CHECK_SECONDS
            )

    def _check_schedule(self) -> None:
        settings = self._settings_service.get()

        if not settings.enabled:
            return

        timezone = ZoneInfo(settings.timezone)
        now = datetime.now(timezone)

        # Scheduler runs only during the configured HH:MM minute.
        if now.strftime("%H:%M") != settings.run_time:
            return

        state = self._read_state()

        last_run = self._parse_date(
            state.get("last_scheduled_run_date")
        )

        if last_run == now.date():
            return

        if last_run is not None:
            days_since_last_run = (
                now.date() - last_run
            ).days

            if days_since_last_run < settings.frequency_days:
                return

        if self._watering_service.status()["running"]:
            LOGGER.warning(
                "Scheduled watering skipped because "
                "watering is already running"
            )
            return

        try:
            self._watering_service.start()
        except WateringAlreadyRunningError:
            return

        self._write_state(
            {
                "last_scheduled_run_date": (
                    now.date().isoformat()
                ),
            }
        )

        LOGGER.info(
            "Scheduled watering started"
        )

    def _calculate_next_run(
        self,
        settings: WateringSettings,
        state: dict,
    ) -> str | None:
        if not settings.enabled:
            return None

        timezone = ZoneInfo(settings.timezone)
        now = datetime.now(timezone)

        scheduled_time = time.fromisoformat(
            settings.run_time
        )

        last_run = self._parse_date(
            state.get("last_scheduled_run_date")
        )

        if last_run is None:
            candidate_date = now.date()

            if now.time() >= scheduled_time:
                candidate_date += timedelta(days=1)

        else:
            minimum_date = (
                last_run
                + timedelta(days=settings.frequency_days)
            )

            candidate_date = max(
                now.date(),
                minimum_date,
            )

            if (
                candidate_date == now.date()
                and now.time() >= scheduled_time
            ):
                candidate_date += timedelta(days=1)

        next_run = datetime.combine(
            candidate_date,
            scheduled_time,
            tzinfo=timezone,
        )

        return next_run.isoformat()

    @staticmethod
    def _parse_date(value: object) -> date | None:
        if not value:
            return None

        return date.fromisoformat(str(value))

    def _read_state(self) -> dict:
        with self._state_lock:
            return json.loads(
                self._state_file.read_text(
                    encoding="utf-8"
                )
            )

    def _write_state(self, state: dict) -> None:
        with self._state_lock:
            temporary_file = (
                self._state_file.with_suffix(".tmp")
            )

            temporary_file.write_text(
                json.dumps(
                    state,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )

            temporary_file.replace(
                self._state_file
            )