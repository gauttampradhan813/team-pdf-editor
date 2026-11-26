"""Logging configuration for the application.

Uvicorn configures its own loggers when the server starts, so this module
only owns the ``app`` logger hierarchy and the root logger.
"""

from __future__ import annotations

import logging
import logging.config

LOGGING_CONFIG = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "standard": {
            "format": "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
            "datefmt": "%Y-%m-%d %H:%M:%S",
        },
        "access": {
            "format": "%(asctime)s | %(levelname)-8s | %(client_addr)s "
            '"%(request_line)s" %(status_code)s',
            "datefmt": "%Y-%m-%d %H:%M:%S",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "standard",
            "stream": "ext://sys.stdout",
        },
    },
    "root": {
        "level": "INFO",
        "handlers": ["console"],
    },
    "loggers": {
        "app": {
            "level": "INFO",
            "handlers": ["console"],
            "propagate": False,
        },
        "app.errors": {
            "level": "INFO",
            "handlers": ["console"],
            "propagate": False,
        },
    },
}


def configure_logging(level: str = "INFO") -> None:
    """Apply the logging configuration.

    Args:
        level: Root/app log level name, e.g. ``INFO`` or ``DEBUG``.
    """
    normalized = (level or "INFO").upper()
    LOGGING_CONFIG["root"]["level"] = normalized
    for logger_name, config in LOGGING_CONFIG["loggers"].items():
        config["level"] = normalized

    logging.config.dictConfig(LOGGING_CONFIG)
    logging.getLogger("app").debug("Logging configured at level %s", normalized)
