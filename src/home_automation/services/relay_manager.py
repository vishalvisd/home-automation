from threading import Lock

from gpiozero import OutputDevice

from home_automation.config.relays import RELAYS_BY_KEY, RelayConfig


class UnknownRelayError(ValueError):
    """Raised when an unknown relay key is requested."""


class RelayManager:
    """
    Own all General-Purpose Input/Output relay devices.

    Only the continuously running backend should create this manager. Other
    scripts and the frontend will send commands to the backend instead of
    accessing General-Purpose Input/Output pins directly.
    """

    def __init__(self) -> None:
        self._lock = Lock()
        self._devices: dict[str, OutputDevice] = {}

        try:
            for relay_config in RELAYS_BY_KEY.values():
                self._devices[relay_config.key] = self._create_device(
                    relay_config
                )
        except Exception:
            self.close()
            raise

    def turn_on(self, relay_key: str) -> None:
        """Energise the requested relay channel."""

        with self._lock:
            self._get_device(relay_key).on()

    def turn_off(self, relay_key: str) -> None:
        """Release the requested relay channel."""

        with self._lock:
            self._get_device(relay_key).off()

    def close(self) -> None:
        """Release every General-Purpose Input/Output device."""

        with self._lock:
            for device in self._devices.values():
                device.close()

            self._devices.clear()

    @staticmethod
    def _create_device(relay_config: RelayConfig) -> OutputDevice:
        # The relay board is active-low:
        # logical ON drives the General-Purpose Input/Output pin LOW.
        device = OutputDevice(
            relay_config.gpio,
            active_high=not relay_config.active_low,
            initial_value=False,
        )

        if relay_config.default_relay_on:
            device.on()
        else:
            device.off()

        return device

    def _get_device(self, relay_key: str) -> OutputDevice:
        try:
            return self._devices[relay_key]
        except KeyError as error:
            raise UnknownRelayError(
                f"Unknown relay: {relay_key}"
            ) from error