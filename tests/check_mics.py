"""
Check of the room microphone part of the backend.

Run on the development machine (it needs ffmpeg with the Opus encoder):

    uv run python tests/check_mics.py

It starts the real receiver, recorder and store in a temporary folder,
a small web server with only the microphone addresses, and stand-in
modules from tests/fake_mic_module.py. Nothing on the Pi is touched and
no real module is needed. It takes about a minute, because sound is
sent at the speed of a real microphone.

The checks: every address is behind the microphone passphrase; a module
that calls is added, stored as Opus files cut on the clock, and its
health is shown; sound the module could not send becomes silence of
the same length, and a long hole ends the file; callers that are not
modules are refused; the same module calling twice replaces itself;
switching a module off stops the storing but not the connection;
removing one deletes its sound; a browser can listen live and gets the
sound as it arrives; the stored sound can be downloaded as MP3 or Opus
for any stretch of time, louder when asked; the age, size and give-way
rules delete
the oldest sound first and never a file being written; the main switch
closes the port; a busy port and a damaged settings file do not stop
anything; shutting down finishes the last file.

To try the page against this stand-in on the Mac (modules call port
3334, the page's addresses are on the port given):

    uv run python tests/check_mics.py --serve 8011
"""

import http.client
import json
import logging
import os
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from urllib.parse import quote
from zoneinfo import ZoneInfo

import uvicorn
from fastapi import FastAPI

from fake_mic_module import FakeModule, tone_frames

from home_automation.api.routes import mics
from home_automation.services import mic_download as download_module
from home_automation.services import mic_receiver_service as receiver_module
from home_automation.services import passphrase_service as passphrase_module
from home_automation.services.mic_receiver_service import MicReceiverService
from home_automation.services.mic_settings_service import MicSettingsService
from home_automation.services.mic_store_service import (
    MicStoreService,
    opus_seconds,
)
from home_automation.services.passphrase_service import PassphraseService


logging.getLogger("home_automation").setLevel(logging.CRITICAL)

LOCAL_TIME_ZONE = ZoneInfo("Asia/Kolkata")
MEGABYTE = 1024 * 1024

API_PORT = 8013
MODULE_PORT = 3399
SEGMENT_SECONDS = 2

failures = 0


def check(name: str, condition: bool, detail: str = "") -> None:
    global failures

    if condition:
        print(f"ok    {name}")
    else:
        failures += 1
        print(f"FAIL  {name}  {detail}")


def wait_until(condition, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout

    while time.monotonic() < deadline:
        if condition():
            return True

        time.sleep(0.1)

    return bool(condition())


class Backend:
    """The microphone services and their addresses, in one folder."""

    def __init__(
        self,
        folder: Path,
        module_port: int,
        segment_seconds: int = 60,
        host: str = "127.0.0.1",
    ) -> None:
        self.folder = folder
        self.storage = folder / "mics"
        self.passphrase_file = folder / "mic_passphrase.json"
        self.settings_file = folder / "mics.json"

        # What the store is told about free RAM. Plenty by default.
        self.free_bytes = 10_000 * MEGABYTE

        self.settings = MicSettingsService(self.settings_file)
        self.passphrases = PassphraseService(
            self.passphrase_file,
            label="Microphone",
        )
        self.receiver = MicReceiverService(
            self.settings,
            self.storage,
            module_port,
            host=host,
            segment_seconds=segment_seconds,
        )
        self.store = MicStoreService(
            self.settings,
            self.storage,
            self.receiver.files_in_use,
            lambda: 250,
            free_bytes=lambda: self.free_bytes,
        )

        self.app = FastAPI()
        self.app.state.mic_settings_service = self.settings
        self.app.state.mic_passphrase_service = self.passphrases
        self.app.state.mic_receiver_service = self.receiver
        self.app.state.mic_store_service = self.store
        self.app.include_router(mics.router)


def start_api(app: FastAPI, port: int) -> uvicorn.Server:
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    )
    threading.Thread(target=server.run, daemon=True).start()

    while not server.started:
        time.sleep(0.05)

    return server


def call(
    method: str,
    path: str,
    passphrase: str | None = None,
    body: dict | None = None,
    header: str = "X-Mics-Passphrase",
) -> tuple[int, dict | list | None]:
    headers = {}

    if passphrase is not None:
        headers[header] = quote(passphrase, safe="")

    data = None

    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"

    request = urllib.request.Request(
        f"http://127.0.0.1:{API_PORT}{path}",
        data=data,
        headers=headers,
        method=method,
    )

    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return response.status, json.loads(response.read() or b"null")
    except urllib.error.HTTPError as error:
        try:
            return error.code, json.loads(error.read() or b"null")
        except ValueError:
            return error.code, None


