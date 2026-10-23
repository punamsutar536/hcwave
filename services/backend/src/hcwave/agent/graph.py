"""LangGraph orchestration of one inbound patient message.

    consent ─▶ emergency ─▶ safety ─▶ language ─▶ router ─┬─▶ flow ──────┐
       │           │           │                          ├─▶ menu       │
       ▼           ▼           ▼                          ├─▶ handover   │
      END         END     END/handover                    └─▶ classify ◀─┘
                                                               │
                                     flow / faq / menu / handover / static reply

Order matters: STOP is honoured before anything else, emergency keywords are
answered before any AI call, and content safety (incl. Prompt Shields) runs
before the LLM sees the text. Low confidence always means a human takes over.
"""

from __future__ import annotations

import logging
import operator
from typing import Annotated, Any, TypedDict

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph

from hcwave.adapters.messaging.base import OutboundKind, OutboundMessage
from hcwave.agent import flows
from hcwave.agent.context import TurnContext
from hcwave.agent.schemas import FAQ_INTENTS, FaqAnswer, IntentResult
from hcwave.db.audit import record_audit
from hcwave.db.models import ConversationStatus
from hcwave.domain.consent import is_start, is_stop, record_consent
from hcwave.domain.conversations import request_handover

_log = logging.getLogger(__name__)
_LANGUAGE_NAMES = {
    "en": "English",
    "ml": "Malayalam",
    "hi": "Hindi",
    "ta": "Tamil",
    "kn": "Kannada",
    "te": "Telugu",
}


class TurnState(TypedDict, total=False):
    """Graph state for one turn."""

    text: str
    reply_id: str | None
    replies: Annotated[list[OutboundMessage], operator.add]
    route: str
    intent: str | None
    confidence: float | None
    faq_query: str | None
    handover_reason: str | None


def _ctx(config: RunnableConfig) -> TurnContext:
    return config["configurable"]["ctx"]


def _normalise(text: str) -> str:
    return " ".join(text.casefold().split())


# --------------------------------------------------------------------------- #
# Gates
# --------------------------------------------------------------------------- #
async def consent_node(state: TurnState, config: RunnableConfig) -> dict[str, Any]:
    """STOP/START keywords and first-message opt-in."""
    ctx = _ctx(config)
    text, settings, conversation = state.get("text", ""), ctx.settings, ctx.conversation
    if is_stop(text, settings):
        await record_consent(
            ctx.session,
            conversation,
            opt_in=False,
            source="keyword",
            evidence=text,
            patients=ctx.patients,
        )
        notice = OutboundMessage(
            kind=OutboundKind.TEXT,
            text=ctx.t("consent.opted_out"),
            metadata={"consent_notice": True},
        )
        return {"replies": [notice], "route": "end", "intent": "opt_out"}
    if is_start(text, settings):
        await record_consent(
            ctx.session,
            conversation,
            opt_in=True,
            source="keyword",
            evidence=text,
            patients=ctx.patients,
        )
        return {"replies": [ctx.text("consent.opted_in")], "route": "end", "intent": "opt_in"}
    if conversation.consent_status == "opted_out":
        notice = OutboundMessage(
            kind=OutboundKind.TEXT,
            text=ctx.t("consent.opted_out"),
            metadata={"consent_notice": True},
        )
        return {"replies": [notice], "route": "end"}
    if conversation.consent_status == "unknown" and settings.conversation.first_message_is_opt_in:
        await record_consent(
            ctx.session,
            conversation,
            opt_in=True,
            source="first_message",
            evidence=text[:200],
            patients=ctx.patients,
        )
    return {"route": "next"}


def detect_emergency(ctx: TurnContext, text: str) -> str | None:
    """Returns the language of the matched emergency keyword, or None.

    Runs before language detection, so the keyword's own language decides the
    reply language (a Malayalam keyword gets the Malayalam emergency reply).
    """
    normalised = _normalise(text)
    for language, keywords in ctx.hospital.emergency.keywords.items():
        if any(_normalise(keyword) in normalised for keyword in keywords):
            return language
    return None


def emergency_reply(ctx: TurnContext, language: str | None = None) -> OutboundMessage:
    """The hospital's emergency message, preferably in ``language``."""
    messages = ctx.hospital.emergency.message
    text = (
        messages.get(language or "")
        or messages.get(ctx.language)
        or messages.get(ctx.hospital.default_language)
        or next(iter(messages.values()))
    )
    return OutboundMessage(kind=OutboundKind.TEXT, text=text, metadata={"emergency": True})


async def emergency_node(state: TurnState, config: RunnableConfig) -> dict[str, Any]:
    """Emergency keywords: immediate reply with emergency number, then staff."""
    ctx = _ctx(config)
    language = detect_emergency(ctx, state.get("text", ""))
    if language is None:
        return {"route": "next"}
    # Romanised keywords sit in the ml/hi lists; keep the conversation language
    # in sync so staff and follow-up messages use it too.
    if language in ctx.hospital.languages:
        ctx.conversation.language = language
    request_handover(ctx.conversation, "emergency")
    await record_audit(
        ctx.session,
        ctx.hospital.id,
        "assistant.emergency",
        entity_type="conversation",
        entity_id=ctx.conversation.id,
    )
    return {
        "replies": [emergency_reply(ctx, language)],
        "route": "end",
        "intent": "emergency",
        "handover_reason": "emergency",
    }


