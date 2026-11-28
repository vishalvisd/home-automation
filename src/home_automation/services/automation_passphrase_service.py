from pathlib import Path

from home_automation.services.passphrase_service import (
    InvalidPassphraseError,
    PassphraseAlreadySetError,
    PassphraseService,
)


__all__ = [
    "AutomationPassphraseService",
    "InvalidPassphraseError",
    "PassphraseAlreadySetError",
]


class AutomationPassphraseService(PassphraseService):
    """
    The passphrase that guards the automation scripts.

    The Automations tab can edit and run Python on the Pi, and the page
    is reachable from the internet, so those addresses ask for a
    passphrase.

    Only a salted hash is kept, in runtime/automation_passphrase.json.
    The first visitor to the Automations tab sets the passphrase. If it
    is forgotten, delete that file on the Pi: the tab then asks for a
    new one. How it is stored and checked is in PassphraseService.
    """

    def __init__(self, passphrase_file: Path) -> None:
        super().__init__(passphrase_file, label="Automation")
