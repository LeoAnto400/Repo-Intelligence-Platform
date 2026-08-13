import logging
import sys

from src.core.config import settings

_CONFIGURED = False


def configure_logging() -> None:
    """
    Configure the root logger so every module-level ``logging.getLogger(__name__)``
    call in the app actually emits output.

    Uvicorn's own ``LOGGING_CONFIG`` only sets up the ``uvicorn``/``uvicorn.access``/
    ``uvicorn.error`` loggers, not the root logger. Without this, application-level
    ``logger.info``/``logger.debug`` calls throughout the codebase are silently
    dropped by Python's logging "last resort" handler (which only surfaces
    WARNING and above), making it look like the app isn't logging anything even
    though the logging calls are already in place.
    """
    global _CONFIGURED
    if _CONFIGURED:
        return

    root_logger = logging.getLogger()
    root_logger.setLevel(settings.LOG_LEVEL)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    root_logger.addHandler(handler)

    _CONFIGURED = True
