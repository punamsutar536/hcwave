"""Small, dependency-free security helpers.

Covers phone-number normalisation and masking (so logs never hold full
numbers), opaque link tokens, HMAC hashing of OTPs and signed cookies.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import secrets
import time
from typing import Any

_NON_DIGITS = re.compile(r"[^\d+]")


def normalize_phone(raw: str, default_country_code: str = "91") -> str:
    """Normalises a phone number to E.164 (``+<country><number>``).

    Args:
        raw: Number as received, e.g. ``"98470 12345"`` or ``"919847012345"``.
        default_country_code: Prefix applied to 10-digit national numbers.

    Returns:
        The E.164 string, e.g. ``"+919847012345"``.
    """
    cleaned = _NON_DIGITS.sub("", raw or "")
    if cleaned.startswith("+"):
        return cleaned
    if cleaned.startswith("00"):
        return "+" + cleaned[2:]
    if len(cleaned) == 10:
        return f"+{default_country_code}{cleaned}"
    if cleaned.startswith("0") and len(cleaned) == 11:
        return f"+{default_country_code}{cleaned[1:]}"
    return "+" + cleaned


def mask_phone(phone: str) -> str:
    """Masks all but the last four digits of a phone number for logs."""
    if not phone:
        return phone
    return phone[:3] + "*" * max(len(phone) - 7, 0) + phone[-4:]


def new_link_token() -> str:
    """Returns a 256-bit URL-safe random token for report links."""
    return secrets.token_urlsafe(32)


def sha256_hex(value: str) -> str:
    """Returns the SHA-256 hex digest of ``value`` (used to store link tokens)."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def hmac_hex(key: str, value: str) -> str:
    """Returns an HMAC-SHA256 hex digest (used to store OTP codes)."""
    return hmac.new(key.encode("utf-8"), value.encode("utf-8"), hashlib.sha256).hexdigest()


def constant_time_equals(left: str, right: str) -> bool:
    """Compares two strings without leaking timing information."""
    return hmac.compare_digest(left.encode("utf-8"), right.encode("utf-8"))


def new_otp(length: int = 6) -> str:
    """Returns a numeric one-time password from a CSPRNG."""
    return "".join(secrets.choice("0123456789") for _ in range(length))


def sign_payload(key: str, payload: dict[str, Any], ttl_seconds: int) -> str:
    """Creates a compact signed, expiring token (``<b64 json>.<b64 sig>``).

    Args:
        key: HMAC secret.
        payload: JSON-serialisable claims.
        ttl_seconds: Lifetime from now.

    Returns:
        The token string.
    """
    body = dict(payload, exp=int(time.time()) + ttl_seconds)
    raw = base64.urlsafe_b64encode(json.dumps(body, separators=(",", ":")).encode()).rstrip(b"=")
    sig = base64.urlsafe_b64encode(hmac.new(key.encode(), raw, hashlib.sha256).digest()).rstrip(
        b"="
    )
    return f"{raw.decode()}.{sig.decode()}"


def verify_payload(key: str, token: str) -> dict[str, Any] | None:
    """Verifies a token created by :func:`sign_payload`.

    Args:
        key: HMAC secret.
        token: Token string.

    Returns:
        The claims if the signature is valid and the token has not expired,
        otherwise ``None``.
    """
    try:
        raw, sig = token.split(".", 1)
    except ValueError:
        return None
    expected = base64.urlsafe_b64encode(
        hmac.new(key.encode(), raw.encode(), hashlib.sha256).digest()
    ).rstrip(b"=")
    if not hmac.compare_digest(expected, sig.encode()):
        return None
    padded = raw + "=" * (-len(raw) % 4)
    try:
        claims = json.loads(base64.urlsafe_b64decode(padded))
    except (ValueError, json.JSONDecodeError):
        return None
    if int(claims.get("exp", 0)) < int(time.time()):
        return None
    return claims
