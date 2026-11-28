"""
How a room microphone module talks to the Pi.

The module calls the Pi on one TCP port and only ever sends; the Pi
sends nothing back. Everything travels in frames:

    2 bytes   0xA5 0x5A, the same in every frame
    1 byte    kind: 1 hello, 2 sound, 3 health
    2 bytes   length of what follows, low byte first
    n bytes   the content

hello   Sent once, first. Text lines "key=value": name (the module's
        hardware name), version, build, rate (always 16000), mics.

sound   4 bytes: a counter, low byte first. Then the samples: signed
        16-bit, low byte first, mono, 16000 a second. The counter goes
        up by one for every block of samples the module takes from its
        microphone, also for a block it could not send. So a jump in
        the counter tells the Pi exactly how much sound was lost.

health  Sent every few seconds. Text lines "key=value": uptime (s),
        wifi_signal (dBm), free_memory (bytes), mic_peak (0 to 32767),
        mics, trial (yes or no).

The firmware and tests/fake_mic_module.py speak this; MicReceiverService
listens to it. Change all three together.
"""

import struct
from collections.abc import Callable


MAGIC = b"\xa5\x5a"

FRAME_HELLO = 1
FRAME_AUDIO = 2
FRAME_STATUS = 3

HEADER_BYTES = 5
MAX_PAYLOAD_BYTES = 2048

SAMPLE_RATE = 16000
BYTES_PER_SAMPLE = 2

# What the firmware sends in one sound frame: 16 ms.
SAMPLES_PER_AUDIO_FRAME = 256

SEQUENCE_MODULO = 2**32


class ProtocolError(Exception):
    """The other side sent something that is not this protocol."""


def encode_frame(kind: int, payload: bytes) -> bytes:
    if len(payload) > MAX_PAYLOAD_BYTES:
        raise ValueError("frame content too long")

    return MAGIC + struct.pack("<BH", kind, len(payload)) + payload


def encode_text(kind: int, fields: dict[str, object]) -> bytes:
    lines = [f"{key}={value}" for key, value in fields.items()]

    return encode_frame(kind, "\n".join(lines).encode("utf-8"))


def decode_text(payload: bytes) -> dict[str, str]:
    fields: dict[str, str] = {}

    for line in payload.decode("utf-8", errors="replace").splitlines():
        key, separator, value = line.partition("=")

        if separator and key.strip():
            fields[key.strip()] = value.strip()

    return fields


def encode_audio(sequence: int, pcm: bytes) -> bytes:
    return encode_frame(
        FRAME_AUDIO,
        struct.pack("<I", sequence % SEQUENCE_MODULO) + pcm,
    )


def decode_audio(payload: bytes) -> tuple[int, bytes]:
    if len(payload) < 4 + BYTES_PER_SAMPLE:
        raise ProtocolError("sound frame too short")

    pcm = payload[4:]

    if len(pcm) % BYTES_PER_SAMPLE:
        raise ProtocolError("sound frame holds half a sample")

    return struct.unpack("<I", payload[:4])[0], pcm


def read_frame(read_exactly: Callable[[int], bytes]) -> tuple[int, bytes]:
    """
    Read one frame. read_exactly(n) must return exactly n bytes or
    raise when the connection ends.
    """

    header = read_exactly(HEADER_BYTES)

    if header[:2] != MAGIC:
        raise ProtocolError("not a microphone module")

    kind, length = struct.unpack("<BH", header[2:])

    if length > MAX_PAYLOAD_BYTES:
        raise ProtocolError("frame content too long")

    return kind, read_exactly(length) if length else b""
