"""
A stand-in for a room microphone module.

It calls the backend the way the ESP32 firmware does (the frames are
described in src/home_automation/services/mic_protocol.py) and sends a
steady tone, or a WAV file again and again. Use it to try the
microphone part of the backend without a module, on the Mac or against
the Pi:

    uv run python tests/fake_mic_module.py --host 192.168.1.31

    uv run python tests/fake_mic_module.py --host 192.168.1.31 \
        --name esp32-mic-test --wav some_16khz_mono.wav --seconds 120

Against the Pi it shows up in the module list under its name
(esp32-mic-test unless another is given) and stays there until it is
removed in the page.

tests/check_mics.py uses the FakeModule class from this file.
"""

import argparse
import array
import math
import socket
import sys
import time
import wave
from pathlib import Path

from home_automation.services.mic_protocol import (
    FRAME_HELLO,
    FRAME_STATUS,
    SAMPLE_RATE,
    SAMPLES_PER_AUDIO_FRAME,
    encode_audio,
    encode_text,
)


FRAME_SECONDS = SAMPLES_PER_AUDIO_FRAME / SAMPLE_RATE
STATUS_EVERY_SECONDS = 5


def tone_frames(frequency: float = 440.0, level: int = 3000):
    """An endless tone, one sound frame at a time."""

    position = 0

    while True:
        samples = array.array(
            "h",
            (
                int(
                    level
                    * math.sin(
                        2 * math.pi * frequency * (position + i) / SAMPLE_RATE
                    )
                )
                for i in range(SAMPLES_PER_AUDIO_FRAME)
            ),
        )

        if sys.byteorder == "big":
            samples.byteswap()

        position += SAMPLES_PER_AUDIO_FRAME

        yield samples.tobytes()


def wav_frames(path: Path):
    """A WAV file (16 kHz, 16-bit, mono), repeated without end."""

    with wave.open(str(path), "rb") as source:
        if (
            source.getframerate() != SAMPLE_RATE
            or source.getnchannels() != 1
            or source.getsampwidth() != 2
        ):
            raise SystemExit(f"{path} must be 16 kHz, 16-bit, mono.")

        data = source.readframes(source.getnframes())

    step = SAMPLES_PER_AUDIO_FRAME * 2
    frames = [
        data[start:start + step]
        for start in range(0, len(data) - step + 1, step)
    ]

    if not frames:
        raise SystemExit(f"{path} is shorter than one sound frame.")

    while True:
        yield from frames


class FakeModule:
    def __init__(
        self,
        host: str,
        port: int,
        name: str = "esp32-mic-test",
        version: str = "fake-1",
        mics: int = 1,
    ) -> None:
        self.host = host
        self.port = port
        self.name = name
        self.version = version
        self.mics = mics

        self.sequence = 0
        self._socket: socket.socket | None = None
        self._started = time.monotonic()

    def connect(self, hello: bool = True) -> None:
        self._socket = socket.create_connection(
            (self.host, self.port),
            timeout=5,
        )

        if hello:
            self.send_hello()

    def send_hello(self, **overrides: object) -> None:
        fields: dict[str, object] = {
            "name": self.name,
            "version": self.version,
            "build": f"{self.version} stand-in",
            "rate": SAMPLE_RATE,
            "mics": self.mics,
        }
        fields.update(overrides)

        self.send_raw(encode_text(FRAME_HELLO, fields))

    def send_status(self, mic_peak: int = 3000) -> None:
        self.send_raw(
            encode_text(
                FRAME_STATUS,
                {
                    "uptime": int(time.monotonic() - self._started),
                    "wifi_signal": -61,
                    "free_memory": 215000,
                    "mic_peak": mic_peak,
                    "mics": self.mics,
                    "trial": "no",
                },
            )
        )

    def send_audio(self, pcm: bytes) -> None:
        self.send_raw(encode_audio(self.sequence, pcm))
        self.sequence += 1

    def skip(self, frames: int) -> None:
        """
        Sound the module took from its microphone but could not send.
        The time passes all the same, as it does on a real module.
        """

        self.sequence += frames
        time.sleep(frames * FRAME_SECONDS)

    def send_raw(self, data: bytes) -> None:
        if self._socket is None:
            raise OSError("not connected")

        self._socket.sendall(data)

    def stream(self, frames, seconds: float) -> None:
        """Send sound at the speed of a real microphone."""

        start = time.monotonic()
        sent = 0
        next_status = 0.0

        while True:
            elapsed = time.monotonic() - start

            if elapsed >= seconds:
                return

            if elapsed >= next_status:
                self.send_status()
                next_status += STATUS_EVERY_SECONDS

            self.send_audio(next(frames))
            sent += 1

            time.sleep(
                max(0.0, start + sent * FRAME_SECONDS - time.monotonic())
            )

    def is_closed_by_other_side(self, wait_seconds: float = 3.0) -> bool:
        """True when the backend has hung up on us."""

        assert self._socket is not None, "not connected"
        self._socket.settimeout(wait_seconds)

        try:
            return self._socket.recv(1) == b""
        except TimeoutError:
            return False
        except OSError:
            return True

    def close(self) -> None:
        if self._socket is not None:
            try:
                self._socket.close()
            except OSError:
                pass

            self._socket = None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=3334)
    parser.add_argument("--name", default="esp32-mic-test")
    parser.add_argument("--wav", type=Path, help="16 kHz mono WAV to send")
    parser.add_argument(
        "--seconds",
        type=float,
        default=0,
        help="how long to send; 0 means until Ctrl+C",
    )
    arguments = parser.parse_args()

    frames = wav_frames(arguments.wav) if arguments.wav else tone_frames()
    module = FakeModule(arguments.host, arguments.port, arguments.name)

    try:
        module.connect()
    except OSError as error:
        raise SystemExit(
            f"Could not connect to {arguments.host}:{arguments.port} "
            f"({error})."
        )

    print(
        f"Connected to {arguments.host}:{arguments.port} as "
        f"{arguments.name}. Sending sound; Ctrl+C stops."
    )

    try:
        module.stream(frames, arguments.seconds or float("inf"))
    except KeyboardInterrupt:
        pass
    except OSError as error:
        print(f"The backend closed the connection ({error}).")
    finally:
        module.close()
        print(f"Sent {module.sequence * FRAME_SECONDS:.0f} s of sound.")


if __name__ == "__main__":
    main()
