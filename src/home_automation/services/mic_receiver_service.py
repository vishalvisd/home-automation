import logging
import socket
import time
from datetime import datetime
from pathlib import Path
from threading import Event, RLock, Thread, current_thread
from zoneinfo import ZoneInfo

from home_automation.config.mic_settings import (
    MAX_MODULES,
    MODULE_ID_PATTERN,
    MicSettings,
)
from home_automation.services.mic_protocol import (
    FRAME_AUDIO,
    FRAME_HELLO,
    FRAME_STATUS,
    SAMPLE_RATE,
    SEQUENCE_MODULO,
    ProtocolError,
    decode_audio,
    decode_text,
    read_frame,
)
from home_automation.services.mic_recorder import (
    FFMPEG_BINARY,
    MicRecorder,
    MicRecorderError,
)
from home_automation.services.mic_settings_service import MicSettingsService


LOGGER = logging.getLogger("home_automation")

LOCAL_TIME_ZONE = ZoneInfo("Asia/Kolkata")

# A caller must say who it is within this time.
HELLO_TIMEOUT_SECONDS = 10

# A module sends sound 62 times a second. Nothing at all for this long
# means it has gone without saying so (power cut, router restart), and
# the connection is closed. The module calls again by itself.
SILENCE_TIMEOUT_SECONDS = 10

# Sound the module could not send is filled with silence, so the time
# inside a file stays right. A longer hole ends the file instead; the
# next sound starts a new one.
MAX_SILENCE_FILL_SECONDS = 30

# After ffmpeg failed, wait this long before starting it again.
RECORDER_RETRY_SECONDS = 5

# If the port cannot be opened (something else has it), try again.
LISTEN_RETRY_SECONDS = 30

# One more than the modules allowed, for a module that calls again
# before its old connection is noticed as dead.
MAX_CONNECTIONS = MAX_MODULES + 4


def _now_iso() -> str:
    return datetime.now(LOCAL_TIME_ZONE).isoformat(timespec="seconds")


class _Session:
    """One module's connection, from its call until it ends."""

    def __init__(self, connection: socket.socket, address: str) -> None:
        self.connection = connection
        self.address = address
        self.thread = current_thread()

        self.module_id: str | None = None
        self.hello: dict[str, str] = {}
        self.health: dict[str, str] = {}
        self.health_at: str | None = None

        self.connected_at = _now_iso()
        self.last_seen_at = self.connected_at

        self.expected_sequence: int | None = None
        self.frames_received = 0
        self.frames_lost = 0

        self.recorder: MicRecorder | None = None
        self.recorder_error: str | None = None
        self.recorder_retry_at = 0.0

        self.closed = Event()

    def close(self) -> None:
        """Safe from any thread: makes the session's own thread stop."""

        self.closed.set()

        try:
            self.connection.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass

        try:
            self.connection.close()
        except OSError:
            pass


