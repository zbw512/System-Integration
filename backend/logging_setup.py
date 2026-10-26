"""Logging configuration.

Logs go to stdout (captured by the process supervisor) and optionally to a file.
Every record carries the current ``request_id`` so a failure reported to the
frontend can be correlated with a server-side log line.

The log format deliberately avoids printing absolute filesystem paths; path
information must never reach an API response either.
"""

from __future__ import annotations

import logging
import sys

from flask import g, has_app_context

from config import Config

LOG_FORMAT = "%(asctime)s %(levelname)-8s [%(request_id)s] %(name)s: %(message)s"
DATE_FORMAT = "%Y-%m-%dT%H:%M:%S%z"

_HANDLER_FLAG = "_learning_state_handler"

_LEVELS = {
    "CRITICAL": logging.CRITICAL,
    "ERROR": logging.ERROR,
    "WARNING": logging.WARNING,
    "INFO": logging.INFO,
    "DEBUG": logging.DEBUG,
}


class RequestIdFilter(logging.Filter):
    """Inject ``request_id`` into every record, outside a request too."""

    def filter(self, record: logging.LogRecord) -> bool:
        request_id = "-"
        if has_app_context():
            request_id = getattr(g, "request_id", "-")
        record.request_id = request_id
        return True


def resolve_level(name: str) -> int:
    """Map a level name to a logging level, defaulting to ``INFO``."""
    return _LEVELS.get(str(name).upper(), logging.INFO)


def configure_logging(config: Config, *, force: bool = False) -> None:
    """Install stdout (and optional file) handlers on the root logger.

    Idempotent: calling it twice with the same configuration only updates the
    level, so imports inside tests do not duplicate handlers.
    """
    root = logging.getLogger()
    level = resolve_level(config.log_level)

    existing = [h for h in root.handlers if getattr(h, _HANDLER_FLAG, False)]
    if existing and not force:
        root.setLevel(level)
        return

    for handler in existing:
        root.removeHandler(handler)

    stream_handler = logging.StreamHandler(stream=sys.stdout)
    stream_handler.setFormatter(logging.Formatter(LOG_FORMAT, DATE_FORMAT))
    stream_handler.addFilter(RequestIdFilter())
    setattr(stream_handler, _HANDLER_FLAG, True)
    root.addHandler(stream_handler)

    if config.log_file:
        file_handler = logging.FileHandler(config.log_file, encoding="utf-8")
        file_handler.setFormatter(logging.Formatter(LOG_FORMAT, DATE_FORMAT))
        file_handler.addFilter(RequestIdFilter())
        setattr(file_handler, _HANDLER_FLAG, True)
        root.addHandler(file_handler)

    root.setLevel(level)
