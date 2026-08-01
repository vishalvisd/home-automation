from dataclasses import dataclass


@dataclass(frozen=True)
class RelayConfig:
    name: str
    channel: str
    gpio: int
    active_low: bool
    default_relay_on: bool


RELAYS = (
    RelayConfig(
        name="RO power",
        channel="IN1",
        gpio=2,
        active_low=True,
        default_relay_on=False,
    ),
    RelayConfig(
        name="Router power",
        channel="IN2",
        gpio=3,
        active_low=True,
        default_relay_on=False,
    ),
    RelayConfig(
        name="Camera power",
        channel="IN3",
        gpio=12,
        active_low=True,
        default_relay_on=True,
    ),
    RelayConfig(
        name="Plant valve",
        channel="IN4",
        gpio=13,
        active_low=True,
        default_relay_on=False,
    ),
    RelayConfig(
        name="Main valve",
        channel="IN5",
        gpio=26,
        active_low=True,
        default_relay_on=False,
    ),
    RelayConfig(
        name="Pump",
        channel="IN6",
        gpio=21,
        active_low=True,
        default_relay_on=False,
    ),
)