import json
import logging
import os
from pathlib import Path
from threading import RLock

from home_automation.config.backblaze_credentials import (
    BackblazeAccount,
    BackblazeAccounts,
)


LOGGER = logging.getLogger("home_automation")


class BackblazeCredentialsService:
    """
    Store the list of Backblaze accounts outside version control.

    The file is runtime/backblaze_credentials.json, mode 0600. The
    application keys never leave the Pi except through the one
    endpoint meant for the downloader; status() masks them.
    """

    def __init__(
        self,
        credentials_file: Path,
    ) -> None:
        self._credentials_file = credentials_file
        self._lock = RLock()

        self._credentials_file.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

    # ------------------------------------------------------------------
    # Read / write
    # ------------------------------------------------------------------

    def get(self) -> BackblazeAccounts:
        with self._lock:
            if not self._credentials_file.exists():
                return BackblazeAccounts()

            raw = json.loads(
                self._credentials_file.read_text(encoding="utf-8")
            )

            return BackblazeAccounts.model_validate(raw)

    def save(self, accounts: BackblazeAccounts) -> BackblazeAccounts:
        with self._lock:
            self._write(accounts)

        return accounts

    def save_from_request(
        self,
        requested: list[dict],
    ) -> BackblazeAccounts:
        """
        Save the list as sent by the UI. A row may leave the
        application key empty to keep the key already stored for an
        account of the same name, so the secret never has to be shown
        or re-typed.
        """

        with self._lock:
            current = {
                account.name: account
                for account in self.get().accounts
            }

            merged = []

            for row in requested:
                name = str(row.get("name", "")).strip()
                application_key = str(
                    row.get("application_key", "")
                ).strip()

                if not application_key:
                    existing = current.get(name)

                    if existing is None:
                        raise ValueError(
                            f"Account '{name or '(unnamed)'}' needs an "
                            "application key"
                        )

                    application_key = existing.application_key

                merged.append(
                    BackblazeAccount(
                        name=name,
                        key_id=str(row.get("key_id", "")),
                        application_key=application_key,
                        bucket=str(row.get("bucket", "")),
                        enabled=bool(row.get("enabled", True)),
                    )
                )

            accounts = BackblazeAccounts(accounts=merged)
            self._write(accounts)

        return accounts

    def migrate_single_key(self, legacy_bucket: str) -> None:
        """
        Convert the old one-key file ({"key_id", "application_key"})
        into a one-account list. The bucket name used to live in
        cameras.json; the caller passes it in. Does nothing when the
        file is already in the new format or absent.
        """

        with self._lock:
            if not self._credentials_file.exists():
                return

            raw = json.loads(
                self._credentials_file.read_text(encoding="utf-8")
            )

            if "accounts" in raw or "key_id" not in raw:
                return

            bucket = legacy_bucket.strip() or "bucket-not-set"

            account = BackblazeAccount(
                name=bucket,
                key_id=raw["key_id"],
                application_key=raw["application_key"],
                bucket=bucket,
                enabled=True,
            )

            self._write(BackblazeAccounts(accounts=[account]))

            LOGGER.info(
                "Backblaze credentials migrated to an account list: %s",
                account.name,
            )

    # ------------------------------------------------------------------
    # Status without secrets
    # ------------------------------------------------------------------

    def status(self) -> dict:
        accounts = self.get()

        return {
            "configured": len(accounts.enabled_accounts()) > 0,
            "accounts": [
                {
                    "name": account.name,
                    "key_id": account.key_id,
                    "key_id_suffix": account.key_id[-4:],
                    "bucket": account.bucket,
                    "enabled": account.enabled,
                }
                for account in accounts.accounts
            ],
        }

    # ------------------------------------------------------------------

    def _write(self, accounts: BackblazeAccounts) -> None:
        temporary_file = self._credentials_file.with_suffix(".tmp")

        contents = json.dumps(accounts.model_dump(), indent=2)

        file_descriptor = os.open(
            temporary_file,
            os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
            0o600,
        )

        try:
            with os.fdopen(file_descriptor, "w") as file:
                file.write(contents)
                file.write("\n")

        except Exception:
            try:
                temporary_file.unlink(missing_ok=True)
            finally:
                raise

        temporary_file.replace(self._credentials_file)
        self._credentials_file.chmod(0o600)
