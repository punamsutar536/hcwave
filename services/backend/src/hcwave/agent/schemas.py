"""Structured LLM outputs used by the assistant."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Intent = Literal[
    "book_appointment",
    "reschedule_appointment",
    "cancel_appointment",
    "doctor_availability",
    "departments_services",
    "package_prices",
    "timings_location",
    "insurance",
    "reports",
    "talk_to_human",
    "greeting",
    "medical_question",
    "out_of_scope",
    "unknown",
]

FAQ_INTENTS = frozenset(
    {"departments_services", "package_prices", "timings_location", "insurance", "reports"}
)


class IntentResult(BaseModel):
    """Intent classification of a free-text message."""

    intent: Intent
    confidence: float = Field(ge=0.0, le=1.0)
    language: str = "en"
    entities: dict[str, str] = Field(default_factory=dict)


class FaqAnswer(BaseModel):
    """Grounded FAQ answer from hospital content."""

    answer: str = ""
    confident: bool = False
    source_ids: list[str] = Field(default_factory=list)
