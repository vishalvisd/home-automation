from datetime import datetime
from zoneinfo import ZoneInfo

from home_automation.config.camera_settings import CameraConfig


LOCAL_TIME_ZONE = ZoneInfo("Asia/Kolkata")


def clip_key(camera: CameraConfig, closed_at: datetime, suffix: str) -> str:
    """
    camN/YYYY/MM/DD/HH/cam_N_YYYY_MM_DD_HH_MM_SS.<ext>

    The same name is used for the object in Backblaze and for the file
    on the archive disk, so the downloader can match them. closed_at is
    the moment the clip was finished, in Asia/Kolkata. Another project
    reads these names; do not change the layout casually.
    """

    timestamp = closed_at.astimezone(LOCAL_TIME_ZONE)
    camera_number = camera.key.removeprefix("cam")

    return (
        f"{camera.key}/"
        f"{timestamp:%Y/%m/%d/%H}/"
        f"cam_{camera_number}_{timestamp:%Y_%m_%d_%H_%M_%S}"
        f"{suffix}"
    )
