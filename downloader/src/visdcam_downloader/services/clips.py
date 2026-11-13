"""
Clip naming as produced by the Pi:

    cam3/2026/11/13/17/cam_3_2026_11_13_17_05_00.mp4
    cam1/2026/11/13/17/cam_1_2026_11_13_17_05_00.ts

Important: the time in the name is when the clip was CLOSED (file
modification time at upload), not when it started. A clip therefore
covers roughly [name_time - segment_seconds, name_time].
"""

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo


CLIP_KEY_PATTERN = re.compile(
    r"^(?P<camera>cam\d+)/"
    r"(?P<y>\d{4})/(?P<m>\d{2})/(?P<d>\d{2})/(?P<h>\d{2})/"
    r"cam_\d+_(?P<fy>\d{4})_(?P<fm>\d{2})_(?P<fd>\d{2})_"
    r"(?P<fh>\d{2})_(?P<fmi>\d{2})_(?P<fs>\d{2})"
    r"\.(?P<ext>ts|mp4)$"
)


@dataclass(frozen=True, slots=True)
class Clip:
    camera: str
    key: str
    size: int
    end_time: datetime
    segment_seconds: int

    @property
    def start_time(self) -> datetime:
        return self.end_time - timedelta(seconds=self.segment_seconds)

    @property
    def extension(self) -> str:
        return self.key.rsplit(".", 1)[-1]

    @property
    def filename(self) -> str:
        return self.key.rsplit("/", 1)[-1]

    def overlaps(self, start: datetime, end: datetime) -> bool:
        return self.start_time < end and self.end_time > start

    def to_dict(self) -> dict:
        return {
            "camera": self.camera,
            "key": self.key,
            "filename": self.filename,
            "size": self.size,
            "extension": self.extension,
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat(),
        }


def parse_clip(
    key: str,
    size: int,
    timezone: ZoneInfo,
    segment_seconds: int,
) -> Clip | None:
    match = CLIP_KEY_PATTERN.match(key)

    if match is None:
        return None

    end_time = datetime(
        int(match["fy"]),
        int(match["fm"]),
        int(match["fd"]),
        int(match["fh"]),
        int(match["fmi"]),
        int(match["fs"]),
        tzinfo=timezone,
    )

    return Clip(
        camera=match["camera"],
        key=key,
        size=size,
        end_time=end_time,
        segment_seconds=segment_seconds,
    )


def hour_prefixes(
    camera: str,
    start: datetime,
    end: datetime,
    segment_seconds: int,
) -> list[str]:
    """
    Bucket folders that can hold clips overlapping [start, end).

    A clip overlapping the window has its END time between start and
    end + segment, so those are the hours to list.
    """

    first = start.replace(minute=0, second=0, microsecond=0)
    last = end + timedelta(seconds=segment_seconds)

    prefixes: list[str] = []
    current = first

    while current <= last:
        prefixes.append(
            f"{camera}/{current:%Y/%m/%d/%H}/"
        )
        current += timedelta(hours=1)

    return prefixes


def select_clips(
    clips: list[Clip],
    start: datetime,
    end: datetime,
) -> list[Clip]:
    chosen = [clip for clip in clips if clip.overlaps(start, end)]
    chosen.sort(key=lambda clip: clip.end_time)
    return chosen


def output_name(
    camera: str,
    start: datetime,
    duration_seconds: int,
    extension: str,
) -> str:
    minutes = max(1, round(duration_seconds / 60))
    return f"{camera}_{start:%Y-%m-%d_%H-%M-%S}_{minutes}min.{extension}"
