import asyncio
import time
from typing import Annotated, Literal
from urllib.parse import unquote

from fastapi import (
    APIRouter,
    Depends,
    Header,
    HTTPException,
    Query,
    Request,
    status,
)
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from home_automation.api.dependencies import (
    get_mic_passphrase_service,
    get_mic_receiver_service,
    get_mic_settings_service,
    get_mic_store_service,
)
from home_automation.config.mic_settings import MicSettings
from home_automation.services.mic_download import (
    FORMATS,
    DownloadBusyError,
    DownloadFailedError,
    download_name,
    make_download,
)
from home_automation.services.mic_receiver_service import (
    LiveUnavailableError,
    MicReceiverService,
)
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

# Live listening looks for new sound this often. A module sends a block
# every 16 ms, so this adds next to nothing to the delay.
LIVE_POLL_SECONDS = 0.02

# When a module sends nothing, a live listener gets a little silence
# this often, so the connection stays in use.
LIVE_SILENCE_EVERY_SECONDS = 1.0
LIVE_SILENCE = bytes(512)


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



@router.get("/modules/{module_id}/live", dependencies=[PassphraseRequired])
async def listen_live(
    module_id: str,
    request: Request,
    receiver: ReceiverServiceDependency,
) -> StreamingResponse:
    """
    One module's sound as it arrives, without end: raw samples, signed
    16-bit, low byte first, mono, 16000 a second. The page plays them
    itself. Loudness is the page's business; this is the sound as the
    module sends it.
    """

    try:
        listener = receiver.open_live(module_id)
    except KeyError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown module: {module_id}",
        ) from error
    except LiveUnavailableError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(error),
        ) from error

    async def chunks():
        quiet_since = time.monotonic()

        try:
            # Ends when the browser goes away, or when the module is
            # switched off or removed (the receiver closes the listener).
            while not listener.closed:
                if await request.is_disconnected():
                    break

                sound = listener.take()

                if sound:
                    quiet_since = time.monotonic()
                    yield sound
                    continue

                if (
                    time.monotonic() - quiet_since
                    >= LIVE_SILENCE_EVERY_SECONDS
                ):
                    quiet_since = time.monotonic()
                    yield LIVE_SILENCE

                await asyncio.sleep(LIVE_POLL_SECONDS)
        finally:
            receiver.close_live(listener)

    return StreamingResponse(
        chunks(),
        media_type="application/octet-stream",
        headers={
            "Cache-Control": "no-store",
            # Ask anything in between not to collect the sound first.
            "X-Accel-Buffering": "no",
            "X-Sample-Rate": "16000",
        },
    )


@router.get(
    "/modules/{module_id}/download",
    dependencies=[PassphraseRequired],
)
def download(
    module_id: str,
    service: SettingsServiceDependency,
    store: StoreServiceDependency,
    start: Annotated[float, Query(description="seconds since 1970")],
    end: Annotated[float, Query(description="seconds since 1970")],
    file_format: Annotated[
        Literal["mp3", "opus"],
        Query(alias="format"),
    ] = "mp3",
    level: bool = True,
) -> StreamingResponse:
    """
    The stored sound of one module between two moments, as one file.

    MP3 plays everywhere; "level" makes it louder and evens the volume
    out. Opus is the stored sound itself, joined and not converted, so
    "level" does nothing there. A hole in the stored sound is simply
    left out: the file is then shorter than the time asked for.
    """

    module = service.get().module(module_id)

    if module is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown module: {module_id}",
        )

    if not end > start:
        raise HTTPException(
            status_code=422,
            detail="The end must be after the start.",
        )

    end = min(end, time.time())
    files = store.files_between(module_id, start, end)

    if not files:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No sound is stored for that time.",
        )

    try:
        pieces = make_download(files, start, end, file_format, level)
    except DownloadBusyError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(error),
        ) from error
    except DownloadFailedError as error:
        raise HTTPException(status_code=500, detail=str(error)) from error

    ending, media_type = FORMATS[file_format]
    # The file is named by the first sound it really holds.
    first_sound = max(start, files[0][1])
    name = download_name(module.name or module.id, first_sound, ending)

    return StreamingResponse(
        pieces,
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{name}"',
            "Cache-Control": "no-store",
        },
    )
