import logging

from datetime import datetime
from pathlib import Path
from threading import Event, RLock, Thread
from time import monotonic
from typing import Any

from home_automation.config.camera_settings import (
    CameraConfig,
    CameraSettings,
)
from home_automation.services.camera_settings_service import (
    CameraSettingsService,
)
from collections.abc import Callable
from home_automation.services.camera_upload_service import (
    CameraUploadService,
)
from home_automation.services.camera_stream_source import (
    CameraStreamSource,
)

LOGGER = logging.getLogger(__name__)

try:
    import gi

    gi.require_version("Gst", "1.0")

    from gi.repository import Gst

except (ImportError, ValueError) as error:
    Gst = None
    GST_IMPORT_ERROR = error

else:
    GST_IMPORT_ERROR = None
    Gst.init(None)


class CameraRecorderUnavailableError(RuntimeError):
    """Raised when GStreamer Python bindings are unavailable."""


class CameraRecorder:
    """Encode and segment frames from a reconnectable camera stream."""

    STOP_TIMEOUT_SECONDS = 10

    def __init__(
        self,
        camera: CameraConfig,
        settings: CameraSettings,
        on_fragment_closed: Callable[
            [CameraConfig, Path],
            None,
        ]
        | None = None,
    ) -> None:
        self._camera = camera
        self._settings = settings

        self._lock = RLock()
        self._stop_event = Event()

        self._pipeline: Any = None
        self._frame_source: Any = None
        self._thread: Thread | None = None

        self._running = False
        self._last_error: str | None = None
        self._current_fragment: str | None = None
        self._last_completed_fragment: str | None = None
        self._on_fragment_closed = (
            on_fragment_closed
        )

        self._stream_source = CameraStreamSource(
            camera,
            Gst,
            self._push_frame,
        )

    def start(self) -> None:
        if Gst is None:
            raise CameraRecorderUnavailableError(
                f"GStreamer Python bindings unavailable: "
                f"{GST_IMPORT_ERROR}"
            )

        with self._lock:
            if self._running:
                return

            camera_directory = (
                Path(self._settings.recording_directory)
                / self._camera.key
            )

            camera_directory.mkdir(
                parents=True,
                exist_ok=True,
            )

            pipeline_description = (
                self._build_pipeline_description(
                    camera_directory
                )
            )

            try:
                pipeline = Gst.parse_launch(
                    pipeline_description
                )

                frame_source = pipeline.get_by_name(
                    "frame_source"
                )

                if frame_source is None:
                    raise RuntimeError(
                        "Unable to find recording appsrc."
                    )

                segmenter = pipeline.get_by_name(
                    "segmenter"
                )

                if segmenter is None:
                    raise RuntimeError(
                        "Unable to find splitmuxsink."
                    )

                segmenter.connect(
                    "format-location",
                    self._format_fragment_location,
                    camera_directory,
                )

                self._pipeline = pipeline
                self._frame_source = frame_source
                self._stop_event.clear()
                self._last_error = None

                result = pipeline.set_state(
                    Gst.State.PLAYING
                )

                if result == Gst.StateChangeReturn.FAILURE:
                    pipeline.set_state(
                        Gst.State.NULL
                    )
                    raise RuntimeError(
                        "GStreamer pipeline failed to start."
                    )

                self._running = True

                self._thread = Thread(
                    target=self._monitor_pipeline,
                    name=(
                        f"camera-recorder-"
                        f"{self._camera.key}"
                    ),
                    daemon=True,
                )

                self._thread.start()
                self._stream_source.start()

                LOGGER.info(
                    "Camera recorder started: %s",
                    self._camera.name,
                )

            except Exception as error:
                self._last_error = str(error)

                if self._pipeline is not None:
                    self._pipeline.set_state(
                        Gst.State.NULL
                    )

                self._pipeline = None
                self._frame_source = None
                self._running = False
                raise

    def stop(self) -> None:
        with self._lock:
            self._stop_event.set()
            thread = self._thread
            running = self._running

        # Stop collecting frames first. The recording pipeline then receives
        # EOS and closes the final non-empty segment cleanly.
        self._stream_source.stop()

        if running and thread is not None:
            thread.join(
                timeout=self.STOP_TIMEOUT_SECONDS + 2
            )

        with self._lock:
            if (
                self._pipeline is not None
                and self._running
            ):
                self._pipeline.set_state(
                    Gst.State.NULL
                )

                self._running = False
                self._pipeline = None
                self._frame_source = None

    def status(self) -> dict[str, object]:
        stream_status = self._stream_source.status()

        with self._lock:
            return {
                "key": self._camera.key,
                "name": self._camera.name,
                "host": self._camera.host,
                "running": self._running,
                "last_error": self._last_error,
                "current_fragment": (
                    self._current_fragment
                ),
                "last_completed_fragment": (
                    self._last_completed_fragment
                ),
                **stream_status,
            }

    def _build_pipeline_description(
        self,
        camera_directory: Path,
    ) -> str:
        segment_nanoseconds = (
            self._settings.segment_seconds
            * 1_000_000_000
        )

        keyframe_interval = max(
            self._settings.frame_rate,
            1,
        )

        location = (
            camera_directory
            / "segment-%05d.ts"
        )

        return (
            f'appsrc '
            f'name=frame_source '
            f'is-live=true '
            f'format=time '
            f'do-timestamp=true '
            f'min-latency=0 '
            f'block=false '
            f'emit-signals=false '
            f'caps="image/jpeg,'
            f'framerate={self._settings.frame_rate}/1" '
            f'! queue '
            f'max-size-buffers=2 '
            f'max-size-bytes=0 '
            f'max-size-time=0 '
            f'leaky=downstream '
            f'! videorate '
            f'drop-only=true '
            f'max-rate={self._settings.frame_rate} '
            f'! jpegdec '
            f'! videoconvert '
            f'! x264enc '
            f'bitrate={self._settings.video_bitrate_kbps} '
            f'speed-preset=ultrafast '
            f'tune=zerolatency '
            f'key-int-max={keyframe_interval} '
            f'! h264parse config-interval=-1 '
            f'! splitmuxsink '
            f'name=segmenter '
            f'muxer=mpegtsmux '
            f'max-size-time={segment_nanoseconds} '
            f'max-size-bytes=0 '
            f'send-keyframe-requests=true '
            f'location="{location}"'
        )

    def _push_frame(self, buffer: Any) -> None:
        with self._lock:
            frame_source = self._frame_source
            running = self._running

        if (
            not running
            or frame_source is None
            or self._stop_event.is_set()
        ):
            return

        # The HTTP capture pipeline has a different clock. Clear its
        # timestamps so appsrc stamps each received JPEG with the long-lived
        # recording pipeline's running time. Network outages therefore become
        # timestamp gaps; no missing frames are fabricated.
        frame = buffer.copy()
        frame.pts = Gst.CLOCK_TIME_NONE
        frame.dts = Gst.CLOCK_TIME_NONE
        frame.duration = (
            Gst.SECOND
            // max(self._settings.frame_rate, 1)
        )

        result = frame_source.emit(
            "push-buffer",
            frame,
        )

        if (
            result != Gst.FlowReturn.OK
            and not self._stop_event.is_set()
        ):
            LOGGER.warning(
                "Camera frame was not accepted by recorder [%s]: %s",
                self._camera.name,
                result,
            )

    def _format_fragment_location(
        self,
        _segmenter: Any,
        fragment_id: int,
        camera_directory: Path,
    ) -> str:
        timestamp = datetime.now().strftime(
            "%Y%m%d_%H%M%S_%f"
        )

        path = camera_directory / (
            f"{timestamp}_"
            f"{fragment_id:06d}.ts"
        )

        with self._lock:
            self._current_fragment = str(path)

        return str(path)

    def _monitor_pipeline(self) -> None:
        pipeline = self._pipeline
        bus = pipeline.get_bus()

        stop_requested_at: float | None = None
        eos_sent = False

        try:
            while True:
                if (
                    self._stop_event.is_set()
                    and not eos_sent
                ):
                    frame_source = self._frame_source

                    if frame_source is not None:
                        frame_source.emit(
                            "end-of-stream"
                        )
                    else:
                        pipeline.send_event(
                            Gst.Event.new_eos()
                        )

                    eos_sent = True
                    stop_requested_at = monotonic()

                message = bus.timed_pop_filtered(
                    500 * Gst.MSECOND,
                    (
                        Gst.MessageType.ERROR
                        | Gst.MessageType.EOS
                        | Gst.MessageType.ELEMENT
                    ),
                )

                if message is None:
                    if (
                        stop_requested_at is not None
                        and monotonic()
                        - stop_requested_at
                        >= self.STOP_TIMEOUT_SECONDS
                    ):
                        LOGGER.warning(
                            "Timed out waiting for camera "
                            "pipeline to stop: %s",
                            self._camera.name,
                        )
                        break

                    continue

                if message.type == Gst.MessageType.ERROR:
                    error, debug = message.parse_error()

                    self._last_error = (
                        f"{error}: {debug or ''}".strip()
                    )

                    LOGGER.error(
                        "Camera recorder error [%s]: %s",
                        self._camera.name,
                        self._last_error,
                    )

                    break

                if message.type == Gst.MessageType.EOS:
                    break

                if message.type == Gst.MessageType.ELEMENT:
                    self._handle_element_message(
                        message
                    )

        finally:
            self._stream_source.stop()

            pipeline.set_state(
                Gst.State.NULL
            )

            with self._lock:
                self._running = False
                self._pipeline = None
                self._frame_source = None

            LOGGER.info(
                "Camera recorder stopped: %s",
                self._camera.name,
            )

    def _handle_element_message(
        self,
        message: Any,
    ) -> None:
        structure = message.get_structure()

        if structure is None:
            return

        if (
            structure.get_name()
            != "splitmuxsink-fragment-closed"
        ):
            return

        location = structure.get_string(
            "location"
        )

        if not location:
            return

        file_path = Path(location)

        # Normally splitmuxsink does not create a fragment until a frame has
        # arrived. Keep this guard so an empty file is never uploaded.
        if (
            not file_path.exists()
            or file_path.stat().st_size == 0
        ):
            file_path.unlink(missing_ok=True)

            LOGGER.info(
                "Empty camera segment discarded [%s]: %s",
                self._camera.name,
                location,
            )
            return

        with self._lock:
            self._last_completed_fragment = location

            if self._current_fragment == location:
                self._current_fragment = None

        LOGGER.info(
                "Camera segment created [%s]: %s",
                self._camera.name,
                location,
            )

        if self._on_fragment_closed is not None:
            try:
                self._on_fragment_closed(
                    self._camera,
                    file_path,
                )
            except Exception:
                LOGGER.exception(
                    "Camera segment callback failed [%s]: %s",
                    self._camera.name,
                    location,
                )


