import json
import logging
from datetime import date, datetime, timedelta
from pathlib import Path
from threading import RLock
from zoneinfo import ZoneInfo

from home_automation.config.backblaze_credentials import BackblazeAccount
from home_automation.services.backblaze_credentials_service import (
    BackblazeCredentialsService,
)


LOGGER = logging.getLogger("home_automation")

LOCAL_TIME_ZONE = ZoneInfo("Asia/Kolkata")

# Dates older than this are dropped from the state file.
KEEP_DAYS = 14


class CloudRotationService:
    """
    Pick which Backblaze account a clip goes to.

    Every calendar day (Asia/Kolkata, the same date as in the clip's
    object path) uses one account. A new day takes the next enabled
    account in the list after the account used on the latest known
    day, wrapping round at the end. The choice is written to
    runtime/cloud_rotation_state.json so it never changes afterwards,
    which keeps consecutive days on different accounts no matter how
    the list is edited.
    """

    def __init__(
        self,
        credentials_service: BackblazeCredentialsService,
        state_file: Path,
    ) -> None:
        self._credentials_service = credentials_service
        self._state_file = state_file
        self._lock = RLock()

        self._state_file.parent.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------

    def account_for(self, recorded_at: datetime) -> BackblazeAccount:
        """Account for the day the clip belongs to."""

        day = recorded_at.astimezone(LOCAL_TIME_ZONE).date()
        day_key = day.isoformat()

        with self._lock:
            accounts = self._credentials_service.get()
            enabled = accounts.enabled_accounts()

            if not enabled:
                raise RuntimeError(
                    "No enabled Backblaze account is configured"
                )

            by_name = {account.name: account for account in enabled}
            days = self._read()

            chosen_name = days.get(day_key)

            if chosen_name in by_name:
                return by_name[chosen_name]

            chosen = self._next_account(days, enabled)

            days[day_key] = chosen.name
            self._write(self._prune(days, day))

            LOGGER.info(
                "Backblaze account for %s: %s (bucket %s)",
                day_key,
                chosen.name,
                chosen.bucket,
            )

            return chosen

    def status(self) -> dict:
        today = datetime.now(LOCAL_TIME_ZONE).date()

        with self._lock:
            days = self._read()
            enabled = self._credentials_service.get().enabled_accounts()

        return {
            "timezone": str(LOCAL_TIME_ZONE),
            "today": today.isoformat(),
            "today_account": days.get(today.isoformat()),
            "enabled_accounts": [account.name for account in enabled],
            "days": dict(sorted(days.items())),
        }

    # ------------------------------------------------------------------

    @staticmethod
    def _next_account(
        days: dict[str, str],
        enabled: list[BackblazeAccount],
    ) -> BackblazeAccount:
        if not days:
            return enabled[0]

        latest_day = max(days)
        latest_name = days[latest_day]
        names = [account.name for account in enabled]

        if latest_name not in names:
            # The last used account was removed or disabled: start
            # again from the top of the list.
            return enabled[0]

        return enabled[(names.index(latest_name) + 1) % len(enabled)]

    @staticmethod
    def _prune(days: dict[str, str], today: date) -> dict[str, str]:
        cutoff = (today - timedelta(days=KEEP_DAYS)).isoformat()

        return {
            day: name for day, name in days.items() if day >= cutoff
        }

    def _read(self) -> dict[str, str]:
        if not self._state_file.exists():
            return {}

        try:
            raw = json.loads(self._state_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            LOGGER.warning(
                "Cloud rotation state unreadable; starting afresh: %s",
                self._state_file,
            )
            return {}

        days = raw.get("days", {})

        return {
            str(day): str(name)
            for day, name in days.items()
            if isinstance(name, str)
        }

    def _write(self, days: dict[str, str]) -> None:
        temporary_file = self._state_file.with_suffix(".tmp")

        temporary_file.write_text(
            json.dumps({"days": days}, indent=2) + "\n",
            encoding="utf-8",
        )

        temporary_file.replace(self._state_file)
