"""Structured logging.

Single-line, JSON-ish records (timestamp, level, logger, message) plus any
extra fields attached to the log record, backed by the stdlib logging module.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any

# Keys managed by the stdlib formatter machinery; never surfaced as fields.
_RESERVED_KEYS = {
    "args",
    "asctime",
    "created",
    "exc_info",
    "exc_text",
    "filename",
    "funcName",
    "levelname",
    "levelno",
    "lineno",
    "message",
    "module",
    "msecs",
    "msg",
    "name",
    "pathname",
    "process",
    "processName",
    "relativeCreated",
    "stack_info",
    "taskName",
    "thread",
    "threadName",
}

_STRUCTURED_HANDLER = "_pka_structured"


class JsonLineFormatter(logging.Formatter):
    """Format log records as one-line JSON-ish objects."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "location": f"{record.pathname}:{record.lineno}",
        }
        for key, value in record.__dict__.items():
            if key in _RESERVED_KEYS or key.startswith("_"):
                continue
            if isinstance(value, (str, int, float, bool)) or value is None:
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


def setup_logging(level: int = logging.INFO) -> None:
    """Attach the structured console handler to the root logger once."""
    root = logging.getLogger()
    if any(getattr(h, _STRUCTURED_HANDLER, False) for h in root.handlers):
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonLineFormatter())
    setattr(handler, _STRUCTURED_HANDLER, True)
    root.addHandler(handler)
    root.setLevel(level)


def get_logger(name: str) -> logging.Logger:
    """Return a module-scoped logger using the structured configuration."""
    return logging.getLogger(name)