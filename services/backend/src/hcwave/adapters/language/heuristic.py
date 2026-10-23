"""Unicode-script language detector – fast, free and offline.

Malayalam and Devanagari scripts are unambiguous; Latin script defaults to
English with low confidence so the LLM can override it for romanised text.
"""

from __future__ import annotations

from hcwave.adapters.base import AdapterSettings
from hcwave.adapters.language.base import DetectedLanguage, LanguageDetector

# (first code point, last code point, language)
_SCRIPTS = [
    (0x0D00, 0x0D7F, "ml"),  # Malayalam
    (0x0900, 0x097F, "hi"),  # Devanagari (Hindi, Marathi...)
    (0x0B80, 0x0BFF, "ta"),  # Tamil
    (0x0C80, 0x0CFF, "kn"),  # Kannada
    (0x0C00, 0x0C7F, "te"),  # Telugu
]


class HeuristicSettings(AdapterSettings):
    """Settings for the heuristic detector."""

    latin_default: str = "en"


class ScriptHeuristicDetector(LanguageDetector):
    """Detects language from the dominant Unicode script."""

    settings_model = HeuristicSettings
    name = "heuristic"

    async def detect(self, text: str) -> DetectedLanguage:
        """Counts characters per script and picks the dominant one."""
        counts: dict[str, int] = {}
        letters = 0
        for char in text:
            if not char.isalpha():
                continue
            letters += 1
            code = ord(char)
            for start, end, lang in _SCRIPTS:
                if start <= code <= end:
                    counts[lang] = counts.get(lang, 0) + 1
                    break
        if not letters:
            return DetectedLanguage(self.config.latin_default, 0.0)
        if counts:
            lang, count = max(counts.items(), key=lambda item: item[1])
            if count / letters >= 0.3:
                return DetectedLanguage(lang, min(0.5 + count / letters / 2, 0.99))
        return DetectedLanguage(self.config.latin_default, 0.5)