class MicReceiverService:
    """
    Takes the calls of the room microphone modules.

    Each module calls the Pi on one TCP port, says its name and then
    sends its sound without end (the frames are described in
    mic_protocol.py). The Pi never calls a module, so a module needs no
    fixed address. For every connected module this service:

    - adds it to the list in runtime/mics.json the first time it is
      seen, switched on;
    - hands its sound to a MicRecorder, which stores it on the RAM disk;
    - remembers what it says about its own health, for the page.

    A module that is switched off in the list stays connected, so its
    health is still seen, but its sound is thrown away.

    Whatever goes wrong here must never disturb the rest of the
    backend: every thread catches its own errors, and a port that
    cannot be opened is only reported.
    """

    def __init__(
        self,
        settings_service: MicSettingsService,
        storage_directory: Path,
        port: int,
        host: str = "0.0.0.0",
        segment_seconds: int = 60,
    ) -> None:
        self._settings_service = settings_service
        self._storage_directory = storage_directory
        self._port = port
        self._host = host
        self._segment_seconds = segment_seconds

        self._lock = RLock()
        self._stop_event = Event()
        self._thread: Thread | None = None

        # Read on every sound frame, so kept in memory. Replaced as a
        # whole whenever the settings change.
        self._settings: MicSettings = settings_service.get()

        self._listening = False
        self._last_error: str | None = None

        # Connections that have said who they are, by module name.
        self._sessions: dict[str, _Session] = {}
        # Every open connection, also those that have not said it yet.
        self._connections: set[_Session] = set()

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def start(self) -> None:
        with self._lock:
            if self._thread is not None:
                return

            self._stop_event.clear()
            self._thread = Thread(
                target=self._listen,
                name="mic-receiver",
                daemon=True,
            )
            self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()

        with self._lock:
            thread = self._thread
            self._thread = None

        if thread is not None:
            thread.join(timeout=10)

        self._close_all()

    def apply_settings(self, settings: MicSettings) -> None:
        """Take over settings that were just saved from the page."""

        with self._lock:
            self._settings = settings.model_copy(deep=True)
            known = {module.id for module in settings.modules}
            removed = [
                session
                for module_id, session in self._sessions.items()
                if module_id not in known
            ]

        # A module taken off the list is cut off, and its last file is
        # finished before this returns. If the module is still powered
        # it calls again and is added as a new one.
        for session in removed:
            session.close()

        for session in removed:
            if session.thread is not current_thread():
                session.thread.join(timeout=8)

    def files_in_use(self) -> set[Path]:
        """The files being written right now; never to be deleted."""

        with self._lock:
            sessions = list(self._sessions.values())

        in_use: set[Path] = set()

        for session in sessions:
            recorder = session.recorder

            if recorder is not None:
                current = recorder.current_file

                if current is not None:
                    in_use.add(current)

        return in_use

    def status(self) -> dict:
        with self._lock:
            settings = self._settings
            sessions = dict(self._sessions)
            listening = self._listening
            last_error = self._last_error

        modules = []

        for module in settings.modules:
            session = sessions.get(module.id)
            entry: dict[str, object] = {
                "id": module.id,
                "name": module.name,
                "enabled": module.enabled,
                "first_seen_at": module.first_seen_at,
                "connected": session is not None,
            }

            if session is not None:
                recorder = session.recorder

                entry.update(
                    {
                        "address": session.address,
                        "connected_at": session.connected_at,
                        "last_seen_at": session.last_seen_at,
                        "firmware_version": session.hello.get("version"),
                        "firmware_build": session.hello.get("build"),
                        "health": dict(session.health),
                        "health_at": session.health_at,
                        "frames_received": session.frames_received,
                        "frames_lost": session.frames_lost,
                        "recording": (
                            recorder is not None and recorder.running
                        ),
                        "recorder_error": session.recorder_error,
                    }
                )

            modules.append(entry)

        return {
            "enabled": settings.enabled,
            "port": self._port,
            "listening": listening,
            "last_error": last_error,
            "ffmpeg_found": FFMPEG_BINARY is not None,
            "modules": modules,
        }

    # ------------------------------------------------------------------
    # Listening
    # ------------------------------------------------------------------

    def _listen(self) -> None:
        """Runs until stop(). An error here only costs a short wait."""

        while not self._stop_event.is_set():
            try:
                self._listen_until_stopped()
            except Exception:
                LOGGER.exception(
                    "Microphone receiver failed; starting it again in "
                    "%s seconds",
                    LISTEN_RETRY_SECONDS,
                )
                self._set_listening(
                    False,
                    "The receiver failed and is starting again; "
                    "see the log.",
                )
                self._stop_event.wait(LISTEN_RETRY_SECONDS)

    def _listen_until_stopped(self) -> None:
        """
        Keep the port open while the settings say "enabled", closed
        while they say off.
        """

        server: socket.socket | None = None
        retry_at = 0.0

        try:
            while not self._stop_event.is_set():
                wanted = self._settings.enabled

                if not wanted and server is not None:
                    server.close()
                    server = None
                    self._set_listening(False, None)
                    self._close_all()
                    LOGGER.info("Microphones switched off: port closed")

                if wanted and server is None and time.monotonic() >= retry_at:
                    try:
                        server = self._open_port()
                        self._set_listening(True, None)
                        LOGGER.info(
                            "Waiting for microphone modules on port %s",
                            self._port,
                        )
                    except OSError as error:
                        retry_at = time.monotonic() + LISTEN_RETRY_SECONDS
                        self._set_listening(
                            False,
                            f"Cannot open port {self._port}: {error}",
                        )
                        LOGGER.error(
                            "Microphones: cannot open port %s (%s); "
                            "trying again in %s seconds",
                            self._port,
                            error,
                            LISTEN_RETRY_SECONDS,
                        )

                if server is None:
                    self._stop_event.wait(1)
                    continue

                try:
                    connection, address = server.accept()
                except TimeoutError:
                    continue
                except OSError as error:
                    LOGGER.error("Microphones: accept failed: %s", error)
                    self._stop_event.wait(1)
                    continue

                Thread(
                    target=self._serve,
                    args=(connection, address[0]),
                    name=f"mic-module-{address[0]}",
                    daemon=True,
                ).start()
        finally:
            if server is not None:
                server.close()

            self._set_listening(False, self._last_error)

    def _open_port(self) -> socket.socket:
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

        try:
            server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server.bind((self._host, self._port))
            server.listen(MAX_CONNECTIONS)
            # So the loop can look at the stop request once a second.
            server.settimeout(1)
        except OSError:
            server.close()
            raise

        return server

    def _set_listening(self, listening: bool, error: str | None) -> None:
        with self._lock:
            self._listening = listening
            self._last_error = error

    def _close_all(self) -> None:
        with self._lock:
            connections = list(self._connections)

        for session in connections:
            session.close()

        for session in connections:
            if session.thread is not current_thread():
                session.thread.join(timeout=8)

    # ------------------------------------------------------------------
    # One connection
    # ------------------------------------------------------------------

    def _serve(self, connection: socket.socket, address: str) -> None:
        session = _Session(connection, address)

        with self._lock:
            too_many = len(self._connections) >= MAX_CONNECTIONS

            if not too_many:
                self._connections.add(session)

        if too_many:
            session.close()
            return

        reason = "connection closed"

        try:
            self._greet(session)
            self._receive(session)
        except ProtocolError as error:
            reason = str(error)
        except TimeoutError:
            reason = f"silent for {SILENCE_TIMEOUT_SECONDS} seconds"
        except (ConnectionError, OSError) as error:
            reason = str(error) or "connection closed"
        except Exception:
            reason = "error, see the log"
            LOGGER.exception("Microphone connection failed: %s", address)
        finally:
            self._end(session, reason)

    def _greet(self, session: _Session) -> None:
        """Wait for the hello, then make room for this module."""

        session.connection.settimeout(HELLO_TIMEOUT_SECONDS)

        kind, payload = read_frame(self._reader(session))

        if kind != FRAME_HELLO:
            raise ProtocolError("the first frame was not a hello")

        hello = decode_text(payload)
        module_id = hello.get("name", "")

        if MODULE_ID_PATTERN.fullmatch(module_id) is None:
            raise ProtocolError("the hello carries no usable name")

        if hello.get("rate") != str(SAMPLE_RATE):
            raise ProtocolError(
                f"the module sends {hello.get('rate')} samples a second; "
                f"only {SAMPLE_RATE} is understood"
            )

        module, is_new = self._settings_service.register_module(module_id)

        if module is None:
            raise ProtocolError(
                f"the list is full ({MAX_MODULES} modules); "
                f"{module_id} was not added"
            )

        if is_new:
            with self._lock:
                self._settings = self._settings_service.get()

            LOGGER.info("New microphone module added: %s", module_id)

        # The same module calling again replaces its old connection.
        # Wait for the old one to finish its file first, so two
        # recorders never write into the same folder at once.
        with self._lock:
            previous = self._sessions.get(module_id)

        if previous is not None:
            previous.close()
            previous.thread.join(timeout=8)

        session.module_id = module_id
        session.hello = hello

        with self._lock:
            self._sessions[module_id] = session

        LOGGER.info(
            "Microphone module connected: %s (%s, firmware %s)",
            module_id,
            session.address,
            hello.get("version", "unknown"),
        )

    def _receive(self, session: _Session) -> None:
        session.connection.settimeout(SILENCE_TIMEOUT_SECONDS)
        read_exactly = self._reader(session)

        while not session.closed.is_set() and not self._stop_event.is_set():
            kind, payload = read_frame(read_exactly)
            session.last_seen_at = _now_iso()

            if kind == FRAME_AUDIO:
                self._handle_audio(session, payload)
            elif kind == FRAME_STATUS:
                session.health = decode_text(payload)
                session.health_at = session.last_seen_at
            # Any other kind is from a newer firmware: skipped.

    def _end(self, session: _Session, reason: str) -> None:
        self._stop_recorder(session)
        session.close()

        with self._lock:
            self._connections.discard(session)

            was_current = (
                session.module_id is not None
                and self._sessions.get(session.module_id) is session
            )

            if was_current:
                del self._sessions[session.module_id]

        if session.module_id is not None:
            LOGGER.info(
                "Microphone module disconnected: %s (%s)",
                session.module_id,
                reason,
            )
        elif reason != "connection closed":
            LOGGER.warning(
                "Microphone port: caller %s refused (%s)",
                session.address,
                reason,
            )

    @staticmethod
    def _reader(session: _Session):
        connection = session.connection

        def read_exactly(count: int) -> bytes:
            chunks = bytearray()

            while len(chunks) < count:
                chunk = connection.recv(count - len(chunks))

                if not chunk:
                    raise ConnectionError("connection closed")

                chunks += chunk

            return bytes(chunks)

        return read_exactly

    # ------------------------------------------------------------------
    # Sound
    # ------------------------------------------------------------------

    def _handle_audio(self, session: _Session, payload: bytes) -> None:
        sequence, pcm = decode_audio(payload)
        lost = self._frames_lost_before(session, sequence)

        session.frames_received += 1
        session.frames_lost += lost

        module = self._settings.module(session.module_id or "")

        if module is None or not module.enabled:
            self._stop_recorder(session)
            return

        if lost:
            samples_per_frame = len(pcm) // 2
            max_fill = MAX_SILENCE_FILL_SECONDS * SAMPLE_RATE

            if lost * samples_per_frame <= max_fill:
                pcm = bytes(lost * len(pcm)) + pcm
            else:
                # Too long a hole to fill: end the file here. The
                # recorder started below names its file by the time now.
                self._stop_recorder(session)

        self._record(session, pcm)

    @staticmethod
    def _frames_lost_before(session: _Session, sequence: int) -> int:
        expected = session.expected_sequence
        session.expected_sequence = (sequence + 1) % SEQUENCE_MODULO

        if expected is None:
            return 0

        lost = (sequence - expected) % SEQUENCE_MODULO

        # A counter that went backwards means the module started again;
        # nothing can be said about what was lost.
        if lost > SEQUENCE_MODULO // 2:
            return 0

        return lost

    def _record(self, session: _Session, pcm: bytes) -> None:
        recorder = session.recorder

        if recorder is None:
            if time.monotonic() < session.recorder_retry_at:
                return

            recorder = MicRecorder(
                session.module_id or "unknown",
                self._storage_directory / (session.module_id or "unknown"),
                self._settings.opus_bitrate_kbps,
                self._segment_seconds,
            )

            try:
                recorder.start()
            except MicRecorderError as error:
                self._recorder_failed(session, str(error))
                return

            session.recorder = recorder
            session.recorder_error = None

        try:
            recorder.write(pcm)
        except MicRecorderError as error:
            self._stop_recorder(session)
            self._recorder_failed(session, str(error))

    def _recorder_failed(self, session: _Session, detail: str) -> None:
        session.recorder_retry_at = time.monotonic() + RECORDER_RETRY_SECONDS

        # Said once, not 62 times a second.
        if session.recorder_error != detail:
            LOGGER.error(
                "Microphone sound of %s is not being stored: %s",
                session.module_id,
                detail,
            )

        session.recorder_error = detail

    @staticmethod
    def _stop_recorder(session: _Session) -> None:
        recorder = session.recorder

        if recorder is None:
            return

        # The recorder stays known until ffmpeg has finished its last
        # file, so that file counts as "in use" up to the end.
        try:
            recorder.stop()
        except Exception:
            LOGGER.exception(
                "Error while stopping the microphone recorder: %s",
                session.module_id,
            )
        finally:
            session.recorder = None
