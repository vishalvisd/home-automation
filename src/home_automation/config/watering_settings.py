from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, Field, field_validator


class WateringSettings(BaseModel):
    """Persistent configuration for panel cleaning and plant watering."""

    # Scheduling
    enabled: bool = False
    run_time: str = "19:00"
    frequency_days: int = Field(default=1, ge=1)
    timezone: str = "Asia/Kolkata"

    # Valve timing
    main_valve_open_delay_seconds: int = Field(default=30, ge=0)
    main_valve_close_delay_seconds: int = Field(default=30, ge=0)

    plant_valve_open_delay_seconds: int = Field(default=0, ge=0)
    plant_valve_close_delay_seconds: int = Field(default=0, ge=0)

    # Watering timing
    panel_sprinkler_seconds: int = Field(default=60, ge=0)
    plant_watering_seconds: int = Field(default=5, ge=0)
    wait_after_pump_stop_seconds: int = Field(default=10, ge=0)
    water_settling_seconds: int = Field(default=3, ge=0)

    @field_validator("run_time")
    @classmethod
    def validate_run_time(cls, value: str) -> str:
        """Require a 24-hour HH:MM time."""

        try:
            datetime.strptime(value, "%H:%M")
        except ValueError as error:
            raise ValueError(
                "run_time must use 24-hour HH:MM format"
            ) from error

        return value

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as error:
            raise ValueError(f"Unknown timezone: {value}") from error

        return value