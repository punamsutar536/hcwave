"""No-op content safety for local development."""

from __future__ import annotations

from hcwave.adapters.safety.base import ContentSafety, SafetyVerdict


class NoopSafety(ContentSafety):
    """Allows everything."""

    name = "none"

    async def screen(
        self, text: str, block_severity: int, check_prompt_attack: bool
    ) -> SafetyVerdict:
        """Returns an empty verdict."""
        return SafetyVerdict()
