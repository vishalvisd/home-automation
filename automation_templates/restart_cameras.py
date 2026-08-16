"""Power-cycle the camera line through the home-automation API."""

import time
import urllib.request


BASE_URL = "http://127.0.0.1:8000"

# Camera line uses the normally open relay contact.
CAMERA_POWER_OFF_SECONDS = 15


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


print("Restarting camera power line")

try:
    relay_command("camera_power", "off")
    time.sleep(CAMERA_POWER_OFF_SECONDS)

finally:
    relay_command("camera_power", "on")

print("Camera restart completed")