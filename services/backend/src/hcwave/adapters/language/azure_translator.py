"""Azure AI Translator language detector.

Uses the resource's custom sub-domain endpoint (required with private
endpoints and Entra ID auth). Falls back to the script heuristic on errors.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

import httpx

from hcwave.adapters.base import AdapterContext, AdapterSettings
from hcwave.adapters.language.base import DetectedLanguage, LanguageDetector
from hcwave.adapters.language.heuristic import ScriptHeuristicDetector

_log = logging.getLogger(__name__)
_SCOPE = "https://cognitiveservices.azure.com/.default"


class AzureTranslatorSettings(AdapterSettings):
    """Settings for Azure AI Translator.

    Attributes:
        endpoint: ``https://<name>.cognitiveservices.azure.com/translator/text/v3.0``.
        api_key: Optional key; empty = Entra ID.
        region: Resource region (needed with keys).
    """

    endpoint: str
    api_key: str = ""
    region: str = ""


class AzureTranslatorDetector(LanguageDetector):
    """Detects language with the Translator ``/detect`` API."""

    settings_model = AzureTranslatorSettings
    name = "azure_translator"

    def __init__(self, raw_settings: Mapping[str, Any], ctx: AdapterContext) -> None:
        super().__init__(raw_settings, ctx)
        self._fallback = ScriptHeuristicDetector({}, ctx)
        self._http = httpx.AsyncClient(timeout=5)

    async def _headers(self) -> dict[str, str]:
        if self.config.api_key:
            headers = {"Ocp-Apim-Subscription-Key": self.config.api_key}
            if self.config.region:
                headers["Ocp-Apim-Subscription-Region"] = self.config.region
            return headers
        return {"Authorization": f"Bearer {await self.ctx.credentials.get_token(_SCOPE)}"}

    async def detect(self, text: str) -> DetectedLanguage:
        """Calls ``/detect``; uses the script heuristic if the call fails."""
        script = await self._fallback.detect(text)
        if script.code != "en":  # Non-Latin scripts are already unambiguous.
            return script
        try:
            response = await self._http.post(
                f"{self.config.endpoint}/detect",
                params={"api-version": "3.0"},
                json=[{"Text": text[:500]}],
                headers=await self._headers(),
            )
            response.raise_for_status()
            result = response.json()[0]
            return DetectedLanguage(result["language"], float(result.get("score", 0.5)))
        except (httpx.HTTPError, KeyError, IndexError, ValueError):
            _log.warning("translator detect failed; using script heuristic")
            return script

    async def aclose(self) -> None:
        """Closes the HTTP client."""
        await self._http.aclose()
