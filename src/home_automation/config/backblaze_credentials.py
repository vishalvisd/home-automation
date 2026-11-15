from pydantic import BaseModel, Field, field_validator


class BackblazeAccount(BaseModel):
    """
    One Backblaze B2 account: its application key and the bucket the
    camera clips go to. Several accounts are kept and uploads rotate
    between them, one account per calendar day.
    """

    # Short label shown in the UI and logs, for example "eu-06".
    name: str = Field(min_length=1, max_length=40)
    key_id: str = Field(min_length=1)
    application_key: str = Field(min_length=1)
    bucket: str = Field(min_length=1)
    enabled: bool = True

    @field_validator("name", "key_id", "application_key", "bucket")
    @classmethod
    def strip_whitespace(cls, value: str) -> str:
        return value.strip()


class BackblazeAccounts(BaseModel):
    """Contents of runtime/backblaze_credentials.json."""

    accounts: list[BackblazeAccount] = []

    @field_validator("accounts")
    @classmethod
    def unique_names(
        cls,
        accounts: list[BackblazeAccount],
    ) -> list[BackblazeAccount]:
        names = [account.name for account in accounts]

        if len(names) != len(set(names)):
            raise ValueError("Every Backblaze account needs a different name")

        return accounts

    def enabled_accounts(self) -> list[BackblazeAccount]:
        return [account for account in self.accounts if account.enabled]


class BackblazeCredentials(BaseModel):
    """
    The old single-key file format, kept only so an existing
    runtime/backblaze_credentials.json can be migrated to the list.
    """

    key_id: str = Field(min_length=1)
    application_key: str = Field(min_length=1)
