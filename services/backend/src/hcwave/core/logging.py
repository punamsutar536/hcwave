"""Structured logging with PII masking.

Logs are JSON lines in containers (collected by Container Insights / Log
Analytics) and plain text locally. A filter masks anything that looks like a
phone number so patient numbers never reach the log store in full.
"""

from __future__ import annotations

import json
import logging
import re
import sys
from datetime import UTC, datetime
from typing import Any

from hcwave.core.security import mask_phone

# +<country><number> or bare 10-13 digit runs.
_PHONE_PATTERN = re.compile(r"\+?\d{10,13}")
_RESERVED = set(vars(logging.makeLogRecord({})).keys()) | {"message", "asctime"}


class PiiMaskingFilter(logging.Filter):
    """Masks phone numbers in log messages and string extras."""

    def filter(self, record: logging.LogRecord) -> bool:
        """Rewrites the record in place and always lets it through."""
        record.msg = _PHONE_PATTERN.sub(lambda m: mask_phone(m.group()), str(record.msg))
        if record.args:
            record.args = tuple(
                _PHONE_PATTERN.sub(lambda m: mask_phone(m.group()), a) if isinstance(a, str) else a
                for a in (record.args if isinstance(record.args, tuple) else (record.args,))
            )
        return True


class JsonFormatter(logging.Formatter):
    """Formats records as one JSON object per line."""

    def format(self, record: logging.LogRecord) -> str:
        """Serialises the record, including any ``extra=`` fields."""
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for key, value in vars(record).items():
            if key not in _RESERVED and not key.startswith("_"):
                payload[key] = value if isinstance(value, (int, float, bool)) else str(value)
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(level: str = "INFO", fmt: str = "json") -> None:
    """Configures the root logger once for the process.

    Args:
        level: Log level name.
        fmt: ``json`` for containers, ``text`` for local development.
    """
    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(PiiMaskingFilter())
    if fmt == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())
    # Azure SDK HTTP logging is very chatty at INFO.
    logging.getLogger("azure").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
