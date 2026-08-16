from pydantic import BaseModel, Field


class BackblazeCredentials(BaseModel):
    """Persistent Backblaze B2 authentication credentials."""

    key_id: str = Field(min_length=1)
    application_key: str = Field(min_length=1)