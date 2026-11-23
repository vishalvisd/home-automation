"""
Check of "Stop recording for N minutes" in CameraRecorderService.

Run on the development machine:

    uv run python tests/check_timed_stop.py

No camera is configured in this check, so no recorder really starts;
it checks the timer: that recording is asked to start again by itself,
and that Start Recording and Stop Recording end or cancel the wait.
"""

import time
from types import SimpleNamespace

from home_automation.services.camera_recorder_service import (
    CameraRecorderService,
)


def build(minutes: float):
    settings = SimpleNamespace(
        cameras=[],
        recording_enabled=True,
        recording_directory="/tmp/not-used",
        recorder_restart_delay_seconds=10,
        archive_enabled=False,
        recording_stop_minutes=minutes,
    )

    uploads = SimpleNamespace(
        pause_status=lambda: {},
        status=lambda camera_key: {},
    )

    service = CameraRecorderService(
        SimpleNamespace(get=lambda: settings),
        uploads,
        None,
        None,
    )

    return service


def wait_until(condition, seconds=8.0) -> bool:
    deadline = time.monotonic() + seconds

    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.05)

    return condition()


# 1. It stops now and starts again by itself.
service = build(minutes=0.02)  # 1.2 seconds
service.start()
assert service.status()["desired_running"] is True

status = service.stop_for_a_while()
assert status["desired_running"] is False and status["stopped_until"], status
assert wait_until(lambda: service.status()["desired_running"] is True)
assert service.status()["stopped_until"] is None
print("1 ok: recording was stopped, then asked to start again by itself")
service.shutdown()

# 2. Start Recording during the wait starts now and clears the timer.
service = build(minutes=60)
service.start()
service.stop_for_a_while()
status = service.start()
assert status["desired_running"] is True and status["stopped_until"] is None
print("2 ok: Start Recording ended the wait at once")

# 3. Stop Recording during the wait keeps it stopped for good.
service.stop_for_a_while()
status = service.stop()
assert status["desired_running"] is False and status["stopped_until"] is None
time.sleep(2.5)  # longer than the supervisor's check interval
assert service.status()["desired_running"] is False
print("3 ok: Stop Recording cancelled the automatic start")
service.shutdown()

# 4. Shutting down during the wait does not start anything.
service = build(minutes=0.02)
service.start()
service.stop_for_a_while()
service.shutdown()
time.sleep(2.0)
assert service.status()["desired_running"] is False
print("4 ok: a shutdown during the wait started nothing")

print("ALL OK")
