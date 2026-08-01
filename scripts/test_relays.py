from time import sleep

from gpiozero import OutputDevice


RELAYS = [
    ("IN1 - RO power", 2),
    ("IN2 - Router power", 3),
    ("IN3 - Camera power", 12),
    ("IN4 - Plant valve", 13),
    ("IN5 - Main valve", 26),
    ("IN6 - Pump", 21),
]


def main() -> None:
    relays: list[OutputDevice] = []

    try:
        for name, gpio_pin in RELAYS:
            relay = OutputDevice(
                gpio_pin,
                active_high=False,
                initial_value=False,
            )
            relays.append(relay)

            print(f"Turning ON: {name}")
            relay.on()
            sleep(1)

            print(f"Turning OFF: {name}")
            relay.off()
            sleep(1)
    finally:
        for relay in relays:
            relay.off()
            relay.close()

    print("Relay test completed.")


if __name__ == "__main__":
    main()
