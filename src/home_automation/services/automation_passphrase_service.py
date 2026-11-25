import hashlib
import hmac
import json
import logging
import os
import secrets
import time
from pathlib import Path
from threading import Lock


LOGGER = logging.getLogger("home_automation")

# Work done to turn a passphrase into the stored value. It makes
# guessing slow for someone who has copied the file.
HASH_ITERATIONS = 200_000
SALT_BYTES = 16

MIN_PASSPHRASE_LENGTH = 4
MAX_PASSPHRASE_LENGTH = 200

# A wrong passphrase is answered only after this wait, and wrong ones
# are handled one at a time, so guessing over the network is about one
# try per second however many requests are sent.
WRONG_PASSPHRASE_DELAY_SECONDS = 1.0


class PassphraseAlreadySetError(Exception):
    pass


class InvalidPassphraseError(Exception):
    pass


class AutomationPassphraseService:
    """
    The passphrase that guards the automation scripts.

    The Automations tab can edit and run Python on the Pi, and the page
    is reachable from the internet, so those addresses ask for a
    passphrase. Nothing else on the page does.

    Only a salted hash is kept, in runtime/automation_passphrase.json.
    The first visitor to the Automations tab sets the passphrase. If it
    is forgotten, delete that file on the Pi: the tab then asks for a
    new one. No restart is needed, because the file is read on every
    check.
    """

    def __init__(self, passphrase_file: Path) -> None:
        self._file = passphrase_file
        self._write_lock = Lock()
        self._wrong_lock = Lock()

        # Remembers the last passphrase that was right, so the slow
        # hash is not repeated on every request of the page. Kept as a
        # keyed digest, never as the passphrase itself, together with
        # the stored record it was right for.
        self._memory_key = secrets.token_bytes(32)
        self._accepted: tuple[str, str, bytes] | None = None

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def is_set(self) -> bool:
        return self._read() is not None

    def set_first(self, passphrase: str) -> None:
        """Store the passphrase. Refused when one is already set."""

        self._validate(passphrase)

        with self._write_lock:
            if self._read() is not None:
                raise PassphraseAlreadySetError(
                    "A passphrase is already set. To change it, delete "
                    f"{self._file.name} in the Pi's runtime folder."
                )

            salt = secrets.token_bytes(SALT_BYTES)

            record = {
                "algorithm": "pbkdf2_sha256",
                "iterations": HASH_ITERATIONS,
                "salt": salt.hex(),
                "hash": self._hash(passphrase, salt, HASH_ITERATIONS).hex(),
            }

            self._write(record)

        LOGGER.info("Automation passphrase set")

    def check(self, passphrase: str | None) -> bool:
        """True when a passphrase is set and this is it."""

        record = self._read()

        if record is None or not passphrase:
            return False

        digest = hmac.new(
            self._memory_key,
            passphrase.encode("utf-8"),
            hashlib.sha256,
        ).digest()

        accepted = self._accepted

        if (
            accepted is not None
            and accepted[0] == record["salt"]
            and accepted[1] == record["hash"]
            and hmac.compare_digest(accepted[2], digest)
        ):
            return True

        with self._wrong_lock:
            expected = bytes.fromhex(record["hash"])
            actual = self._hash(
                passphrase,
                bytes.fromhex(record["salt"]),
                int(record["iterations"]),
            )

            if hmac.compare_digest(expected, actual):
                self._accepted = (record["salt"], record["hash"], digest)
                return True

            time.sleep(WRONG_PASSPHRASE_DELAY_SECONDS)

        LOGGER.warning("Wrong automation passphrase given")
        return False

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _validate(passphrase: str) -> None:
        if len(passphrase) < MIN_PASSPHRASE_LENGTH:
            raise InvalidPassphraseError(
                f"Use at least {MIN_PASSPHRASE_LENGTH} characters."
            )

        if len(passphrase) > MAX_PASSPHRASE_LENGTH:
            raise InvalidPassphraseError(
                f"Use at most {MAX_PASSPHRASE_LENGTH} characters."
            )

    @staticmethod
    def _hash(passphrase: str, salt: bytes, iterations: int) -> bytes:
        return hashlib.pbkdf2_hmac(
            "sha256",
            passphrase.encode("utf-8"),
            salt,
            iterations,
        )

    def _read(self) -> dict | None:
        """The stored record, or None when no usable one exists."""

        try:
            record = json.loads(self._file.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (OSError, ValueError) as error:
            LOGGER.warning(
                "Automation passphrase file unreadable (%s); "
                "treated as not set",
                error,
            )
            return None

        try:
            bytes.fromhex(record["salt"])
            bytes.fromhex(record["hash"])
            int(record["iterations"])
        except (KeyError, TypeError, ValueError):
            LOGGER.warning(
                "Automation passphrase file is damaged; treated as not set"
            )
            return None

        return record

    def _write(self, record: dict) -> None:
        self._file.parent.mkdir(parents=True, exist_ok=True)

        temporary_file = self._file.with_suffix(".tmp")

        # Readable by the service user only, from the first byte.
        file_descriptor = os.open(
            temporary_file,
            os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
            0o600,
        )

        with os.fdopen(file_descriptor, "w", encoding="utf-8") as handle:
            json.dump(record, handle, indent=2)
            handle.write("\n")

        temporary_file.replace(self._file)
        self._file.chmod(0o600)
