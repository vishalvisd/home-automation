"""Restart both router and camera power lines."""

import time
import urllib.request


BASE_URL = "http://127.0.0.1:8000"

POWER_OFF_SECONDS = 60
ROUTER_RECOVERY_SECONDS = 20


def relay_command(relay: str, command: str) -> None:
    request = urllib.request.Request(
        f"{BASE_URL}/api/relays/{relay}/{command}",
        method="POST",
    )

    with urllib.request.urlopen(
        request,
        timeout=10,
    ):
        pass


print("Restarting router and camera line")

try:
    # Camera relay OFF removes camera power.
    relay_command("camera_power", "off")

    # Router relay ON removes router power because it uses NC.
    relay_command("router_power", "on")

    time.sleep(POWER_OFF_SECONDS)

    # Restore the router first.
    relay_command("router_power", "off")

    # Give the network some time to recover before cameras return.
    time.sleep(ROUTER_RECOVERY_SECONDS)

    relay_command("camera_power", "on")

finally:
    # Always leave both systems powered.
    relay_command("router_power", "off")
    relay_command("camera_power", "on")

print("Router and camera restart completed")