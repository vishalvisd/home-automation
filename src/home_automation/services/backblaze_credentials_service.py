import json
import os
from pathlib import Path

from home_automation.config.backblaze_credentials import (
    BackblazeCredentials,
)


class BackblazeCredentialsService:
    """Store Backblaze credentials outside version control."""

    def __init__(
        self,
        credentials_file: Path,
    ) -> None:
        self._credentials_file = credentials_file

        self._credentials_file.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

    def get(self) -> BackblazeCredentials | None:
        if not self._credentials_file.exists():
            return None

        raw = json.loads(
            self._credentials_file.read_text()
        )

        return BackblazeCredentials.model_validate(
            raw
        )

    def save(
        self,
        credentials: BackblazeCredentials,
    ) -> None:
        temporary_file = (
            self._credentials_file.with_suffix(
                ".tmp"
            )
        )

        contents = json.dumps(
            credentials.model_dump(),
            indent=2,
        )

        file_descriptor = os.open(
            temporary_file,
            os.O_WRONLY
            | os.O_CREAT
            | os.O_TRUNC,
            0o600,
        )

        try:
            with os.fdopen(
                file_descriptor,
                "w",
            ) as file:
                file.write(contents)
                file.write("\n")

        except Exception:
            try:
                temporary_file.unlink(
                    missing_ok=True
                )
            finally:
                raise

        temporary_file.replace(
            self._credentials_file
        )

        self._credentials_file.chmod(
            0o600
        )

    def status(self) -> dict:
        credentials = self.get()

        if credentials is None:
            return {
                "configured": False,
                "key_id_suffix": None,
            }

        return {
            "configured": True,
            "key_id_suffix": (
                credentials.key_id[-4:]
            ),
        }