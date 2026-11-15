from typing import Literal

from pydantic import BaseModel, Field, model_validator


# "esp32_mjpeg": ESP32-CAM serving MJPEG over HTTP. Frames are pulled with
#                GStreamer and software-encoded to H.264 on the Pi.
# "rtsp":        Commercial IP camera serving H.264/H.265 over RTSP. ffmpeg
#                copies the video as-is; only audio is converted to AAC.
CameraSourceType = Literal["esp32_mjpeg", "rtsp"]


class CameraConfig(BaseModel):
    key: str
    name: str

    enabled: bool = True

    source_type: CameraSourceType = "esp32_mjpeg"

    # ESP32-CAM fields. Ignored for RTSP cameras.
    host: str = ""
    stream_path: str = "/stream"
    control_port: int = Field(default=8080, ge=1, le=65535)

    # RTSP field. Full URL, including username:password if the camera
    # needs them, for example rtsp://admin:@192.168.1.18:554/ch0_0.264
    # Ignored for ESP32-CAM cameras.
    stream_url: str = ""

    # RTSP field, optional. The camera's smaller sub stream, used only
    # for live view in the browser (go2rtc). When empty, live view uses
    # stream_url. Ignored for ESP32-CAM cameras.
    live_stream_url: str = ""

    @model_validator(mode="after")
    def validate_source_fields(self) -> "CameraConfig":
        if self.source_type == "esp32_mjpeg":
            if not self.host.strip():
                raise ValueError(
                    f"{self.name}: an ESP32-CAM needs an IP address / host"
                )

        if self.source_type == "rtsp":
            if not self.stream_url.strip().lower().startswith("rtsp://"):
                raise ValueError(
                    f"{self.name}: the stream URL must start with rtsp://"
                )

            live_url = self.live_stream_url.strip()
            if live_url and not live_url.lower().startswith("rtsp://"):
                raise ValueError(
                    f"{self.name}: the live view stream URL must start "
                    "with rtsp://"
                )

        return self


class CameraSettings(BaseModel):
    """Persistent configuration for the CCTV subsystem."""

    # Recording starts disabled until we test the new recorder.
    recording_enabled: bool = False

    segment_seconds: int = Field(default=180, ge=10)

    # ESP32-CAM only. RTSP cameras are stream-copied, so the camera
    # itself decides frame rate and bitrate.
    frame_rate: int = Field(default=15, ge=1)
    video_bitrate_kbps: int = Field(default=1000, ge=100)

    # RAM-backed temporary recording storage. Deliberate: it keeps
    # continuous CCTV writes off the SD card.
    recording_directory: str = (
        "/dev/shm/home-automation/cameras"
    )

    # Camera mode automation (ESP32-CAM only).
    day_mode_time: str = "06:00"
    night_mode_time: str = "18:00"

    # Health monitoring.
    health_check_seconds: int = Field(default=30, ge=5)
    restart_after_failures: int = Field(default=3, ge=1)

    # Recorder recovery
    recorder_restart_delay_seconds: int = Field(
        default=10,
        ge=1,
    )

    # RAM guard. Segments waiting for upload per camera. When a new
    # segment closes and this many are already waiting, the oldest
    # waiting segment is deleted without being uploaded.
    pending_upload_limit: int = Field(default=3, ge=1)

    # Backblaze B2 upload. Accounts and buckets live in
    # runtime/backblaze_credentials.json; uploads rotate between the
    # enabled accounts, one account per calendar day.
    b2_upload_enabled: bool = False

    # Upload speed limit in kilobytes per second, shared by every
    # upload in progress. (The old b2_upload_rate_kbps applied per
    # upload, so three cameras used three times the number.)
    b2_upload_rate_kb_s: int = Field(
        default=750,
        ge=1,
    )

    cameras: list[CameraConfig] = [
        CameraConfig(
            key="cam1",
            name="Camera 1",
            host="192.168.1.33",
        ),
        CameraConfig(
            key="cam2",
            name="Camera 2",
            host="192.168.1.36",
        ),
    ]
