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


class PassphraseService:
    """
    A passphrase that guards one part of the page.

    The page is reachable from the internet without a login, so the
    parts that must not be open to everyone ask for a passphrase. Each
    such part has its own passphrase, in its own file: the automation
    scripts (AutomationPassphraseService) and the room microphones.

    Only a salted hash is kept, in a file under runtime/. The first
    visitor to that part of the page sets the passphrase. If it is
    forgotten, delete the file on the Pi: the page then asks for a new
    one. No restart is needed, because the file is read on every check.

    "label" is the word used for this passphrase in the log and in
    messages, for example "Automation".
    """

    def __init__(self, passphrase_file: Path, label: str) -> None:
        self._file = passphrase_file
        self._label = label
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

        LOGGER.info("%s passphrase set", self._label)

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

        LOGGER.warning("Wrong %s passphrase given", self._label.lower())
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
                "%s passphrase file unreadable (%s); "
                "treated as not set",
                self._label,
                error,
            )
            return None

        try:
            bytes.fromhex(record["salt"])
            bytes.fromhex(record["hash"])
            int(record["iterations"])
        except (KeyError, TypeError, ValueError):
            LOGGER.warning(
                "%s passphrase file is damaged; treated as not set",
                self._label,
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
