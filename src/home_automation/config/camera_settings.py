from pydantic import BaseModel, Field


class CameraConfig(BaseModel):
    key: str
    name: str
    host: str

    enabled: bool = True

    stream_path: str = "/stream"
    control_port: int = Field(default=8080, ge=1, le=65535)


class CameraSettings(BaseModel):
    """Persistent configuration for the CCTV subsystem."""

    # Recording starts disabled until we test the new recorder.
    recording_enabled: bool = False

    segment_seconds: int = Field(default=180, ge=10)
    frame_rate: int = Field(default=15, ge=1)
    video_bitrate_kbps: int = Field(default=1000, ge=100)

    # RAM-backed temporary recording storage.
    recording_directory: str = (
        "/dev/shm/home-automation/cameras"
    )

    # Camera mode automation.
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

    # Backblaze B2 upload
    b2_upload_enabled: bool = False
    b2_region: str = "ca-east-006"
    b2_bucket: str = "visd-cctv"
    b2_upload_rate_kbps: int = Field(
        default=300,
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