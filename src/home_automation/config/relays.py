from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RelayConfig:
    """Hardware configuration for one relay-board channel."""

    key: str
    name: str
    channel: str
    gpio: int
    active_low: bool

    # This represents the relay-coil state, not the appliance power state.
    # For example, the router relay is OFF while the router remains powered
    # through the relay's normally closed contact.
    default_relay_on: bool


RELAYS = (
    RelayConfig(
        key="ro_power",
        name="RO power",
        channel="IN1",
        gpio=2,
        active_low=True,
        default_relay_on=False,
    ),
    RelayConfig(
        key="router_power",
        name="Router power",
        channel="IN2",
        gpio=3,
        active_low=True,
        default_relay_on=False,
    ),
    RelayConfig(
        key="camera_power",
        name="Camera power",
        channel="IN3",
        gpio=12,
        active_low=True,
        default_relay_on=True,
    ),
    RelayConfig(
        key="plant_valve",
        name="Plant solenoid valve",
        channel="IN4",
        gpio=13,
        active_low=True,
        default_relay_on=False,
    ),
    RelayConfig(
        key="main_valve",
        name="Main motorised valve",
        channel="IN5",
        gpio=26,
        active_low=True,
        default_relay_on=False,
    ),
    RelayConfig(
        key="pump",
        name="Pump control",
        channel="IN6",
        gpio=21,
        active_low=True,
        default_relay_on=False,
    ),
)


RELAYS_BY_KEY = {relay.key: relay for relay in RELAYS}