async def safety_node(state: TurnState, config: RunnableConfig) -> dict[str, Any]:
    """Content Safety + Prompt Shields before any LLM call."""
    ctx = _ctx(config)
    text = state.get("text", "")
    if not text or state.get("reply_id"):
        return {"route": "next"}  # button/list replies carry no free text
    cfg = ctx.settings.safety
    try:
        verdict = await ctx.services.container.safety.screen(
            text[: ctx.settings.guardrails.max_input_chars],
            cfg.block_severity,
            cfg.prompt_shields_enabled,
        )
    except Exception:  # noqa: BLE001 - decide fail-open/closed by config
        _log.exception("content safety unavailable")
        if cfg.fail_open:
            return {"route": "next"}
        return {"route": "handover", "handover_reason": "safety_unavailable"}
    if verdict.self_harm:
        request_handover(ctx.conversation, "self_harm")
        return {
            "replies": [ctx.text("safety.self_harm")],
            "route": "end",
            "intent": "self_harm",
            "handover_reason": "self_harm",
        }
    if verdict.blocked:
        await record_audit(
            ctx.session,
            ctx.hospital.id,
            "assistant.blocked",
            entity_type="conversation",
            entity_id=ctx.conversation.id,
            prompt_attack=verdict.prompt_attack,
        )
        return {"replies": [ctx.text("safety.blocked")], "route": "end", "intent": "blocked"}
    return {"route": "next"}


async def language_node(state: TurnState, config: RunnableConfig) -> dict[str, Any]:
    """Detects the language when the script makes it unambiguous."""
    ctx = _ctx(config)
    text = state.get("text", "")
    if text and not state.get("reply_id"):
        detected = await ctx.services.container.language.detect(text)
        if detected.confidence >= 0.75 and detected.code in ctx.hospital.languages:
            ctx.conversation.language = detected.code
            ctx.audit["language_confident"] = True
    return {}


# --------------------------------------------------------------------------- #
# Routing and handlers
# --------------------------------------------------------------------------- #
async def router_node(state: TurnState, config: RunnableConfig) -> dict[str, Any]:
    """Chooses between flows, menu, handover and the intent classifier."""
    ctx = _ctx(config)
    text = _normalise(state.get("text", ""))
    keywords = ctx.settings.conversation
    if not ctx.hospital.features.assistant:
        return {"route": "handover", "handover_reason": "assistant_disabled"}
    if state.get("reply_id") or ctx.conversation.flow:
        return {"route": "flow"}
    if text in {k.casefold() for k in keywords.menu_keywords}:
        return {"route": "menu"}
    if text in {k.casefold() for k in keywords.human_keywords}:
        return {"route": "handover", "handover_reason": "requested"}
    return {"route": "classify"}


def _apply_flow_result(result: flows.FlowResult) -> dict[str, Any]:
    if result.handover_reason:
        return {
            "replies": result.replies,
            "route": "handover",
            "handover_reason": result.handover_reason,
        }
    if result.faq_query:
        return {"replies": result.replies, "route": "faq", "faq_query": result.faq_query}
    if result.fallthrough:
        return {"replies": result.replies, "route": "classify"}
    return {"replies": result.replies, "route": "end"}


async def flow_node(state: TurnState, config: RunnableConfig) -> dict[str, Any]:
    """Runs one step of the active flow or a global button payload."""
    ctx = _ctx(config)
    result = await flows.handle_flow_input(ctx, state.get("text", ""), state.get("reply_id"))
    return _apply_flow_result(result)


async def menu_node(state: TurnState, config: RunnableConfig) -> dict[str, Any]:
    """Shows the main menu."""
    return {"replies": flows.main_menu(_ctx(config)).replies, "route": "end", "intent": "greeting"}


async def classify_node(state: TurnState, config: RunnableConfig) -> dict[str, Any]:
    """Classifies free text with the small model and dispatches by intent."""
    ctx = _ctx(config)
    text = state.get("text", "")
    if not text:
        return {"route": "menu"}
    system = ctx.settings.prompts["intent_classifier"]["system"].format(hospital=ctx.hospital.name)
    try:
        result = await ctx.services.container.llm.structured(
            "intent", IntentResult, system, text[: ctx.settings.guardrails.max_input_chars]
        )
    except Exception:  # noqa: BLE001 - an LLM outage hands over, never drops the patient
        _log.exception("intent classification failed")
        return {"route": "handover", "handover_reason": "llm_unavailable"}

    if not ctx.audit.get("language_confident") and result.language in ctx.hospital.languages:
        ctx.conversation.language = result.language
    update: dict[str, Any] = {"intent": result.intent, "confidence": result.confidence}
    if (
        result.confidence < ctx.settings.guardrails.intent_confidence_threshold
        or result.intent == "unknown"
    ):
        return {**update, "route": "handover", "handover_reason": "low_confidence"}

    intent = result.intent
    if intent in FAQ_INTENTS:
        return {**update, "route": "faq", "faq_query": text}
    if intent == "talk_to_human":
        return {**update, "route": "handover", "handover_reason": "requested"}
    if intent == "greeting":
        return {**update, "route": "menu"}
    if intent == "medical_question":
        return {**update, "replies": [ctx.text("medical.refusal")], "route": "end"}
    if intent == "out_of_scope":
        return {**update, "replies": [ctx.text("out_of_scope")], "route": "end"}
    if intent == "book_appointment":
        flow = await flows.start_booking(ctx)
    elif intent in {"reschedule_appointment", "cancel_appointment"}:
        flow = await flows.start_manage(ctx)
    else:  # doctor_availability
        flow = await flows.start_availability(ctx)
    return {**update, **_apply_flow_result(flow)}


