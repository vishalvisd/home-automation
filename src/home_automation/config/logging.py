import logging


class IgnoreWateringStatusFilter(logging.Filter):
    """Hide repetitive frontend polling from Uvicorn access logs."""

    def filter(self, record: logging.LogRecord) -> bool:
        return "/api/watering/status" not in record.getMessage()


def configure_logging() -> None:
    """Configure application-specific logging filters."""

    logging.getLogger("uvicorn.access").addFilter(
        IgnoreWateringStatusFilter()
    )