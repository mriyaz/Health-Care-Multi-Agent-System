import logging  # Python standard logging library
from pythonjsonlogger import jsonlogger  # Formatter that outputs log records as JSON
from api.settings import (
    Settings,
)  # Settings provides log level and other environment metadata


def configure_logging(settings: Settings) -> None:
    root = logging.getLogger()  # Get the root logger so configuration applies app-wide
    root.handlers.clear()  # Remove any default handlers to avoid duplicate logs
    root.setLevel(
        settings.log_level.upper()
    )  # Set root log level (e.g. INFO/DEBUG) from settings

    handler = logging.StreamHandler()  # Send logs to stdout/stderr (container-friendly)
    formatter = jsonlogger.JsonFormatter(  # Emit JSON with a predictable set of keys
        "%(asctime)s %(levelname)s %(name)s %(message)s %(request_id)s %(method)s %(path)s %(status_code)s %(duration_ms)s"
    )
    handler.setFormatter(formatter)  # Attach the JSON formatter to the stream handler
    root.addHandler(handler)  # Register the handler so all logs flow through it


def get_logger() -> logging.Logger:
    return logging.getLogger(
        "healthos.api"
    )  # Return a named logger used throughout the API code
