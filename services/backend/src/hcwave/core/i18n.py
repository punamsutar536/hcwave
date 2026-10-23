"""Localised bot strings loaded from ``config/locales/<lang>.yaml``.

Native speakers review every string before go-live (Malayalam, Hindi,
English to start), so wording lives in YAML, never in code.
"""

from __future__ import annotations

from typing import Any

from hcwave.config.schema import Settings


class _SafeDict(dict[str, Any]):
    """Leaves unknown ``{placeholders}`` untouched instead of raising."""

    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def translate(settings: Settings, language: str, key: str, **params: Any) -> str:
    """Returns the localised string for ``key``.

    Falls back to the default language, then English, then the key itself.

    Args:
        settings: Loaded settings (holds the locale tables).
        language: Desired language code, e.g. ``ml``.
        key: String identifier, e.g. ``booking.choose_department``.
        **params: Values for ``{placeholders}`` in the string.

    Returns:
        The formatted string.
    """
    for lang in (language, settings.language.default, "en"):
        text = settings.locales.get(lang, {}).get(key)
        if text:
            return text.format_map(_SafeDict(params))
    return key
