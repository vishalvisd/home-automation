"""Power-cycle the main router through the home-automation API."""

import time
import urllib.request


BASE_URL = "http://127.0.0.1:8000"

# Router uses the normally closed relay contact.
# Relay ON cuts router power.
ROUTER_POWER_OFF_SECONDS = 60


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


print("Restarting router")

try:
    relay_command("router_power", "on")
    time.sleep(ROUTER_POWER_OFF_SECONDS)

finally:
    # Relay OFF restores power through the normally closed contact.
    relay_command("router_power", "off")

print("Router restart completed")