"""Runs the assistant for one inbound message inside a tenant transaction."""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from hcwave.adapters.messaging.base import InboundEvent, OutboundKind, OutboundMessage
from hcwave.agent.context import TurnContext
from hcwave.agent.graph import build_graph, detect_emergency, emergency_reply
from hcwave.config.schema import HospitalConfig
from hcwave.db.models import Conversation, ConversationStatus, Patient
from hcwave.domain.consent import is_stop, record_consent
from hcwave.domain.services import Services


@dataclass
class TurnOutcome:
    """Result of one turn: replies plus classification for the audit row."""

    replies: list[OutboundMessage] = field(default_factory=list)
    intent: str | None = None
    confidence: float | None = None
    handover_reason: str | None = None


class Assistant:
    """Compiles the LangGraph once and runs it per message.

    Args:
        services: Domain services.
    """

    def __init__(self, services: Services) -> None:
        self._services = services
        self._graph = build_graph()

    async def handle(
        self,
        session: AsyncSession,
        hospital: HospitalConfig,
        conversation: Conversation,
        patients: list[Patient],
        event: InboundEvent,
    ) -> TurnOutcome:
        """Decides the replies for one inbound message.

        While staff own the conversation the bot stays silent, except that
        STOP is still honoured and emergencies still get the emergency reply.
        """
        ctx = TurnContext(self._services, session, hospital, conversation, patients)
        if conversation.status != ConversationStatus.BOT:
            return await self._staff_owned(ctx, event)
        state = await self._graph.ainvoke(
            {"text": event.text, "reply_id": event.reply_id, "replies": []},
            config={"configurable": {"ctx": ctx}},
        )
        return TurnOutcome(
            replies=list(state.get("replies", [])),
            intent=state.get("intent"),
            confidence=state.get("confidence"),
            handover_reason=state.get("handover_reason"),
        )

    async def _staff_owned(self, ctx: TurnContext, event: InboundEvent) -> TurnOutcome:
        if is_stop(event.text, ctx.settings):
            await record_consent(
                ctx.session,
                ctx.conversation,
                opt_in=False,
                source="keyword",
                evidence=event.text,
                patients=ctx.patients,
            )
            notice = OutboundMessage(
                kind=OutboundKind.TEXT,
                text=ctx.t("consent.opted_out"),
                metadata={"consent_notice": True},
            )
            return TurnOutcome([notice], intent="opt_out")
        language = detect_emergency(ctx, event.text)
        if language is not None:
            ctx.conversation.handover_reason = "emergency"
            return TurnOutcome(
                [emergency_reply(ctx, language)], intent="emergency", handover_reason="emergency"
            )
        return TurnOutcome()
