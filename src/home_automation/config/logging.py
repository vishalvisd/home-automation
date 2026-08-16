import logging


class IgnorePollingRequestsFilter(logging.Filter):
    """Hide repetitive frontend polling from Uvicorn access logs."""

    IGNORED_PATHS = (
        "/api/watering/status",
        "/api/cameras/recording/status",
    )

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()

        return not any(
            path in message
            for path in self.IGNORED_PATHS
        )


def configure_logging() -> None:
    """Configure application and Uvicorn logging."""

    # Suppress repetitive frontend polling.
    logging.getLogger("uvicorn.access").addFilter(
        IgnorePollingRequestsFilter()
    )

    # Send home-automation application logs through the same
    # handler used by Uvicorn.
    uvicorn_logger = logging.getLogger("uvicorn")
    application_logger = logging.getLogger("home_automation")

    application_logger.setLevel(logging.INFO)
    application_logger.handlers = (
        uvicorn_logger.handlers.copy()
    )
    application_logger.propagate = False