from time import sleep

from gpiozero import OutputDevice

from home_automation.config.relays import RELAYS


def main() -> None:
    devices: list[OutputDevice] = []

    try:
        for relay_config in RELAYS:
            relay = OutputDevice(
                relay_config.gpio,
                active_high=not relay_config.active_low,
                initial_value=False,
            )
            devices.append(relay)

            print(f"Turning ON: {relay_config.channel} - {relay_config.name}")
            relay.on()
            sleep(1)

            print(f"Turning OFF: {relay_config.channel} - {relay_config.name}")
            relay.off()
            sleep(1)
    finally:
        for relay in devices:
            relay.off()
            relay.close()

    print("Relay test completed.")


if __name__ == "__main__":
    main()