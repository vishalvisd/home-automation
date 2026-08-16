import logging

from collections.abc import Callable
from threading import Event, RLock, Thread
from typing import Any

from home_automation.config.camera_settings import CameraConfig


LOGGER = logging.getLogger(__name__)


class CameraStreamSource:
    """Reconnectable MJPEG source for one camera."""

    RECONNECT_DELAY_SECONDS = 2
    SAMPLE_POLL_MILLISECONDS = 500

    def __init__(
        self,
        camera: CameraConfig,
        gst: Any,
        on_frame: Callable[[Any], None],
    ) -> None:
        self._camera = camera
        self._gst = gst
        self._on_frame = on_frame

        self._lock = RLock()
        self._stop_event = Event()
        self._thread: Thread | None = None
        self._pipeline: Any = None

        self._connected = False
        self._has_connected = False
        self._reconnect_count = 0
        self._last_error: str | None = None

    def start(self) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return

            self._stop_event.clear()
            self._thread = Thread(
                target=self._run,
                name=f"camera-stream-{self._camera.key}",
                daemon=True,
            )
            self._thread.start()

    def stop(self) -> None:
        with self._lock:
            self._stop_event.set()
            pipeline = self._pipeline
            thread = self._thread

        # This also releases a blocked HTTP read immediately.
        if pipeline is not None:
            pipeline.set_state(self._gst.State.NULL)

        if thread is not None:
            thread.join(timeout=3)

        with self._lock:
            self._connected = False
            self._pipeline = None

    def status(self) -> dict[str, object]:
        with self._lock:
            return {
                "stream_connected": self._connected,
                "stream_reconnect_count": self._reconnect_count,
                "last_stream_error": self._last_error,
            }

    def _run(self) -> None:
        while not self._stop_event.is_set():
            pipeline = None

            try:
                pipeline = self._gst.parse_launch(
                    self._build_pipeline_description()
                )
                sink = pipeline.get_by_name("capture_sink")

                if sink is None:
                    raise RuntimeError(
                        "Unable to find camera capture appsink."
                    )

                with self._lock:
                    self._pipeline = pipeline

                result = pipeline.set_state(self._gst.State.PLAYING)
                if result == self._gst.StateChangeReturn.FAILURE:
                    raise RuntimeError(
                        "Camera capture pipeline failed to start."
                    )

                bus = pipeline.get_bus()

                while not self._stop_event.is_set():
                    sample = sink.emit(
                        "try-pull-sample",
                        self.SAMPLE_POLL_MILLISECONDS
                        * self._gst.MSECOND,
                    )

                    if sample is not None:
                        self._mark_connected()
                        buffer = sample.get_buffer()
                        if buffer is not None:
                            self._on_frame(buffer)

                    message = bus.timed_pop_filtered(
                        0,
                        self._gst.MessageType.ERROR
                        | self._gst.MessageType.EOS,
                    )
                    if message is None:
                        continue

                    if message.type == self._gst.MessageType.ERROR:
                        error, debug = message.parse_error()
                        self._mark_disconnected(
                            f"{error}: {debug or ''}".strip()
                        )
                    else:
                        self._mark_disconnected(
                            "Camera stream ended unexpectedly."
                        )
                    break

            except Exception as error:
                if not self._stop_event.is_set():
                    self._mark_disconnected(str(error))

            finally:
                if pipeline is not None:
                    pipeline.set_state(self._gst.State.NULL)

                with self._lock:
                    if self._pipeline is pipeline:
                        self._pipeline = None
                    self._connected = False

            if not self._stop_event.is_set():
                self._stop_event.wait(
                    timeout=self.RECONNECT_DELAY_SECONDS
                )

    def _build_pipeline_description(self) -> str:
        stream_url = (
            f"http://{self._camera.host}"
            f"{self._camera.stream_path}"
        )

        return (
            f'souphttpsrc location="{stream_url}" '
            f'is-live=true timeout=5 retries=0 '
            f'! multipartdemux '
            f'! image/jpeg '
            f'! appsink name=capture_sink '
            f'emit-signals=false sync=false '
            f'max-buffers=1 drop=true'
        )

    def _mark_connected(self) -> None:
        with self._lock:
            if self._connected:
                return

            self._connected = True
            if self._has_connected:
                self._reconnect_count += 1
                message = "Camera stream reconnected: %s"
            else:
                self._has_connected = True
                message = "Camera stream connected: %s"

        LOGGER.info(message, self._camera.name)

    def _mark_disconnected(self, error_message: str) -> None:
        with self._lock:
            was_connected = self._connected
            first_failure = self._last_error is None
            self._connected = False
            self._last_error = error_message

        # Do not spam logs while a camera remains offline. Log the actual
        # disconnect once, then stay quiet until it reconnects.
        if was_connected or first_failure:
            LOGGER.warning(
                "Camera stream disconnected [%s]: %s",
                self._camera.name,
                error_message,
            )