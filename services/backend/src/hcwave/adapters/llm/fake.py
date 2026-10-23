"""Deterministic, offline LLM for tests and laptop demos.

Implements tool calling so ``with_structured_output`` works exactly as with
real providers. Answers come from simple keyword rules – good enough to demo
the booking flow and run the test-suite without any cloud credentials.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Sequence
from typing import Any

from langchain_core.embeddings import Embeddings
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.utils.function_calling import convert_to_openai_tool

from hcwave.adapters.llm.base import LLMProvider
from hcwave.config.schema import LLMProfile

# Keyword -> intent, checked in order.
_INTENT_RULES: list[tuple[str, str]] = [
    (r"\b(human|agent|person|staff|call me)\b", "talk_to_human"),
    (r"\b(reschedul|change.*appointment|postpone)", "reschedule_appointment"),
    (r"\b(cancel)", "cancel_appointment"),
    (r"\b(book|appointment|consult|see a doctor)", "book_appointment"),
    (r"\b(available|availability|when is dr|timing of dr)", "doctor_availability"),
    (r"\b(package|health ?check|price|cost)", "package_prices"),
    (r"\b(insurance|cashless|tpa|claim)", "insurance"),
    (r"\b(where|location|direction|address|parking|open|timings?|hours)\b", "timings_location"),
    (r"\b(department|service|speciality|specialty)", "departments_services"),
    (r"\b(hi|hello|hey|namaste|menu)\b", "greeting"),
]
_NEGATIVE = re.compile(
    r"\b(rude|dirty|wait|late|expensive|bad|worst|delay|billing|overcharg)", re.I
)


def _intent_args(system: str, text: str) -> dict[str, Any]:
    lowered = text.lower()
    for pattern, intent in _INTENT_RULES:
        if re.search(pattern, lowered):
            return {"intent": intent, "confidence": 0.9, "language": "en", "entities": {}}
    return {"intent": "unknown", "confidence": 0.3, "language": "en", "entities": {}}


def _feedback_args(system: str, text: str) -> dict[str, Any]:
    lowered = text.lower()
    categories = []
    for word, category in [
        ("wait", "waiting_time"),
        ("bill", "billing"),
        ("rude", "staff_behaviour"),
        ("dirty", "cleanliness"),
        ("doctor", "doctor_communication"),
    ]:
        if word in lowered:
            categories.append(category)
    negative = bool(_NEGATIVE.search(text))
    return {
        "sentiment": "negative" if negative else "positive",
        "categories": categories or ["other"],
        "summary": text[:120],
    }


def _faq_args(system: str, text: str) -> dict[str, Any]:
    # The system prompt contains numbered context passages; answer with the first.
    match = re.search(r"\[1\][^\n]*\n(.+?)(?:\n\[2\]|\Z)", system, re.S)
    if not match:
        return {"answer": "", "confident": False, "source_ids": []}
    return {"answer": match.group(1).strip()[:600], "confident": True, "source_ids": ["1"]}


_RULES = {"IntentResult": _intent_args, "FeedbackTags": _feedback_args, "FaqAnswer": _faq_args}


class RuleBasedChatModel(BaseChatModel):
    """Chat model that answers tool calls with keyword rules."""

    tool_name: str | None = None

    @property
    def _llm_type(self) -> str:
        return "hcwave-rule-based"

    def bind_tools(self, tools: Sequence[Any], **kwargs: Any) -> RuleBasedChatModel:  # type: ignore[override]
        """Remembers the requested tool so the next call answers it."""
        name = convert_to_openai_tool(tools[0])["function"]["name"]
        return self.model_copy(update={"tool_name": name})

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        text = str(messages[-1].content)
        system = "\n".join(str(m.content) for m in messages if m.type == "system")
        if self.tool_name:
            args = _RULES.get(self.tool_name, lambda _s, _t: {})(system, text)
            message = AIMessage(
                content="", tool_calls=[{"name": self.tool_name, "args": args, "id": "fake-1"}]
            )
        else:
            message = AIMessage(content=f"(offline model) {text[:200]}")
        return ChatResult(generations=[ChatGeneration(message=message)])


class HashEmbeddings(Embeddings):
    """Deterministic bag-of-words hash embeddings (tests only)."""

    def __init__(self, dimensions: int = 64) -> None:
        self.dimensions = dimensions

    def _embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        for token in re.findall(r"\w+", text.lower()):
            vector[int(hashlib.md5(token.encode()).hexdigest(), 16) % self.dimensions] += 1.0  # noqa: S324
        norm = sum(v * v for v in vector) ** 0.5 or 1.0
        return [v / norm for v in vector]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embeds documents."""
        return [self._embed(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        """Embeds a query."""
        return self._embed(text)


class FakeProvider(LLMProvider):
    """Offline provider; never use in production."""

    name = "fake"
    system = "hcwave.fake"

    def chat_model(self, profile: LLMProfile) -> BaseChatModel:
        """Returns the rule-based model."""
        return RuleBasedChatModel()

    def embeddings(self, profile: LLMProfile) -> Embeddings:
        """Returns hash embeddings of the profile's dimension."""
        return HashEmbeddings(profile.dimensions or 64)
