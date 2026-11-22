import csv
import logging
from datetime import datetime
from pathlib import Path
from threading import Lock

from home_automation.services.clip_naming import LOCAL_TIME_ZONE


LOGGER = logging.getLogger("home_automation")

FIELDS = [
    "time",
    "event",
    "reason",
    "seconds",
    "clips",
    "mb",
    "start_stop_count",
    "load_cycle_count",
    "note",
]

# What the "event" column can hold:
#   service_start  the backend started; the disk's state is not known yet
#   wake           we mounted the disk (this spins it up); "reason" says
#                  why: timer, size, low_ram, shutdown, manual, browse;
#                  "seconds" is how long the mount took
#   wake_failed    the mount did not work; "note" has the error
#   batch          a batch finished; clips, mb, "seconds" for the whole
#                  batch, and the disk's own SMART counters
#   stay_awake     a batch finished but the disk was left running
#                  because the downloader is browsing it
#   park           we unmounted and parked the disk; "seconds" is how
#                  long it had been awake; "note" is ok or the error
#   check          the answer of the sleep check between batches, written
#                  only when it changes; "reason" is asleep, awake or
#                  unknown


class DiskActivityLog:
    """
    A small text file that records when the USB disk is woken and
    parked, so its rest can be studied for a few days. It is written
    only while the setting archive_activity_log_enabled is on. One line
    per event, a few hundred lines a day.
    """

    def __init__(self, log_file: Path) -> None:
        self._log_file = log_file
        self._lock = Lock()

    @property
    def path(self) -> Path:
        return self._log_file

    def write(self, event: str, **fields) -> None:
        row = {name: "" for name in FIELDS}
        row["time"] = datetime.now(LOCAL_TIME_ZONE).isoformat(timespec="seconds")
        row["event"] = event

        for name, value in fields.items():
            if name in row and value is not None:
                row[name] = value

        try:
            with self._lock:
                self._log_file.parent.mkdir(parents=True, exist_ok=True)
                new_file = not self._log_file.exists()

                with open(self._log_file, "a", newline="") as handle:
                    writer = csv.DictWriter(handle, fieldnames=FIELDS)

                    if new_file:
                        writer.writeheader()

                    writer.writerow(row)

        except OSError as error:
            # The study must never disturb recording.
            LOGGER.warning("Could not write the disk activity log: %s", error)

    def read(self) -> list[dict]:
        try:
            with self._lock, open(self._log_file, newline="") as handle:
                return list(csv.DictReader(handle))
        except FileNotFoundError:
            return []
        except OSError as error:
            LOGGER.warning("Could not read the disk activity log: %s", error)
            return []

    def summary(self) -> list[dict]:
        """One row per calendar day (Asia/Kolkata), oldest day first."""

        days: dict[str, dict] = {}

        def day_of(row: dict) -> dict:
            return days.setdefault(
                row["time"][:10],
                {
                    "day": row["time"][:10],
                    "wakes": 0,
                    "wakes_by_reason": {},
                    "batches": 0,
                    "clips": 0,
                    "mb": 0.0,
                    "awake_minutes": 0.0,
                    "rests": 0,
                    "longest_rest_minutes": None,
                    "shortest_rest_minutes": None,
                    "average_rest_minutes": None,
                    "spin_ups_counted_by_disk": 0,
                    "spin_ups_not_ours": 0,
                    "found_awake_unexpectedly": 0,
                    "failures": 0,
                    "_rest_total": 0.0,
                },
            )

        last_park_at: datetime | None = None
        last_counter: int | None = None
        wakes_since_counter = 0

        for row in self.read():
            try:
                moment = datetime.fromisoformat(row["time"])
            except (KeyError, ValueError):
                continue

            day = day_of(row)
            event = row.get("event", "")

            if event == "service_start":
                # A restart: what happened to the disk in between is
                # not known, so do not count a rest across it.
                last_park_at = None

            elif event == "wake":
                day["wakes"] += 1
                reason = row.get("reason") or "unknown"
                day["wakes_by_reason"][reason] = (
                    day["wakes_by_reason"].get(reason, 0) + 1
                )
                wakes_since_counter += 1

                if last_park_at is not None:
                    rest = (moment - last_park_at).total_seconds() / 60
                    day["rests"] += 1
                    day["_rest_total"] += rest

                    if (
                        day["longest_rest_minutes"] is None
                        or rest > day["longest_rest_minutes"]
                    ):
                        day["longest_rest_minutes"] = round(rest, 1)

                    if (
                        day["shortest_rest_minutes"] is None
                        or rest < day["shortest_rest_minutes"]
                    ):
                        day["shortest_rest_minutes"] = round(rest, 1)

                    last_park_at = None

            elif event == "batch":
                day["batches"] += 1
                day["clips"] += self._int(row.get("clips")) or 0
                day["mb"] += self._float(row.get("mb")) or 0.0

                counter = self._int(row.get("start_stop_count"))

                if counter is not None:
                    if last_counter is not None and counter >= last_counter:
                        counted = counter - last_counter
                        day["spin_ups_counted_by_disk"] += counted
                        day["spin_ups_not_ours"] += max(
                            0, counted - wakes_since_counter
                        )

                    last_counter = counter
                    wakes_since_counter = 0

            elif event == "park":
                day["awake_minutes"] += (self._float(row.get("seconds")) or 0.0) / 60

                if row.get("note") == "ok":
                    last_park_at = moment
                else:
                    day["failures"] += 1

            elif event == "wake_failed":
                day["failures"] += 1

            elif event == "check" and row.get("reason") == "awake":
                day["found_awake_unexpectedly"] += 1

        result = []

        for key in sorted(days):
            day = days[key]
            rest_total = day.pop("_rest_total")

            if day["rests"]:
                day["average_rest_minutes"] = round(rest_total / day["rests"], 1)

            day["mb"] = round(day["mb"], 1)
            day["awake_minutes"] = round(day["awake_minutes"], 1)
            result.append(day)

        return result

    @staticmethod
    def _int(value) -> int | None:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _float(value) -> float | None:
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
