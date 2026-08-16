from threading import Event, Lock, Thread

from home_automation.config.watering_settings import WateringSettings
from home_automation.services.relay_manager import RelayManager
from home_automation.services.watering_settings_service import (
    WateringSettingsService,
)


class WateringAlreadyRunningError(RuntimeError):
    """Raised when watering is started while another run is active."""


class WateringStopped(RuntimeError):
    """Internal signal used when a safe stop is requested."""


class WateringService:
    """Run the complete panel-cleaning and plant-watering process."""

    def __init__(
        self,
        relay_manager: RelayManager,
        settings_service: WateringSettingsService,
    ) -> None:
        self._relay_manager = relay_manager
        self._settings_service = settings_service

        self._state_lock = Lock()
        self._stop_event = Event()
        self._thread: Thread | None = None

        self._running = False
        self._last_result = "never_run"
        self._last_error: str | None = None

    def start(self) -> None:
        """
        Start watering using a snapshot of the latest runtime settings.

        Settings changed from the UI during an active run apply to the
        next run, not halfway through the current run.
        """

        with self._state_lock:
            if self._running:
                raise WateringAlreadyRunningError(
                    "Watering is already running."
                )

            settings = self._settings_service.get()

            self._running = True
            self._last_result = "running"
            self._last_error = None
            self._stop_event.clear()

            self._thread = Thread(
                target=self._run,
                args=(settings,),
                name="watering-process",
                daemon=True,
            )
            self._thread.start()

    def stop(self) -> None:
        """Request safe termination of the current run."""

        self._stop_event.set()

    def status(self) -> dict[str, str | bool | None]:
        with self._state_lock:
            return {
                "running": self._running,
                "last_result": self._last_result,
                "last_error": self._last_error,
            }

    def shutdown(self) -> None:
        """
        Stop an active run before GPIO resources are released.

        Waiting here is intentional because the valves must be returned
        to their configured resting state before RelayManager is closed.
        """

        self.stop()

        thread = self._thread

        if thread is not None and thread.is_alive():
            thread.join()

    def _run(self, settings: WateringSettings) -> None:
        hardware_safe = False

        try:
            print("Starting watering process")

            # Supply mains power to the valve-control relays.
            self._relay_manager.turn_on("valve_power")

            print("Opening main valve")
            self._relay_manager.turn_on("main_valve")
            self._wait(
                settings.main_valve_open_delay_seconds
            )

            print("Starting water pump")
            self._relay_manager.turn_on("pump")

            print("Cleaning solar panels")
            self._wait(
                settings.panel_sprinkler_seconds
            )

            print("Opening plant valve")
            self._relay_manager.turn_on("plant_valve")
            self._wait(
                settings.plant_valve_open_delay_seconds
            )

            print("Watering plants")
            self._wait(
                settings.plant_watering_seconds
            )

            print("Stopping water pump")
            self._relay_manager.turn_off("pump")
            self._wait(
                settings.wait_after_pump_stop_seconds
            )

            print("Closing plant valve")
            self._relay_manager.turn_off("plant_valve")
            self._wait(
                settings.plant_valve_close_delay_seconds
            )

            self._wait(
                settings.water_settling_seconds
            )

            print("Closing main valve")
            self._relay_manager.turn_off("main_valve")
            self._wait(
                settings.main_valve_close_delay_seconds
            )

            print("Removing valve-system power")
            self._relay_manager.turn_off("valve_power")

            hardware_safe = True
            self._set_result("completed")

        except WateringStopped:
            self._set_result("stopped")

        except Exception as error:
            self._set_result(
                "failed",
                error=str(error),
            )

        finally:
            if not hardware_safe:
                self._safe_cleanup(settings)

            with self._state_lock:
                self._running = False

            print("Watering process finished")

    def _safe_cleanup(
        self,
        settings: WateringSettings,
    ) -> None:
        """Return watering hardware to its resting configuration."""

        print("Running safe watering cleanup")

        try:
            self._relay_manager.turn_off("pump")

            # Ensure valve circuits have power while closing.
            self._relay_manager.turn_on("valve_power")

            self._relay_manager.turn_off("plant_valve")
            self._interruptible_cleanup_wait(
                settings.plant_valve_close_delay_seconds
            )

            self._relay_manager.turn_off("main_valve")
            self._interruptible_cleanup_wait(
                settings.main_valve_close_delay_seconds
            )

            self._relay_manager.turn_off("valve_power")

        except Exception as error:
            self._set_result(
                "failed",
                error=f"Cleanup failed: {error}",
            )

    def _wait(self, seconds: int) -> None:
        if seconds <= 0:
            return

        if self._stop_event.wait(timeout=seconds):
            raise WateringStopped()

    @staticmethod
    def _interruptible_cleanup_wait(seconds: int) -> None:
        """
        Cleanup delays must complete even when the stop flag is set.

        A stop request must not prevent a motorised valve from getting
        enough time to reach its closed position.
        """

        if seconds <= 0:
            return

        Event().wait(timeout=seconds)

    def _set_result(
        self,
        result: str,
        *,
        error: str | None = None,
    ) -> None:
        with self._state_lock:
            self._last_result = result
            self._last_error = error