async def faq_node(state: TurnState, config: RunnableConfig) -> dict[str, Any]:
    """Answers from the hospital's own content (RAG) or hands over."""
    ctx = _ctx(config)
    container = ctx.services.container
    query = state.get("faq_query") or state.get("text", "")
    cfg = ctx.settings.knowledge
    try:
        hits = [
            h
            for h in await container.knowledge.search(
                ctx.hospital.id, query, ctx.language, cfg.top_k
            )
            if h.score >= cfg.min_score
        ]
    except Exception:  # noqa: BLE001
        _log.exception("knowledge search failed")
        hits = []
    if not hits:
        return {"route": "handover", "handover_reason": "no_answer"}
    context = "\n".join(f"[{i}] {hit.title}\n{hit.content}" for i, hit in enumerate(hits, 1))
    system = ctx.settings.prompts["faq_answer"]["system"].format(
        hospital=ctx.hospital.name,
        language_name=_LANGUAGE_NAMES.get(ctx.language, "English"),
        context=context,
    )
    try:
        answer = await container.llm.structured("reply", FaqAnswer, system, query)
    except Exception:  # noqa: BLE001
        _log.exception("FAQ answer generation failed")
        return {"route": "handover", "handover_reason": "llm_unavailable"}
    best = max(h.score for h in hits)
    # The model must ground its answer in the passages; otherwise staff answer.
    if not answer.confident or not answer.answer.strip():
        return {"route": "handover", "handover_reason": "low_confidence"}
    reply = OutboundMessage(
        kind=OutboundKind.TEXT, text=f"{answer.answer.strip()}\n\n{ctx.t('faq.footer')}"
    )
    return {"replies": [reply], "route": "end", "confidence": best}


async def handover_node(state: TurnState, config: RunnableConfig) -> dict[str, Any]:
    """Queues the conversation for the front-office takeover screen."""
    ctx = _ctx(config)
    reason = state.get("handover_reason") or "requested"
    already = ctx.conversation.status != ConversationStatus.BOT
    request_handover(ctx.conversation, reason)
    key = "handover.waiting" if already else "handover.connecting"
    return {"replies": [ctx.text(key)], "route": "end", "handover_reason": reason}


# --------------------------------------------------------------------------- #
# Graph assembly
# --------------------------------------------------------------------------- #
def _route(*allowed: str) -> Any:
    def choose(state: TurnState) -> str:
        route = state.get("route", "end")
        return route if route in allowed else "end"

    return choose


def build_graph() -> Any:
    """Compiles the turn graph (compile once per process; it is stateless)."""
    graph = StateGraph(TurnState)
    graph.add_node("consent", consent_node)
    graph.add_node("emergency", emergency_node)
    graph.add_node("safety", safety_node)
    graph.add_node("language", language_node)
    graph.add_node("router", router_node)
    graph.add_node("flow", flow_node)
    graph.add_node("menu", menu_node)
    graph.add_node("classify", classify_node)
    graph.add_node("faq", faq_node)
    graph.add_node("handover", handover_node)

    graph.add_edge(START, "consent")
    graph.add_conditional_edges("consent", _route("next"), {"next": "emergency", "end": END})
    graph.add_conditional_edges("emergency", _route("next"), {"next": "safety", "end": END})
    graph.add_conditional_edges(
        "safety",
        _route("next", "handover"),
        {"next": "language", "handover": "handover", "end": END},
    )
    graph.add_edge("language", "router")
    graph.add_conditional_edges(
        "router",
        _route("flow", "menu", "handover", "classify"),
        {
            "flow": "flow",
            "menu": "menu",
            "handover": "handover",
            "classify": "classify",
            "end": END,
        },
    )
    graph.add_conditional_edges(
        "flow",
        _route("classify", "faq", "handover"),
        {"classify": "classify", "faq": "faq", "handover": "handover", "end": END},
    )
    graph.add_conditional_edges(
        "classify",
        _route("faq", "menu", "handover"),
        {"faq": "faq", "menu": "menu", "handover": "handover", "end": END},
    )
    graph.add_conditional_edges("faq", _route("handover"), {"handover": "handover", "end": END})
    graph.add_edge("menu", END)
    graph.add_edge("handover", END)
    return graph.compile()
