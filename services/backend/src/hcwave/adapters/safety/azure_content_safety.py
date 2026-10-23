"""Azure AI Content Safety: text analysis plus Prompt Shields."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from typing import Any

import httpx

from hcwave.adapters.base import AdapterContext, AdapterSettings
from hcwave.adapters.safety.base import ContentSafety, SafetyVerdict

_log = logging.getLogger(__name__)
_SCOPE = "https://cognitiveservices.azure.com/.default"


class AzureContentSafetySettings(AdapterSettings):
    """Settings for Azure AI Content Safety."""

    endpoint: str
    api_key: str = ""
    api_version: str = "2024-09-01"
    timeout_seconds: float = 5.0


class AzureContentSafety(ContentSafety):
    """Calls ``text:analyze`` and ``text:shieldPrompt`` in parallel."""

    settings_model = AzureContentSafetySettings
    name = "azure_content_safety"

    def __init__(self, raw_settings: Mapping[str, Any], ctx: AdapterContext) -> None:
        super().__init__(raw_settings, ctx)
        self._http = httpx.AsyncClient(timeout=self.config.timeout_seconds)

    async def _headers(self) -> dict[str, str]:
        if self.config.api_key:
            return {"Ocp-Apim-Subscription-Key": self.config.api_key}
        return {"Authorization": f"Bearer {await self.ctx.credentials.get_token(_SCOPE)}"}

    async def _post(self, operation: str, body: dict[str, Any]) -> dict[str, Any]:
        response = await self._http.post(
            f"{self.config.endpoint.rstrip('/')}/contentsafety/text:{operation}",
            params={"api-version": self.config.api_version},
            json=body,
            headers=await self._headers(),
        )
        response.raise_for_status()
        return response.json()

    async def screen(
        self, text: str, block_severity: int, check_prompt_attack: bool
    ) -> SafetyVerdict:
        """Screens text; raises on service errors so the caller decides fail-open/closed."""
        calls = [self._post("analyze", {"text": text[:10000], "outputType": "FourSeverityLevels"})]
        if check_prompt_attack:
            calls.append(self._post("shieldPrompt", {"userPrompt": text[:10000], "documents": []}))
        results = await asyncio.gather(*calls)
        severities = {
            item["category"]: int(item.get("severity", 0))
            for item in results[0].get("categoriesAnalysis", [])
        }
        attack = bool(
            len(results) > 1
            and results[1].get("userPromptAnalysis", {}).get("attackDetected", False)
        )
        self_harm = severities.get("SelfHarm", 0) >= 2
        harmful = any(sev >= block_severity for cat, sev in severities.items() if cat != "SelfHarm")
        return SafetyVerdict(
            blocked=harmful or attack,
            prompt_attack=attack,
            self_harm=self_harm,
            severities=severities,
        )

    async def aclose(self) -> None:
        """Closes the HTTP client."""
        await self._http.aclose()
