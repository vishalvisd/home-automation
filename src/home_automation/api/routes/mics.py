from typing import Annotated
from urllib.parse import unquote

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field

from home_automation.api.dependencies import (
    get_mic_passphrase_service,
    get_mic_receiver_service,
    get_mic_settings_service,
    get_mic_store_service,
)
from home_automation.config.mic_settings import MicSettings
from home_automation.services.mic_receiver_service import MicReceiverService
from home_automation.services.mic_settings_service import MicSettingsService
from home_automation.services.mic_store_service import MicStoreService
from home_automation.services.passphrase_service import (
    InvalidPassphraseError,
    PassphraseAlreadySetError,
    PassphraseService,
)


router = APIRouter(
    prefix="/api/mics",
    tags=["mics"],
)


PassphraseServiceDependency = Annotated[
    PassphraseService,
    Depends(get_mic_passphrase_service),
]

SettingsServiceDependency = Annotated[
    MicSettingsService,
    Depends(get_mic_settings_service),
]

ReceiverServiceDependency = Annotated[
    MicReceiverService,
    Depends(get_mic_receiver_service),
]

StoreServiceDependency = Annotated[
    MicStoreService,
    Depends(get_mic_store_service),
]


class PassphraseBody(BaseModel):
    passphrase: str


class GeneralSettingsUpdate(BaseModel):
    """The settings that are not about one module."""

    enabled: bool
    keep_minutes: int
    ram_limit_mb: int
    opus_bitrate_kbps: int


class ModuleUpdate(BaseModel):
    name: str = Field(default="", max_length=40)
    enabled: bool = True


def require_passphrase(
    passphrases: PassphraseServiceDependency,
    x_mics_passphrase: Annotated[str | None, Header()] = None,
) -> None:
    """
    Guard for every microphone address: this is the sound of rooms and
    the page is reachable from the internet.

    The page sends the passphrase with each request in the
    X-Mics-Passphrase header, percent-encoded because a header cannot
    carry every character. It is a passphrase of its own, not the one
    of the automation scripts.
    """

    if not passphrases.is_set():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Set a passphrase for the microphones first.",
        )

    given = unquote(x_mics_passphrase or "")

    if not passphrases.check(given):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Wrong passphrase.",
        )


PassphraseRequired = Depends(require_passphrase)


@router.get("/passphrase")
def passphrase_state(
    passphrases: PassphraseServiceDependency,
) -> dict:
    """Open to anyone: says only whether a passphrase has been set."""

    return {"set": passphrases.is_set()}


@router.post("/passphrase")
def set_passphrase(
    body: PassphraseBody,
    passphrases: PassphraseServiceDependency,
) -> dict:
    """Sets the passphrase the first time. Refused once one is set."""

    try:
        passphrases.set_first(body.passphrase)
    except InvalidPassphraseError as error:
        raise HTTPException(
            status_code=422,
            detail=str(error),
        ) from error
    except PassphraseAlreadySetError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(error),
        ) from error

    return {"set": True}


@router.post("/passphrase/check", dependencies=[PassphraseRequired])
def check_passphrase() -> dict:
    """Answers 200 when the passphrase in the header is right."""

    return {"ok": True}


@router.get("/status", dependencies=[PassphraseRequired])
def mic_status(
    receiver: ReceiverServiceDependency,
    store: StoreServiceDependency,
) -> dict:
    """Every module's health and what is stored, for the page."""

    receiving = receiver.status()
    storage = store.status()
    stored_by_module = storage.pop("modules")

    for module in receiving["modules"]:
        module["stored"] = stored_by_module.get(module["id"])

    return {
        **receiving,
        "storage": storage,
    }


@router.get("/settings", dependencies=[PassphraseRequired])
def get_settings(
    service: SettingsServiceDependency,
) -> MicSettings:
    return service.get()


@router.put("/settings", dependencies=[PassphraseRequired])
def save_settings(
    update: GeneralSettingsUpdate,
    service: SettingsServiceDependency,
    receiver: ReceiverServiceDependency,
    store: StoreServiceDependency,
) -> MicSettings:
    """
    Save the general settings. The module list is left as it is: a
    module that called for the first time while the page was open must
    not be lost by a save.
    """

    current = service.get()

    try:
        settings = MicSettings.model_validate(
            {
                **update.model_dump(),
                "modules": [
                    module.model_dump() for module in current.modules
                ],
            }
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    service.save(settings)
    receiver.apply_settings(settings)
    # A shorter history or a smaller limit applies now.
    store.clean()

    return settings


@router.put("/modules/{module_id}", dependencies=[PassphraseRequired])
def save_module(
    module_id: str,
    update: ModuleUpdate,
    service: SettingsServiceDependency,
    receiver: ReceiverServiceDependency,
) -> MicSettings:
    """Give a module its room name, or switch it on or off."""

    settings = service.get()
    module = settings.module(module_id)

    if module is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown module: {module_id}",
        )

    module.name = update.name.strip()
    module.enabled = update.enabled

    service.save(settings)
    receiver.apply_settings(settings)

    return settings


@router.delete("/modules/{module_id}", dependencies=[PassphraseRequired])
def remove_module(
    module_id: str,
    service: SettingsServiceDependency,
    receiver: ReceiverServiceDependency,
    store: StoreServiceDependency,
) -> MicSettings:
    """
    Take a module off the list and delete its stored sound. A module
    that is still powered calls again within seconds and is added as a
    new one, so this is for a module that has been taken out.
    """

    settings = service.get()

    if settings.module(module_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown module: {module_id}",
        )

    settings.modules = [
        module for module in settings.modules if module.id != module_id
    ]

    service.save(settings)
    receiver.apply_settings(settings)
    store.delete_module(module_id)

    return settings
