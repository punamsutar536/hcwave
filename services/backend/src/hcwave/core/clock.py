"""Time helpers. All persisted timestamps are timezone-aware UTC."""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo


def utcnow() -> datetime:
    """Returns the current time as an aware UTC datetime."""
    return datetime.now(UTC)


def to_local(moment: datetime, timezone: str) -> datetime:
    """Converts an aware datetime to the given IANA timezone."""
    return moment.astimezone(ZoneInfo(timezone))


def format_local(moment: datetime, timezone: str, fmt: str = "%d %b %Y, %I:%M %p") -> str:
    """Formats an aware datetime in a hospital's local time for patients."""
    return to_local(moment, timezone).strftime(fmt)
