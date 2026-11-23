"""
Check of the upload pause in CameraUploadService, with a pretend cloud.

Run on the development machine:

    uv run python tests/check_upload_pause.py

It needs no camera, disk or internet. It prints what it checked and ends
with "ALL OK", or stops at the first check that fails.
"""

import os
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

from home_automation.config.camera_settings import CameraConfig
from home_automation.services.camera_upload_service import (
    LOCAL_TIME_ZONE,
    CameraUploadService,
)


def build(**overrides):
    """A service with four cameras, a pretend cloud and short times."""

    folder = Path(tempfile.mkdtemp())

    values = dict(
        b2_upload_enabled=True,
        pending_upload_limit=3,
        upload_pause_minutes=60,
        upload_pause_buffer_mb=200,
        archive_buffer_reserve_mb=250,
        router_restart_enabled=False,
        cameras=[
            CameraConfig(
                key=f"cam{number}",
                name=f"Camera {number}",
                source_type="rtsp",
                stream_url="rtsp://example/",
            )
            for number in (1, 2, 3, 4)
        ],
    )
    values.update(overrides)

    settings = SimpleNamespace(**values)
    uploaded: list[str] = []

    class PretendCloud:
        def upload(self, local_file, remote_key, recorded_at):
            time.sleep(0.02)
            uploaded.append(remote_key.rsplit("/", 1)[-1])
            return "pretend-account"

    service = CameraUploadService(
        SimpleNamespace(get=lambda: settings),
        PretendCloud(),
    )

    # Plenty of RAM unless a check says otherwise.
    service._ram_free_bytes = lambda directory: 10 * 1024**3

    start = datetime(2026, 11, 23, 15, 0, 0, tzinfo=LOCAL_TIME_ZONE)
    counter = {"n": 0}

    def clip(camera_index: int, size: int = 1000) -> Path:
        counter["n"] += 1
        when = start + timedelta(seconds=10 * counter["n"])
        path = folder / f"cam{camera_index + 1}_{counter['n']:03d}.mp4"
        path.write_bytes(b"x" * size)
        os.utime(path, (when.timestamp(), when.timestamp()))
        service.submit(settings.cameras[camera_index], path)
        return path

    return service, settings, uploaded, clip


def wait_until(condition, seconds=5.0) -> bool:
    deadline = time.monotonic() + seconds

    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.02)

    return condition()


# 1. A pause holds every clip, far more than pending_upload_limit, and
#    a resume uploads all of them, oldest first, with nothing dropped.
service, settings, uploaded, clip = build()
service.pause_uploads()

for _ in range(7):
    for camera_index in range(4):
        clip(camera_index)

time.sleep(0.3)
status = service.pause_status()
assert uploaded == [], uploaded
assert status["paused"] and status["waiting_files"] == 28, status
assert status["dropped"] == 0 and status["until"], status

service.resume_uploads()
assert wait_until(lambda: len(uploaded) == 28), len(uploaded)
times = [name[-12:-4] for name in uploaded]
assert sorted(uploaded) == sorted(set(uploaded))
assert all(service.status(f"cam{n}")["dropped"] == 0 for n in (1, 2, 3, 4))
print("1 ok: 28 clips waited through the pause, all uploaded after resume")

# 2. After the backlog is gone the normal rule is back.
assert wait_until(lambda: service.pause_status()["catching_up"] is False)
assert service._backlog_allowed(settings.pending_upload_limit) is False
print("2 ok: back to the normal waiting rule after catching up")
service.shutdown()

# 3. The size limit: the oldest clips of all cameras go first, the
#    newest always stays.
service, settings, uploaded, clip = build(upload_pause_buffer_mb=20)
service.pause_uploads()
paths = [clip(index % 4, size=3 * 1024 * 1024) for index in range(10)]  # 30 MB
status = service.pause_status()
assert status["waiting_mb"] <= 21.5, status
assert status["dropped"] == 4, status
assert not any(path.exists() for path in paths[:4]), "oldest four must be gone"
assert all(path.exists() for path in paths[4:]), "newest six must remain"
service.resume_uploads()
assert wait_until(lambda: len(uploaded) == 6)
print("3 ok: over the size limit, the 4 oldest of 10 were dropped, 6 uploaded")
service.shutdown()

