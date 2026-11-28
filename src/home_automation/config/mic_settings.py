import re

from pydantic import BaseModel, Field, field_validator, model_validator


# The name a module sends for itself, made from its hardware address,
# like "esp32-mic-2f20". It is also the name of the module's folder, so
# only these characters are allowed.
MODULE_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{2,31}$")

# More than this is not a home any more; it also keeps a stray device on
# the home network from filling the list.
MAX_MODULES = 16


class MicModuleConfig(BaseModel):
    """One room microphone module."""

    # The hardware name the module sends. Never typed by hand.
    id: str

    # The room name typed in the page ("Hall"). Empty until it is given.
    name: str = Field(default="", max_length=40)

    # Switched off, the Pi neither stores nor plays this module's sound,
    # although the module keeps calling.
    enabled: bool = True

    # When the Pi first saw this module (Asia/Kolkata).
    first_seen_at: str = ""

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        if MODULE_ID_PATTERN.fullmatch(value) is None:
            raise ValueError(
                "a module name is 3 to 32 characters: small letters, "
                "digits and '-'"
            )

        return value

    @field_validator("name")
    @classmethod
    def tidy_name(cls, value: str) -> str:
        return value.strip()


class MicSettings(BaseModel):
    """Persistent configuration for the room microphones."""

    # Off closes the port the modules call, so nothing is received.
    enabled: bool = True

    # How much sound is kept, per module.
    keep_minutes: int = Field(default=120, ge=1, le=24 * 60)

    # All modules together may use this much of the RAM disk. When it is
    # reached the oldest minute goes first, whichever module it is from,
    # so every module keeps the same length of history.
    ram_limit_mb: int = Field(default=120, ge=5, le=1000)

    # Opus bitrate of the stored sound. A change applies the next time a
    # module connects.
    opus_bitrate_kbps: int = Field(default=32, ge=8, le=96)

    modules: list[MicModuleConfig] = Field(
        default_factory=list,
        max_length=MAX_MODULES,
    )

    @model_validator(mode="after")
    def unique_modules(self) -> "MicSettings":
        ids = [module.id for module in self.modules]

        if len(ids) != len(set(ids)):
            raise ValueError("the same module is listed twice")

        return self

    def module(self, module_id: str) -> MicModuleConfig | None:
        for module in self.modules:
            if module.id == module_id:
                return module

        return None