class CameraRecorderService:
    """Manage and automatically recover CCTV recording pipelines."""

    SUPERVISOR_CHECK_SECONDS = 2
    RECOVERY_CONFIRM_SECONDS = 5

    def __init__(
        self,
        settings_service: CameraSettingsService,
        upload_service: CameraUploadService,
    ) -> None:
        self._upload_service = upload_service
        self._settings_service = settings_service
        self._lock = RLock()

        self._recorders: dict[
            str,
            CameraRecorder,
        ] = {}

        self._next_retry_at: dict[
            str,
            float,
        ] = {}

        self._restart_counts: dict[
            str,
            int,
        ] = {}

        self._recovery_pending_since: dict[
            str,
            float,
        ] = {}

        # "Desired running" is deliberately separate from
        # settings.recording_enabled.
        #
        # recording_enabled controls automatic startup when
        # FastAPI starts.
        #
        # desired_running becomes True after either automatic
        # startup or the user presses "Start Recording".
        self._desired_running = False

        self._shutdown_event = Event()

        self._supervisor_thread = Thread(
            target=self._supervisor_loop,
            name="camera-recorder-supervisor",
            daemon=True,
        )

        self._supervisor_thread.start()

    def start(self) -> dict:
        settings = self._settings_service.get()

        with self._lock:
            self._desired_running = True

        for camera in settings.cameras:
            if camera.enabled:
                self._start_camera(
                    camera,
                    settings,
                    is_recovery=False,
                )

        return self.status()

    def stop(self) -> dict:
        # Set this before stopping pipelines so the supervisor
        # cannot restart them while Stop Recording is running.
        with self._lock:
            self._desired_running = False
            self._next_retry_at.clear()
            self._recovery_pending_since.clear()

            recorders = list(
                self._recorders.values()
            )

        for recorder in recorders:
            recorder.stop()

        return self.status()

    def start_if_enabled(self) -> None:
        settings = self._settings_service.get()

        if settings.recording_enabled:
            self.start()

    def shutdown(self) -> None:
        self.stop()

        self._shutdown_event.set()

        if self._supervisor_thread.is_alive():
            self._supervisor_thread.join(
                timeout=self.SUPERVISOR_CHECK_SECONDS + 2
            )

    def status(self) -> dict:
        settings = self._settings_service.get()

        camera_statuses = []

        with self._lock:
            desired_running = self._desired_running

            for camera in settings.cameras:
                recorder = self._recorders.get(
                    camera.key
                )

                restart_count = (
                    self._restart_counts.get(
                        camera.key,
                        0,
                    )
                )

                if recorder is None:
                    camera_statuses.append(
                        {
                            "key": camera.key,
                            "name": camera.name,
                            "host": camera.host,
                            "enabled": camera.enabled,
                            "running": False,
                            "last_error": None,
                            "current_fragment": None,
                            "last_completed_fragment": None,
                            "stream_connected": False,
                            "stream_reconnect_count": 0,
                            "last_stream_error": None,
                            "restart_count": restart_count,
                        }
                    )

                else:
                    recorder_status = (
                        recorder.status()
                    )

                    recorder_status["enabled"] = (
                        camera.enabled
                    )

                    recorder_status[
                        "restart_count"
                    ] = restart_count

                    camera_statuses.append(
                        recorder_status
                    )

        return {
            "gstreamer_available": (
                Gst is not None
            ),
            "gstreamer_error": (
                None
                if GST_IMPORT_ERROR is None
                else str(GST_IMPORT_ERROR)
            ),
            "recording_enabled": (
                settings.recording_enabled
            ),
            "desired_running": (
                desired_running
            ),
            "recording_directory": (
                settings.recording_directory
            ),
            "recorder_restart_delay_seconds": (
                settings.recorder_restart_delay_seconds
            ),
            "cameras": camera_statuses,
        }

    def _supervisor_loop(self) -> None:
        LOGGER.info(
            "Camera recorder supervisor started"
        )

        while not self._shutdown_event.is_set():
            try:
                self._supervise_once()

            except Exception:
                LOGGER.exception(
                    "Unexpected camera recorder "
                    "supervisor error"
                )

            self._shutdown_event.wait(
                timeout=self.SUPERVISOR_CHECK_SECONDS
            )

        LOGGER.info(
            "Camera recorder supervisor stopped"
        )

    def _supervise_once(self) -> None:
        with self._lock:
            if not self._desired_running:
                return

        settings = self._settings_service.get()
        now = monotonic()

        for camera in settings.cameras:
            if not camera.enabled:
                continue

            with self._lock:
                recorder = self._recorders.get(
                    camera.key
                )

                next_retry = self._next_retry_at.get(
                    camera.key
                )

                recovery_pending_since = (
                    self._recovery_pending_since.get(
                        camera.key
                    )
                )

            running = (
                recorder is not None
                and recorder.status()["running"]
            )

            if running:
                if (
                    recovery_pending_since is not None
                    and (
                        now - recovery_pending_since
                        >= self.RECOVERY_CONFIRM_SECONDS
                    )
                ):
                    with self._lock:
                        self._recovery_pending_since.pop(
                            camera.key,
                            None,
                        )

                        self._restart_counts[
                            camera.key
                        ] = (
                            self._restart_counts.get(
                                camera.key,
                                0,
                            )
                            + 1
                        )

                    LOGGER.info(
                        "Camera recorder recovered: %s",
                        camera.name,
                    )

                continue

            # A recovery attempt started, but the pipeline died
            # before remaining healthy long enough to confirm it.
            if recovery_pending_since is not None:
                with self._lock:
                    self._recovery_pending_since.pop(
                        camera.key,
                        None,
                    )

                    self._next_retry_at[
                        camera.key
                    ] = (
                        now
                        + settings.recorder_restart_delay_seconds
                    )

                LOGGER.warning(
                    "Camera recorder recovery failed; "
                    "retrying in %s seconds: %s",
                    settings.recorder_restart_delay_seconds,
                    camera.name,
                )

                continue

            # First observation of a failed recorder.
            # Start the configured retry timer.
            if next_retry is None:
                with self._lock:
                    self._next_retry_at[
                        camera.key
                    ] = (
                        now
                        + settings.recorder_restart_delay_seconds
                    )

                LOGGER.warning(
                    "Camera recorder is not running; "
                    "retrying in %s seconds: %s",
                    settings.recorder_restart_delay_seconds,
                    camera.name,
                )

                continue

            if now < next_retry:
                continue

            LOGGER.warning(
                "Attempting camera recorder recovery: %s",
                camera.name,
            )

            self._start_camera(
                camera,
                settings,
                is_recovery=True,
            )

    def _start_camera(
        self,
        camera: CameraConfig,
        settings: CameraSettings,
        *,
        is_recovery: bool,
    ) -> None:
        with self._lock:
            existing = self._recorders.get(
                camera.key
            )

            if (
                existing is not None
                and existing.status()["running"]
            ):
                return

            recorder = CameraRecorder(
                camera,
                settings,
                on_fragment_closed=(
                    self._upload_service.submit
                ),
            )

            self._recorders[camera.key] = (
                recorder
            )

        try:
            recorder.start()

        except Exception:
            LOGGER.exception(
                "Unable to start recorder: %s",
                camera.name,
            )

            with self._lock:
                self._next_retry_at[
                    camera.key
                ] = (
                    monotonic()
                    + settings.recorder_restart_delay_seconds
                )

            return

        with self._lock:
            self._next_retry_at.pop(
                camera.key,
                None,
            )

            if is_recovery:
                self._recovery_pending_since[
                    camera.key
                ] = monotonic()