# 4. The RAM guard: when the RAM disk runs short, the cloud clips give
#    way, down to the newest one, whatever the size limit says.
service, settings, uploaded, clip = build()
service.pause_uploads()
paths = [clip(index % 4) for index in range(5)]
service._ram_free_bytes = lambda directory: 100 * 1024 * 1024  # under 2 x 250 MB
newest = clip(0)
status = service.pause_status()
assert status["waiting_files"] == 1 and newest.exists(), status
assert status["dropped"] == 5, status
print("4 ok: RAM short, cloud clips gave way and only the newest stayed")
service.shutdown()

# 5. The pause ends by itself.
service, settings, uploaded, clip = build(upload_pause_minutes=0.01)  # 0.6 s
service.pause_uploads()
clip(0)
clip(1)
time.sleep(0.2)
assert uploaded == [] and service.pause_status()["paused"]
assert wait_until(lambda: len(uploaded) == 2, seconds=4)
assert service.pause_status()["paused"] is False
print("5 ok: the pause ended by itself and the clips uploaded")
service.shutdown()

# 6. Pressing pause again starts the time afresh.
service, settings, uploaded, clip = build()
first = service.pause_uploads()["until"]
time.sleep(1.1)
second = service.pause_uploads()["until"]
assert second > first, (first, second)
print("6 ok: pressing pause again moved the end time")

# 7. Shutting down during a pause is quick and keeps only what the
#    normal rule keeps (3 per camera).
for _ in range(6):
    for camera_index in range(4):
        clip(camera_index)

began = time.monotonic()
service.shutdown()
took = time.monotonic() - began
assert took < 3, took
assert len(uploaded) == 12, len(uploaded)
print(f"7 ok: shutdown during a pause took {took:.1f} s; 12 of 24 clips uploaded")

# 8. With uploads switched off nothing changes: the clip is deleted.
service, settings, uploaded, clip = build(b2_upload_enabled=False)
path = clip(0)
assert not path.exists() and uploaded == []
print("8 ok: uploads switched off still deletes the clip at once")
service.shutdown()

# 9. The "skip" pause: nothing waits, nothing is uploaded, and nothing
#    is uploaded after it ends either.
service, settings, uploaded, clip = build()
status = service.pause_uploads("skip")
assert status["paused"] and status["mode"] == "skip", status
paths = [clip(index % 4) for index in range(12)]
time.sleep(0.3)
status = service.pause_status()
assert uploaded == [] and not any(path.exists() for path in paths)
assert status["waiting_files"] == 0 and status["skipped"] == 12, status
service.resume_uploads()
time.sleep(0.3)
assert uploaded == [], "a skip pause must leave nothing to upload afterwards"
assert service.pause_status()["catching_up"] is False
after = clip(0)
assert wait_until(lambda: len(uploaded) == 1)
print("9 ok: skip pause deleted 12 clips, nothing uploaded after it; uploads work again")
service.shutdown()

# 10. Going from "hold" to "skip" deletes the clips that were waiting.
service, settings, uploaded, clip = build()
service.pause_uploads("hold")
paths = [clip(index % 4) for index in range(8)]
time.sleep(0.2)
assert service.pause_status()["waiting_files"] == 8
service.pause_uploads("skip")
assert wait_until(lambda: not any(path.exists() for path in paths))
assert uploaded == [] and service.pause_status()["waiting_files"] == 0
print("10 ok: switching from hold to skip deleted the 8 waiting clips")

# 11. Going from "skip" to "hold" keeps clips from then on.
service.pause_uploads("hold")
clip(0)
clip(1)
time.sleep(0.2)
assert uploaded == [] and service.pause_status()["waiting_files"] == 2
service.resume_uploads()
assert wait_until(lambda: len(uploaded) == 2)
print("11 ok: switching from skip to hold kept the next clips and uploaded them")
service.shutdown()

# 12. A "skip" pause ends by itself too.
service, settings, uploaded, clip = build(upload_pause_minutes=0.01)  # 0.6 s
service.pause_uploads("skip")
clip(0)
assert wait_until(lambda: service.pause_status()["paused"] is False, seconds=4)
clip(1)
assert wait_until(lambda: len(uploaded) == 1)
print("12 ok: the skip pause ended by itself")
service.shutdown()

# 13. An unknown kind of pause is refused.
service, settings, uploaded, clip = build()
try:
    service.pause_uploads("something else")
except ValueError:
    print("13 ok: an unknown kind of pause is refused")
else:
    raise AssertionError("an unknown pause mode must be refused")
service.shutdown()

print("ALL OK")
