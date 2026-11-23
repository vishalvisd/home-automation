import logging
import socket
from datetime import datetime
from threading import Event, Lock
from time import monotonic

from home_automation.services.camera_settings_service import (
    CameraSettingsService,
)
from home_automation.services.clip_naming import LOCAL_TIME_ZONE
from home_automation.services.relay_manager import RelayManager


LOGGER = logging.getLogger("home_automation")

# The relay the main router is powered through (config/relays.py). The
# router hangs on the normally closed contact: relay ON cuts its power,
# relay OFF powers it.
ROUTER_RELAY_KEY = "router_power"

# After the configured wait, keep waiting until this address answers,
# so uploads do not resume into a router that is still starting. It is
# the address the uploads need anyway.
INTERNET_CHECK_HOST = "api.backblazeb2.com"
INTERNET_CHECK_PORT = 443
INTERNET_CHECK_EVERY_SECONDS = 5
INTERNET_CHECK_TIMEOUT_SECONDS = 5

# Never hold the uploads longer than this after power is back.
INTERNET_MAX_WAIT_SECONDS = 300


class RouterRestartService:
    """
    Power-cycle the main router once, for its own health.

    CameraUploadService calls restart() just after midnight, when the
    first clip of a new day is about to pick that day's Backblaze
    account, and holds every upload until it returns.

    Every camera reaches the Pi through the router's own ports, so
    nothing is recorded while the router is off and starting: about two
    minutes on all cameras. The owner accepts that (docs/decisions.md).
    """

    def __init__(
        self,
        settings_service: CameraSettingsService,
        relay_manager: RelayManager,
    ) -> None:
        self._settings_service = settings_service
        self._relay_manager = relay_manager

        self._run_lock = Lock()
        self._abort = Event()

        self._status_lock = Lock()
        self._status: dict = {
            "running": False,
            "last_started_at": None,
            "last_finished_at": None,
            "last_power_off_seconds": None,
            "last_internet_back_after_seconds": None,
            "last_result": None,
        }

    def restart(self) -> dict:
        """
        Cut the router's power, restore it, and wait until the
        internet answers. Blocks for the whole time. The relay is
        always released, whatever happens.
        """

        settings = self._settings_service.get()
        off_seconds = settings.router_restart_off_seconds
        wait_seconds = settings.router_restart_wait_seconds

        with self._run_lock:
            self._note(
                running=True,
                last_started_at=self._now(),
                last_finished_at=None,
                last_power_off_seconds=off_seconds,
                last_internet_back_after_seconds=None,
                last_result=None,
            )

            LOGGER.info(
                "Router restart: power off for %s seconds", off_seconds
            )

            result = "ok"
            back_after: float | None = None

            try:
                try:
                    self._relay_manager.turn_on(ROUTER_RELAY_KEY)
                    self._abort.wait(timeout=off_seconds)
                finally:
                    self._relay_manager.turn_off(ROUTER_RELAY_KEY)

                power_back = monotonic()

                LOGGER.info(
                    "Router restart: power back on; waiting at least "
                    "%s seconds",
                    wait_seconds,
                )

                self._abort.wait(timeout=wait_seconds)

                limit = max(wait_seconds, INTERNET_MAX_WAIT_SECONDS)

                while not self._abort.is_set():
                    if self._internet_answers():
                        back_after = round(monotonic() - power_back, 1)
                        break

                    if monotonic() - power_back >= limit:
                        result = (
                            f"the internet did not answer within {limit} "
                            "seconds; uploads resumed anyway"
                        )
                        break

                    self._abort.wait(timeout=INTERNET_CHECK_EVERY_SECONDS)

                if self._abort.is_set():
                    result = "stopped early because the backend is shutting down"

            except Exception as error:
                LOGGER.exception("Router restart failed")
                result = f"error: {error}"

            self._note(
                running=False,
                last_finished_at=self._now(),
                last_internet_back_after_seconds=back_after,
                last_result=result,
            )

            LOGGER.info(
                "Router restart finished: %s (internet back after %s seconds)",
                result,
                back_after,
            )

            return self.status()

    def abort(self) -> None:
        """End a running restart at once; the relay is released."""

        self._abort.set()

    def status(self) -> dict:
        settings = self._settings_service.get()

        with self._status_lock:
            return {
                "enabled": settings.router_restart_enabled,
                "off_seconds": settings.router_restart_off_seconds,
                "wait_seconds": settings.router_restart_wait_seconds,
                **self._status,
            }

    def _note(self, **changes) -> None:
        with self._status_lock:
            self._status.update(changes)

    @staticmethod
    def _now() -> str:
        return datetime.now(LOCAL_TIME_ZONE).isoformat(timespec="seconds")

    @staticmethod
    def _internet_answers() -> bool:
        try:
            with socket.create_connection(
                (INTERNET_CHECK_HOST, INTERNET_CHECK_PORT),
                timeout=INTERNET_CHECK_TIMEOUT_SECONDS,
            ):
                return True
        except OSError:
            return False