def fetch(
    path: str,
    passphrase: str | None = None,
) -> tuple[int, dict, bytes]:
    """A whole answer that is not JSON: its code, headers and content."""

    headers = {}

    if passphrase is not None:
        headers["X-Mics-Passphrase"] = quote(passphrase, safe="")

    request = urllib.request.Request(
        f"http://127.0.0.1:{API_PORT}{path}",
        headers=headers,
    )

    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status, dict(response.headers), response.read()
    except urllib.error.HTTPError as error:
        return error.code, dict(error.headers), error.read()


def open_live(path: str, passphrase: str):
    """Start listening live, as the page does; close the connection to stop."""

    connection = http.client.HTTPConnection("127.0.0.1", API_PORT, timeout=10)
    connection.request(
        "GET",
        path,
        headers={"X-Mics-Passphrase": quote(passphrase, safe="")},
    )

    return connection, connection.getresponse()


def loudness(path: Path) -> float:
    """Mean volume of a sound file in dB (0 is the loudest possible)."""

    result = subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-i", str(path),
            "-af", "volumedetect", "-f", "null", "-",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    for line in result.stderr.splitlines():
        if "mean_volume:" in line:
            return float(line.split("mean_volume:")[1].split("dB")[0])

    return -999.0


def duration(path: Path) -> float:
    """Length of a sound file in seconds, 0 when it does not play."""

    result = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "csv=p=0", str(path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    try:
        return float(result.stdout.strip())
    except ValueError:
        return 0.0


def codec(path: Path) -> str:
    result = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "stream=codec_name",
            "-of", "csv=p=0", str(path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    return result.stdout.strip()


def stream_in_background(module: FakeModule, seconds: float) -> threading.Thread:
    def run() -> None:
        try:
            module.stream(tone_frames(), seconds)
        except OSError:
            # The backend hung up; some checks want exactly that.
            pass

    thread = threading.Thread(target=run, daemon=True)
    thread.start()

    return thread


def module_status(passphrase: str, module_id: str) -> dict:
    _, body = call("GET", "/api/mics/status", passphrase=passphrase)

    for module in (body or {}).get("modules", []):
        if module["id"] == module_id:
            return module

    return {}


def make_file(folder: Path, name: str, megabytes: float, age_seconds: float) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_bytes(b"\0" * int(megabytes * MEGABYTE))
    moment = time.time() - age_seconds
    os.utime(path, (moment, moment))

    return path


def name_for(age_seconds: float) -> str:
    moment = datetime.fromtimestamp(time.time() - age_seconds, LOCAL_TIME_ZONE)

    return moment.strftime("%Y%m%d_%H%M%S") + ".opus"


# ----------------------------------------------------------------------
# The checks
# ----------------------------------------------------------------------

def check_passphrase(backend: Backend, good: str) -> None:
    base = "/api/mics"

    code, body = call("GET", f"{base}/passphrase")
    check("passphrase not set at first", code == 200 and body == {"set": False})

    code, _ = call("GET", f"{base}/status")
    check("status refused before one is set", code == 403, str(code))

    code, body = call("POST", f"{base}/passphrase", body={"passphrase": good})
    check("first visitor sets it", code == 200 and body == {"set": True}, str(code))

    code, _ = call("POST", f"{base}/passphrase", body={"passphrase": "another"})
    check("setting it a second time is refused", code == 409, str(code))

    text = backend.passphrase_file.read_text(encoding="utf-8")
    check("the file does not hold the passphrase", good not in text)
    mode = stat.S_IMODE(backend.passphrase_file.stat().st_mode)
    check("the file is private (0600)", mode == 0o600, oct(mode))

    guarded = [
        ("GET", f"{base}/status", None),
        ("GET", f"{base}/settings", None),
        (
            "PUT",
            f"{base}/settings",
            {
                "enabled": False,
                "keep_minutes": 1,
                "ram_limit_mb": 5,
                "opus_bitrate_kbps": 8,
            },
        ),
        ("PUT", f"{base}/modules/esp32-mic-test", {"name": "x", "enabled": False}),
        ("DELETE", f"{base}/modules/esp32-mic-test", None),
        ("POST", f"{base}/passphrase/check", None),
    ]

    for method, path, payload in guarded:
        code, _ = call(method, path, body=payload)
        check(f"no passphrase: {method} {path}", code == 401, str(code))

        code, _ = call(method, path, passphrase="wrong one", body=payload)
        check(f"wrong passphrase: {method} {path}", code == 401, str(code))

    code, _ = call(
        "GET",
        f"{base}/status",
        passphrase=good,
        header="X-Automations-Passphrase",
    )
    check("the automation header does not open the microphones", code == 401, str(code))

    code, body = call("GET", f"{base}/settings", passphrase=good)
    check(
        "the refused saves changed nothing",
        code == 200 and body["enabled"] is True and body["keep_minutes"] == 120,
        str(body),
    )

    code, body = call("GET", f"{base}/status", passphrase=good)
    check(
        "status with the right passphrase: listening, no modules yet",
        code == 200 and body["listening"] is True and body["modules"] == [],
        str(body),
    )


def check_receiving(backend: Backend, good: str) -> None:
    name = "esp32-mic-a1b2"
    folder = backend.storage / name

    module = FakeModule("127.0.0.1", MODULE_PORT, name, version="fake-7", mics=2)
    module.connect()
    started = time.time()
    module.stream(tone_frames(), 5)

    status = module_status(good, name)
    check("a module that calls is added to the list", bool(status), "not in status")
    check("...switched on, with no room name yet", status.get("enabled") is True and status.get("name") == "")
    check("...and shown as connected", status.get("connected") is True)
    check("its firmware version is shown", status.get("firmware_version") == "fake-7", str(status.get("firmware_version")))
    check("its health is shown", status.get("health", {}).get("wifi_signal") == "-61", str(status.get("health")))
    check("its sound is being stored", status.get("recording") is True, str(status.get("recorder_error")))
    check("no sound counted as lost", status.get("frames_lost") == 0, str(status.get("frames_lost")))

    saved = json.loads(backend.settings_file.read_text(encoding="utf-8"))
    check(
        "the module is in runtime/mics.json with the time it was first seen",
        len(saved["modules"]) == 1
        and saved["modules"][0]["id"] == name
        and saved["modules"][0]["first_seen_at"] != "",
        str(saved["modules"]),
    )

    in_use = backend.receiver.files_in_use()
    check("the file being written is known", len(in_use) == 1 and next(iter(in_use)).parent == folder, str(in_use))

    module.close()
    check(
        "after it hangs up it is shown as not connected",
        wait_until(lambda: module_status(good, name).get("connected") is False),
    )

    files = sorted(folder.glob("*.opus"))
    check("the sound was cut into several files", len(files) >= 2, str(len(files)))
    check("every file is Opus", all(codec(path) == "opus" for path in files))

    total = sum(duration(path) for path in files)
    check("together they hold the 5 seconds that were sent", 4.6 <= total <= 5.4, f"{total:.2f} s")

    first = datetime.strptime(files[0].stem, "%Y%m%d_%H%M%S").replace(tzinfo=LOCAL_TIME_ZONE)
    check(
        "the first file is named by its start, in India time",
        abs(first.timestamp() - started) <= 1.5,
        f"{files[0].name} against {datetime.fromtimestamp(started, LOCAL_TIME_ZONE):%H%M%S}",
    )

    later = [
        datetime.strptime(path.stem, "%Y%m%d_%H%M%S").second % SEGMENT_SECONDS
        for path in files[1:]
    ]
    check("the following files start on the clock", all(value == 0 for value in later), str(later))

    code, body = call("GET", "/api/mics/status", passphrase=good)
    stored = body["modules"][0]["stored"]
    check("the page is told what is stored for it", stored is not None and stored["files"] == len(files), str(stored))

    worst = max(abs(opus_seconds(path) - duration(path)) for path in files)
    check("a file's length is read right from the file itself", worst < 0.05, f"{worst:.3f} s off")

    stretches = stored["stretches"]
    check(
        "the page is told it is one unbroken stretch of 5 seconds",
        len(stretches) == 1 and 4.6 <= stretches[0]["end"] - stretches[0]["start"] <= 5.4,
        str(stretches),
    )
    check("...that began when the module began", abs(stretches[0]["start"] - started) <= 1.5, str(stretches))


def check_live(backend: Backend, good: str) -> None:
    name = "esp32-mic-a1b2"
    path = f"/api/mics/modules/{name}/live"

    code, _, _ = fetch(path)
    check("live listening needs the passphrase", code == 401, str(code))

    code, _, _ = fetch("/api/mics/modules/esp32-mic-none/live", good)
    check("live listening to an unknown module is refused", code == 404, str(code))

    time.sleep(1.1)
    module = FakeModule("127.0.0.1", MODULE_PORT, name)
    module.connect()
    thread = stream_in_background(module, 30)
    wait_until(lambda: module_status(good, name).get("recording") is True)

    connection, response = open_live(path, good)

    started = time.monotonic()
    received = b""

    while time.monotonic() - started < 2.0:
        received += response.read(512)

    seconds = len(received) / 2 / 16000
    check("a live listener gets the sound as fast as it is made", 1.7 <= seconds <= 2.6, f"{seconds:.2f} s of sound in 2 s")

    samples = memoryview(received[: len(received) // 2 * 2]).cast("h")
    peak = max(max(samples), -min(samples))
    check("...and it is the module's sound, untouched", 2900 <= peak <= 3000, str(peak))

    _, status = call("GET", "/api/mics/status", passphrase=good)
    check("the page is told someone is listening", status["live_listeners"] == [name], str(status["live_listeners"]))

    listeners = [backend.receiver.open_live(name) for _ in range(2)]

    try:
        backend.receiver.open_live(name)
        refused = False
    except receiver_module.LiveUnavailableError:
        refused = True

    check("a fourth listener at once is refused", refused)

    for listener in listeners:
        backend.receiver.close_live(listener)

    connection.close()
    check(
        "when the browser goes, the listening ends by itself",
        wait_until(lambda: backend.receiver.status()["live_listeners"] == [], 6),
        str(backend.receiver.status()["live_listeners"]),
    )

    connection, response = open_live(path, good)
    response.read(512)

    call("PUT", f"/api/mics/modules/{name}", passphrase=good, body={"name": "", "enabled": False})
    check(
        "switching the module off ends the listening",
        wait_until(lambda: backend.receiver.status()["live_listeners"] == [], 4),
    )
    connection.close()

    code, _, _ = fetch(path, good)
    check("a module that is off cannot be listened to", code == 409, str(code))

    call("PUT", f"/api/mics/modules/{name}", passphrase=good, body={"name": "", "enabled": True})

    module.close()
    thread.join(timeout=5)
    wait_until(lambda: module_status(good, name).get("connected") is False)


def check_download(backend: Backend, good: str, folder: Path) -> None:
    name = "esp32-mic-a1b2"
    base = f"/api/mics/modules/{name}/download"

    stretches = module_status(good, name)["stored"]["stretches"]
    first = stretches[0]                    # the 5 seconds of the first check
    start = first["start"] + 1
    end = first["start"] + 4
    window = f"start={start}&end={end}"

    code, _, _ = fetch(f"{base}?{window}")
    check("a download needs the passphrase", code == 401, str(code))

    code, headers, content = fetch(f"{base}?{window}", good)
    mp3 = folder / "download.mp3"
    mp3.write_bytes(content)
    check("a stretch of stored sound can be downloaded", code == 200, str(code))
    check("...as MP3 unless asked otherwise", codec(mp3) == "mp3" and headers.get("content-type") == "audio/mpeg", codec(mp3))
    check("...3 seconds were asked for and 3 seconds came", 2.7 <= duration(mp3) <= 3.3, f"{duration(mp3):.2f} s")

    stamp = datetime.fromtimestamp(start, LOCAL_TIME_ZONE).strftime("%Y%m%d_%H%M%S")
    check(
        "...named by the module and the start in India time",
        headers.get("content-disposition") == f'attachment; filename="{name}_{stamp}.mp3"',
        str(headers.get("content-disposition")),
    )

    code, headers, content = fetch(f"{base}?{window}&format=opus", good)
    opus = folder / "download.opus"
    opus.write_bytes(content)
    check("the stored Opus itself can be downloaded", code == 200 and codec(opus) == "opus", f"{code} {codec(opus)}")
    check("...also cut to the time asked for", 2.7 <= duration(opus) <= 3.3, f"{duration(opus):.2f} s")

    code, _, content = fetch(f"{base}?{window}&level=false", good)
    plain = folder / "download_plain.mp3"
    plain.write_bytes(content)
    check(
        "\"level the volume\" makes the download louder",
        code == 200 and loudness(mp3) > loudness(plain) + 6,
        f"{loudness(mp3):.1f} dB against {loudness(plain):.1f} dB",
    )

    # From before the first sound to now: everything stored, with the
    # holes between the stretches left out.
    stored_seconds = sum(stretch["end"] - stretch["start"] for stretch in stretches)
    code, headers, content = fetch(f"{base}?start={first['start'] - 60}&end={time.time() + 60}&format=opus", good)
    whole = folder / "download_all.opus"
    whole.write_bytes(content)
    check(
        "all of it at once: every stretch joined, the holes left out",
        code == 200 and abs(duration(whole) - stored_seconds) <= 0.5,
        f"{duration(whole):.2f} s against {stored_seconds:.2f} s stored",
    )
    stamp = datetime.fromtimestamp(first["start"], LOCAL_TIME_ZONE).strftime("%Y%m%d_%H%M%S")
    check("...named by the first sound it holds", stamp in str(headers.get("content-disposition")), str(headers.get("content-disposition")))

    code, _, _ = fetch(f"{base}?start={first['start'] - 7200}&end={first['start'] - 3600}", good)
    check("a time with no stored sound is refused", code == 404, str(code))

    code, _, _ = fetch(f"{base}?start={end}&end={start}", good)
    check("an end before the start is refused", code == 422, str(code))

    code, _, _ = fetch(f"/api/mics/modules/esp32-mic-none/download?{window}", good)
    check("a download from an unknown module is refused", code == 404, str(code))

    download_module._one_at_a_time.acquire()
    code, _, _ = fetch(f"{base}?{window}", good)
    download_module._one_at_a_time.release()
    check("a second download at the same time is refused", code == 409, str(code))

    code, _, _ = fetch(f"{base}?{window}", good)
    check("...and the next one after it works", code == 200, str(code))


def check_lost_sound(backend: Backend, good: str) -> None:
    name = "esp32-mic-a1b2"
    folder = backend.storage / name

    # A file is named by the second it starts in. Calling again within
    # the same second as the last file began would write over that
    # file, and the sums below would come out short.
    time.sleep(1.1)
    before = set(folder.glob("*.opus"))

    module = FakeModule("127.0.0.1", MODULE_PORT, name)
    module.connect()
    module.stream(tone_frames(), 2)
    module.skip(62)                         # about one second not sent
    module.stream(tone_frames(), 2)

    lost = module_status(good, name).get("frames_lost")
    check("sound the module could not send is counted", lost == 62, str(lost))

    module.close()
    wait_until(lambda: module_status(good, name).get("connected") is False)

    new_files = sorted(set(folder.glob("*.opus")) - before)
    total = sum(duration(path) for path in new_files)
    check(
        "...and filled with silence, so 4 s sent with 1 s lost is 5 s stored",
        4.6 <= total <= 5.4,
        f"{total:.2f} s",
    )

    time.sleep(1.1)
    before = set(folder.glob("*.opus"))

    module = FakeModule("127.0.0.1", MODULE_PORT, name)
    module.connect()
    module.stream(tone_frames(), 1.5)
    module.skip(100)                        # 1.6 seconds not sent: over the limit set for this check
    module.stream(tone_frames(), 1.5)
    module.close()
    wait_until(lambda: module_status(good, name).get("connected") is False)

    new_files = sorted(set(folder.glob("*.opus")) - before)
    total = sum(duration(path) for path in new_files)
    check(
        "a long hole is not filled: the file ends and a new one starts",
        1.5 <= total <= 4.0,
        f"{total:.2f} s",
    )


def check_refusals(backend: Backend, good: str) -> None:
    def refused(label: str, module: FakeModule) -> None:
        check(label, module.is_closed_by_other_side(4), "still connected")
        module.close()

    module = FakeModule("127.0.0.1", MODULE_PORT, "Bad Name!")
    module.connect()
    refused("a caller with an unusable name is refused", module)

    module = FakeModule("127.0.0.1", MODULE_PORT, "esp32-mic-slow")
    module.connect(hello=False)
    module.send_hello(rate=8000)
    refused("a module with another sample rate is refused", module)

    module = FakeModule("127.0.0.1", MODULE_PORT, "esp32-mic-web")
    module.connect(hello=False)
    module.send_raw(b"GET / HTTP/1.1\r\nHost: pi\r\n\r\n")
    refused("a caller that is not a module is refused", module)

    module = FakeModule("127.0.0.1", MODULE_PORT, "esp32-mic-mute")
    module.connect(hello=False)
    refused("a caller that never says who it is is hung up on", module)

    code, body = call("GET", "/api/mics/settings", passphrase=good)
    ids = [entry["id"] for entry in body["modules"]]
    check("none of them was added to the list", ids == ["esp32-mic-a1b2"], str(ids))

    module = FakeModule("127.0.0.1", MODULE_PORT, "esp32-mic-c3d4")
    module.connect()
    module.stream(tone_frames(), 0.5)
    refused("a module that falls silent is hung up on", module)
    check(
        "...and shown as not connected",
        wait_until(lambda: module_status(good, "esp32-mic-c3d4").get("connected") is False),
    )


def check_same_module_twice(backend: Backend, good: str) -> None:
    name = "esp32-mic-c3d4"

    first = FakeModule("127.0.0.1", MODULE_PORT, name, version="first")
    first.connect()
    first_thread = stream_in_background(first, 30)
    time.sleep(1.0)

    second = FakeModule("127.0.0.1", MODULE_PORT, name, version="second")
    second.connect()
    second_thread = stream_in_background(second, 30)

    first_thread.join(timeout=8)
    check("the same module calling again ends its old connection", not first_thread.is_alive())
    check(
        "...and the new one is the one shown",
        wait_until(lambda: module_status(good, name).get("firmware_version") == "second"),
        str(module_status(good, name).get("firmware_version")),
    )

    return second, second_thread


def check_switch_and_remove(backend: Backend, good: str, module: FakeModule, thread: threading.Thread) -> None:
    name = module.name
    folder = backend.storage / name
    path = f"/api/mics/modules/{name}"

    check("it is storing", wait_until(lambda: module_status(good, name).get("recording") is True))

    code, _ = call("PUT", path, passphrase=good, body={"name": "  Hall ", "enabled": False})
    check("a module can be named and switched off", code == 200, str(code))

    status = module_status(good, name)
    check("the room name is kept, tidied", status.get("name") == "Hall", str(status.get("name")))
    check("switched off: storing stops", wait_until(lambda: module_status(good, name).get("recording") is False))
    check("...but it stays connected", module_status(good, name).get("connected") is True)

    # ffmpeg may still be finishing its last file for a moment.
    wait_until(lambda: not backend.receiver.files_in_use())
    time.sleep(0.5)
    count = len(list(folder.glob("*.opus")))
    time.sleep(2 * SEGMENT_SECONDS + 0.5)
    check("...and no new file appears", len(list(folder.glob("*.opus"))) == count)

    code, _ = call("PUT", path, passphrase=good, body={"name": "Hall", "enabled": True})
    check("switched on again: storing starts again", wait_until(lambda: module_status(good, name).get("recording") is True))

    code, _ = call("PUT", "/api/mics/modules/esp32-mic-none", passphrase=good, body={"name": "x", "enabled": True})
    check("an unknown module cannot be changed", code == 404, str(code))

    # Taken out of the wall: it stops calling, then it is removed.
    module.close()
    thread.join(timeout=5)
    wait_until(lambda: module_status(good, name).get("connected") is False)
    check("it has stored sound", len(list(folder.glob("*.opus"))) > 0)

    code, body = call("DELETE", path, passphrase=good)
    ids = [entry["id"] for entry in (body or {}).get("modules", [])]
    check("a module can be removed from the list", code == 200 and name not in ids, str(ids))
    check("...and its stored sound is deleted", not folder.exists())

    code, _ = call("DELETE", path, passphrase=good)
    check("removing it twice is refused", code == 404, str(code))


def check_settings(backend: Backend, good: str) -> None:
    base = "/api/mics/settings"

    code, body = call(
        "PUT",
        base,
        passphrase=good,
        body={"enabled": True, "keep_minutes": 90, "ram_limit_mb": 200, "opus_bitrate_kbps": 24},
    )
    check(
        "the general settings can be saved",
        code == 200 and body["keep_minutes"] == 90 and body["ram_limit_mb"] == 200,
        str(code),
    )
    check(
        "...and the module list is left alone by it",
        [entry["id"] for entry in body["modules"]] == ["esp32-mic-a1b2"],
        str(body["modules"]),
    )

    code, _ = call(
        "PUT",
        base,
        passphrase=good,
        body={"enabled": True, "keep_minutes": 90, "ram_limit_mb": 1, "opus_bitrate_kbps": 24},
    )
    check("a limit that makes no sense is refused", code == 422, str(code))

    code, _ = call(
        "PUT",
        base,
        passphrase=good,
        body={"enabled": True, "keep_minutes": 120, "ram_limit_mb": 120, "opus_bitrate_kbps": 32},
    )
    check("back to the defaults", code == 200, str(code))


def check_store_rules(folder: Path) -> None:
    """The age, size and give-way rules, on files made for the purpose."""

    storage = folder / "store_rules"
    settings = MicSettingsService(folder / "store_rules.json")
    in_use: set[Path] = set()
    free = {"bytes": 10_000 * MEGABYTE}

    store = MicStoreService(
        settings,
        storage,
        lambda: set(in_use),
        lambda: 250,
        free_bytes=lambda: free["bytes"],
    )

    hall = storage / "esp32-mic-hall"
    room = storage / "esp32-mic-room"

    # --- age ----------------------------------------------------------
    old = make_file(hall, name_for(3 * 3600), 0.1, 3 * 3600 - 60)
    recent = make_file(hall, name_for(3600), 0.1, 3600 - 60)
    stranger = make_file(storage / "not a module", name_for(9 * 3600), 0.1, 9 * 3600)

    store.clean()
    check("sound older than 2 hours is deleted", not old.exists())
    check("sound from an hour ago is kept", recent.exists())
    check("a folder that is not a module's is never touched", stranger.exists())

    recent.unlink()

    # --- size ---------------------------------------------------------
    current = settings.get()
    current.ram_limit_mb = 5
    settings.save(current)

    files = []

    for index in range(8):
        age = 3000 - index * 300            # oldest first
        owner = hall if index % 2 == 0 else room
        files.append(make_file(owner, name_for(age), 1, age - 60))

    in_use.add(files[0])                    # the oldest is "being written"
    fresh = make_file(room, name_for(1), 1, 0)

    store.clean()

    left = [path for path in files if path.exists()]
    total = sum(path.stat().st_size for path in left) + fresh.stat().st_size
    check("over the limit: sound is deleted down to the limit", total <= 5 * MEGABYTE, f"{total / MEGABYTE:.1f} MB")
    check("...the oldest first", [path.exists() for path in files[1:]] == [False] * 4 + [True] * 3, str([path.exists() for path in files]))
    check("...but never a file being written", files[0].exists())
    check("...nor one written a moment ago", fresh.exists())
    check(
        "...and both modules lose alike",
        abs(len(list(hall.glob("*.opus"))) - len(list(room.glob("*.opus")))) <= 2,
    )

    status = store.status()
    check("the page is told how many were deleted", status["deleted_for_age"] == 1 and status["deleted_for_size"] == 4, str(status))

    # --- giving way to the camera clips ---------------------------------
    in_use.clear()
    remaining = [path for path in files if path.exists()]
    oldest = remaining[0]

    store.give_way_if_ram_short()
    check("with free RAM nothing gives way", all(path.exists() for path in remaining))

    # Free RAM is just under the floor (250 + 50 MB) and each deleted
    # megabyte frees one.
    start_count = len(remaining)
    free_base = 299 * MEGABYTE

    def free_now() -> int:
        gone = start_count - sum(1 for path in remaining if path.exists())
        return free_base + gone * MEGABYTE

    store._free_bytes = free_now
    store.give_way_if_ram_short()

    check("RAM short: the oldest sound gives way", not oldest.exists())
    check(
        "...and only as much as is needed",
        sum(1 for path in remaining if path.exists()) == start_count - 1,
        str(sum(1 for path in remaining if path.exists())),
    )
    check("the page is told it gave way", store.status()["deleted_for_ram"] == 1 and store.status()["last_gave_way_at"] is not None)


def check_main_switch(backend: Backend, good: str) -> None:
    def port_open() -> bool:
        try:
            socket.create_connection(("127.0.0.1", MODULE_PORT), timeout=1).close()
            return True
        except OSError:
            return False

    body = {"enabled": False, "keep_minutes": 120, "ram_limit_mb": 120, "opus_bitrate_kbps": 32}
    call("PUT", "/api/mics/settings", passphrase=good, body=body)
    check("switched off as a whole: the port is closed", wait_until(lambda: not port_open(), 4))

    _, status = call("GET", "/api/mics/status", passphrase=good)
    check("...and the page is told", status["enabled"] is False and status["listening"] is False, str(status["listening"]))

    body["enabled"] = True
    call("PUT", "/api/mics/settings", passphrase=good, body=body)
    check("switched on again: the port is open again", wait_until(port_open, 4))


def check_busy_port_and_damaged_file(folder: Path) -> None:
    other = Backend(folder / "second", MODULE_PORT)
    other.receiver.start()

    check(
        "a port that is taken does not stop anything; it is reported",
        wait_until(lambda: other.receiver.status()["last_error"] is not None, 4)
        and other.receiver.status()["listening"] is False,
        str(other.receiver.status()["last_error"]),
    )
    other.receiver.stop()

    damaged = folder / "damaged.json"
    damaged.write_text("{not json", encoding="utf-8")
    settings = MicSettingsService(damaged)
    check(
        "a damaged settings file is put aside and the defaults are used",
        settings.get().ram_limit_mb == 120 and damaged.with_suffix(".damaged").exists(),
    )


def check_shutdown(backend: Backend, good: str) -> None:
    name = "esp32-mic-a1b2"
    folder = backend.storage / name

    module = FakeModule("127.0.0.1", MODULE_PORT, name)
    module.connect()
    thread = stream_in_background(module, 30)
    wait_until(lambda: module_status(good, name).get("recording") is True)
    time.sleep(1.0)

    started = time.monotonic()
    backend.receiver.stop()
    backend.store.stop()
    took = time.monotonic() - started

    check("shutting down is quick", took < 8, f"{took:.1f} s")

    newest = max(folder.glob("*.opus"), key=lambda path: path.stat().st_mtime)
    check("the last file was finished and plays", duration(newest) > 0, newest.name)

    left = subprocess.run(
        ["pgrep", "-f", str(backend.storage)],
        capture_output=True,
        text=True,
        check=False,
    ).stdout.split()
    check("no ffmpeg is left running", left == [], str(left))

    module.close()
    thread.join(timeout=5)


def run_checks() -> None:
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        raise SystemExit("ffmpeg and ffprobe are needed for this check.")

    # The real waits are longer than a check should take.
    passphrase_module.WRONG_PASSPHRASE_DELAY_SECONDS = 0.05
    receiver_module.HELLO_TIMEOUT_SECONDS = 2
    receiver_module.SILENCE_TIMEOUT_SECONDS = 2
    # Really 30 seconds; a hole longer than this ends the file.
    receiver_module.MAX_SILENCE_FILL_SECONDS = 1

    folder = Path(tempfile.mkdtemp(prefix="mics_check_"))

    try:
        backend = Backend(folder, MODULE_PORT, segment_seconds=SEGMENT_SECONDS)
        backend.receiver.start()
        server = start_api(backend.app, API_PORT)
        wait_until(lambda: backend.receiver.status()["listening"], 4)

        good = "kamre ki awaaz 42 %&+"

        check_passphrase(backend, good)
        check_receiving(backend, good)
        check_lost_sound(backend, good)
        check_live(backend, good)
        check_download(backend, good, folder)
        check_refusals(backend, good)
        module, thread = check_same_module_twice(backend, good)
        check_switch_and_remove(backend, good, module, thread)
        check_settings(backend, good)
        check_store_rules(folder)
        check_main_switch(backend, good)
        check_busy_port_and_damaged_file(folder)
        check_shutdown(backend, good)

        server.should_exit = True
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def serve(port: int) -> None:
    folder = Path(tempfile.mkdtemp(prefix="mics_demo_"))
    backend = Backend(folder, 3334, host="0.0.0.0")
    backend.receiver.start()
    backend.store.start()

    print(f"Stand-in backend on http://127.0.0.1:{port}")
    print("Modules call port 3334, for example:")
    print("  uv run python tests/fake_mic_module.py")
    print(f"Sound is stored under: {backend.storage}")

    try:
        uvicorn.run(backend.app, host="127.0.0.1", port=port, log_level="warning")
    finally:
        backend.receiver.stop()
        backend.store.stop()
        shutil.rmtree(folder, ignore_errors=True)


if __name__ == "__main__":
    if "--serve" in sys.argv:
        serve(int(sys.argv[sys.argv.index("--serve") + 1]))
    else:
        run_checks()

        print()

        if failures:
            print(f"{failures} check(s) FAILED")
            sys.exit(1)

        print("all checks passed")
