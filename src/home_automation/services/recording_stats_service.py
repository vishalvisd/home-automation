import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from threading import RLock
from time import monotonic

from home_automation.services.clip_naming import LOCAL_TIME_ZONE


LOGGER = logging.getLogger("home_automation")

# "disk" is the primary recording on the USB disk, "cloud" the backup in
# Backblaze.
COPIES = ("disk", "cloud")

KEEP_HOURS = 48
SAVE_EVERY_SECONDS = 3600


class RecordingStatsService:
    """
    Count, per camera, per copy and per hour, the clips that actually
    reached their storage, so the UI can show the last 24 hours at a
    glance. Counters live in RAM and are written to one small file at
    most once an hour (and at shutdown), so a restart does not blank
    the view. The hour is the clip's own recording hour, not the
    moment it was stored.
    """

    def __init__(self, stats_file: Path) -> None:
        self._stats_file = stats_file
        self._lock = RLock()
        # {"cam1": {"disk": {"2026-11-22T09:00": {"count": 20, "bytes": 1234}}}}
        self._hours: dict[str, dict[str, dict[str, dict[str, int]]]] = {}
        self._since: datetime | None = None
        self._dirty = False
        self._last_save = monotonic()

        self._stats_file.parent.mkdir(parents=True, exist_ok=True)
        self._load()

        if self._since is None:
            self._since = datetime.now(LOCAL_TIME_ZONE)

    # ------------------------------------------------------------------

    def record(
        self,
        camera_key: str,
        copy: str,
        byte_count: int,
        recorded_at: datetime,
    ) -> None:
        hour = self._hour_key(recorded_at)

        with self._lock:
            bucket = (
                self._hours.setdefault(camera_key, {})
                .setdefault(copy, {})
                .setdefault(hour, {"count": 0, "bytes": 0})
            )
            bucket["count"] += 1
            bucket["bytes"] += int(byte_count)
            self._dirty = True

        self._save_if_due()

    def hours(self, camera_key: str, copy: str, count: int = 24) -> list[dict]:
        """The last `count` hours, oldest first, ending with the current hour."""

        now = datetime.now(LOCAL_TIME_ZONE)
        current = now.replace(minute=0, second=0, microsecond=0)
        result = []

        with self._lock:
            buckets = self._hours.get(camera_key, {}).get(copy, {})
            since = self._since

        for offset in range(count - 1, -1, -1):
            start = current - timedelta(hours=offset)
            key = self._hour_key(start)
            bucket = buckets.get(key)
            # An hour is "known" once the counters existed during it, or
            # when something was counted for it (loaded from the file).
            known = bucket is not None or (
                since is not None and start + timedelta(hours=1) > since
            )

            result.append(
                {
                    "hour": start.isoformat(),
                    "count": bucket["count"] if bucket else 0,
                    "bytes": bucket["bytes"] if bucket else 0,
                    # False for hours before the counters existed.
                    "known": known,
                    "current": offset == 0,
                }
            )

        return result

    def shutdown(self) -> None:
        self._save(force=True)

    # ------------------------------------------------------------------

    @staticmethod
    def _hour_key(moment: datetime) -> str:
        return moment.astimezone(LOCAL_TIME_ZONE).strftime("%Y-%m-%dT%H:00")

    def _save_if_due(self) -> None:
        if monotonic() - self._last_save >= SAVE_EVERY_SECONDS:
            self._save()

    def _save(self, force: bool = False) -> None:
        with self._lock:
            if not self._dirty and not force:
                return

            self._prune()
            payload = {
                "since": self._since.isoformat() if self._since else None,
                "hours": self._hours,
            }
            self._dirty = False
            self._last_save = monotonic()

        try:
            temporary = self._stats_file.with_suffix(".tmp")
            temporary.write_text(json.dumps(payload, indent=1) + "\n", encoding="utf-8")
            temporary.replace(self._stats_file)
        except OSError as error:
            LOGGER.warning("Could not save recording stats: %s", error)

    def _load(self) -> None:
        if not self._stats_file.exists():
            return

        try:
            payload = json.loads(self._stats_file.read_text(encoding="utf-8"))
            self._hours = payload.get("hours", {}) or {}
            since = payload.get("since")
            self._since = datetime.fromisoformat(since) if since else None
            self._prune()
        except (OSError, ValueError) as error:
            LOGGER.warning("Recording stats unreadable; starting afresh: %s", error)
            self._hours = {}
            self._since = None

    def _prune(self) -> None:
        cutoff = self._hour_key(datetime.now(LOCAL_TIME_ZONE) - timedelta(hours=KEEP_HOURS))

        for camera in self._hours.values():
            for copy in camera.values():
                for key in [key for key in copy if key < cutoff]:
                    del copy[key]
