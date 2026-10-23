"""Content safety contract: harmful content and prompt-injection screening.

Runs before any LLM call, on top of the system-prompt rules.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field

from hcwave.adapters.base import Adapter


@dataclass(frozen=True)
class SafetyVerdict:
    """Screening result.

    Attributes:
        blocked: True when the message must not reach the LLM.
        prompt_attack: True when Prompt Shields flagged a jailbreak attempt.
        self_harm: True for self-harm signals – handled as a crisis (helpline
            reply and human handover), never as a plain refusal.
        severities: Category -> severity for audit.
    """

    blocked: bool = False
    prompt_attack: bool = False
    self_harm: bool = False
    severities: dict[str, int] = field(default_factory=dict)


class ContentSafety(Adapter, abc.ABC):
    """Abstract content safety service."""

    @abc.abstractmethod
    async def screen(
        self, text: str, block_severity: int, check_prompt_attack: bool
    ) -> SafetyVerdict:
        """Screens patient text."""
