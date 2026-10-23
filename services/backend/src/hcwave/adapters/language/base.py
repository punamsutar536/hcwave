"""Language detection contract (Malayalam, Hindi and English to start)."""

from __future__ import annotations

import abc
from dataclasses import dataclass

from hcwave.adapters.base import Adapter


@dataclass(frozen=True)
class DetectedLanguage:
    """Detection result.

    Attributes:
        code: ISO 639-1 code (``ml``, ``hi``, ``en``...).
        confidence: 0..1. Romanised Malayalam/Hindi typed in Latin script
            often scores low; the intent model then refines the language.
    """

    code: str
    confidence: float


class LanguageDetector(Adapter, abc.ABC):
    """Abstract language detector."""

    @abc.abstractmethod
    async def detect(self, text: str) -> DetectedLanguage:
        """Detects the language of ``text``."""
