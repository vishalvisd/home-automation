from threading import Event, Lock, Thread
from time import sleep

from home_automation.config.watering import (
    MAIN_VALVE_MOVEMENT_SECONDS,
    PANEL_SPRINKLER_SECONDS,
    PLANT_WATERING_SECONDS,
    WAIT_AFTER_PUMP_STOP_SECONDS,
    WATER_SETTLING_SECONDS,
)
from home_automation.services.relay_manager import RelayManager


class WateringAlreadyRunningError(RuntimeError):
    """Raised when watering is started while another run is active."""


class WateringService:
    """Run the complete solar-panel cleaning and plant-watering sequence."""

    def __init__(self, relay_manager: RelayManager) -> None:
        self._relay_manager = relay_manager
        self._state_lock = Lock()
        self._stop_event = Event()
        self._thread: Thread | None = None
        self._running = False
        self._last_result = "never_run"
        self._last_error: str | None = None

    def start(self) -> None:
        """Start watering in a background thread."""

        with self._state_lock:
            if self._running:
                raise WateringAlreadyRunningError(
                    "Watering is already running."
                )

            self._running = True
            self._last_result = "running"
            self._last_error = None
            self._stop_event.clear()

            self._thread = Thread(
                target=self._run,
                name="watering-process",
                daemon=True,
            )
            self._thread.start()

    def stop(self) -> None:
        """Request safe termination of the current watering run."""

        self._stop_event.set()

    def status(self) -> dict[str, str | bool | None]:
        """Return execution status without reporting physical relay states."""

        with self._state_lock:
            return {
                "running": self._running,
                "last_result": self._last_result,
                "last_error": self._last_error,
            }

    def shutdown(self) -> None:
        """Safely stop watering before the backend releases GPIO resources."""

        self.stop()

        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(
                timeout=MAIN_VALVE_MOVEMENT_SECONDS + 5
            )

    def _run(self) -> None:
        try:
            print("Starting watering process")

            # Supply power to the main motorised valve and plant valve.
            self._relay_manager.turn_on("valve_power")

            print("Opening main motorised valve")
            self._relay_manager.turn_on("main_valve")

            if not self._wait(MAIN_VALVE_MOVEMENT_SECONDS):
                self._set_result("stopped")
                return

            print("Starting water pump")
            self._relay_manager.turn_on("pump")

            if not self._wait(PANEL_SPRINKLER_SECONDS):
                self._set_result("stopped")
                return

            print("Opening plant solenoid valve")
            self._relay_manager.turn_on("plant_valve")

            if not self._wait(PLANT_WATERING_SECONDS):
                self._set_result("stopped")
                return

            print("Stopping water pump")
            self._relay_manager.turn_off("pump")

            if not self._wait(WAIT_AFTER_PUMP_STOP_SECONDS):
                self._set_result("stopped")
                return

            print("Closing plant solenoid valve")
            self._relay_manager.turn_off("plant_valve")

            if not self._wait(WATER_SETTLING_SECONDS):
                self._set_result("stopped")
                return

            self._set_result("completed")

        except Exception as error:
            self._set_result(
                "failed",
                error=str(error),
            )

        finally:
            self._safe_cleanup()

            with self._state_lock:
                self._running = False

            print("Watering process finished")

    def _safe_cleanup(self) -> None:
        """
        Leave the watering hardware in its safe resting configuration.

        Valve power remains available while the main motorised valve closes.
        It is removed only after the valve movement time has elapsed.
        """

        print("Running watering cleanup")

        self._relay_manager.turn_off("pump")
        self._relay_manager.turn_off("plant_valve")

        self._relay_manager.turn_on("valve_power")
        self._relay_manager.turn_off("main_valve")

        sleep(MAIN_VALVE_MOVEMENT_SECONDS)

        self._relay_manager.turn_off("valve_power")

    def _wait(self, seconds: int) -> bool:
        """Wait for the duration or return early when stopping is requested."""

        return not self._stop_event.wait(timeout=seconds)

    def _set_result(
        self,
        result: str,
        *,
        error: str | None = None,
    ) -> None:
        with self._state_lock:
            self._last_result = result
            self._last_error = error