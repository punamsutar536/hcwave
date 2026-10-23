"""Feedback, service recovery and review invites.

* A feedback template goes out 2–4 h after an OPD visit or 1 day after
  discharge (Durable Functions or the feedback job decide *when*).
* The patient replies with a 0–10 score, then one open comment. The tagger
  model labels sentiment and category.
* Any detractor score or negative comment opens a ticket and alerts patient
  relations on WhatsApp and email; overdue tickets escalate to the unit head.
* Every patient is invited to leave a Google review – no review gating
  (Google policy); complaints are handled through service recovery instead.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from hcwave.adapters.messaging.base import OutboundKind, OutboundMessage
from hcwave.config.schema import HospitalConfig
from hcwave.core.clock import utcnow
from hcwave.core.container import Container
from hcwave.core.errors import PolicyViolationError
from hcwave.core.i18n import translate
from hcwave.db.audit import record_audit
from hcwave.db.models import (
    Appointment,
    AppointmentStatus,
    Conversation,
    Feedback,
    FeedbackStatus,
    MessageStatus,
    Patient,
    Ticket,
    TicketStatus,
)
from hcwave.domain.consent import may_send_proactive
from hcwave.domain.context import first_name
from hcwave.domain.conversations import clear_flow, get_or_create_conversation
from hcwave.domain.messenger import Messenger
from hcwave.domain.notifications import claim_notification, release_notification

_log = logging.getLogger(__name__)


class FeedbackTags(BaseModel):
    """Structured output of the feedback tagger model."""

    sentiment: Literal["positive", "neutral", "negative"]
    categories: list[str] = Field(default_factory=list)
    summary: str = ""


class TicketService:
    """Service-recovery tickets and their alerts.

    Args:
        container: Dependency container.
        messenger: Policy-aware sender.
    """

    def __init__(self, container: Container, messenger: Messenger) -> None:
        self._c = container
        self._messenger = messenger
        self._cfg = container.settings.feedback

    async def create(
        self,
        session: AsyncSession,
        hospital: HospitalConfig,
        *,
        summary: str,
        category: str = "other",
        severity: str = "medium",
        patient_id: uuid.UUID | None = None,
        feedback_id: uuid.UUID | None = None,
        conversation_id: uuid.UUID | None = None,
        score: int | None = None,
    ) -> Ticket:
        """Opens a ticket and alerts patient relations immediately."""
        ticket = Ticket(
            id=uuid.uuid4(),
            hospital_id=hospital.id,
            patient_id=patient_id,
            feedback_id=feedback_id,
            conversation_id=conversation_id,
            category=category,
            severity=severity,
            summary=summary[:2000],
            status=TicketStatus.OPEN,
            due_at=utcnow() + timedelta(hours=self._cfg.ticket_sla_hours),
        )
        session.add(ticket)
        await session.flush()
        await record_audit(
            session, hospital.id, "ticket.created", entity_type="ticket", entity_id=ticket.id
        )
        await self._alert(
            session,
            hospital,
            phones=hospital.contacts.patient_relations_phones,
            emails=hospital.contacts.patient_relations_emails,
            subject=f"[{hospital.name}] New patient complaint ({category})",
            ticket=ticket,
            score="-" if score is None else str(score),
        )
        return ticket

    async def _alert(
        self,
        session: AsyncSession,
        hospital: HospitalConfig,
        *,
        phones: list[str],
        emails: list[str],
        subject: str,
        ticket: Ticket,
        score: str,
    ) -> None:
        values = {
            "hospital_name": hospital.name,
            "category": ticket.category.replace("_", " "),
            "score": score,
            "summary": ticket.summary[:200],
        }
        for phone in phones:
            conversation = await get_or_create_conversation(session, hospital.id, phone, lock=False)
            message = self._messenger.template(hospital, "staff_ticket_alert", "en", values)
            try:
                await self._messenger.send(
                    session, hospital, conversation, message, sender="system"
                )
            except PolicyViolationError:
                _log.warning("staff alert blocked for one recipient")
        if emails:
            body = (
                f"Category: {values['category']}\nScore: {score}\nSeverity: {ticket.severity}\n"
                f"Due by: {ticket.due_at:%Y-%m-%d %H:%M} UTC\n\n{ticket.summary}\n\n"
                f"Open the staff app to respond. Ticket ID: {ticket.id}"
            )
            await self._c.email.send(self._c.settings.email.sender, emails, subject, body)

    async def escalate_overdue(
        self, session: AsyncSession, hospital: HospitalConfig, now: datetime | None = None
    ) -> int:
        """Escalates unresolved tickets past their SLA to the unit head."""
        now = now or utcnow()
        overdue = await session.scalars(
            select(Ticket).where(
                Ticket.hospital_id == hospital.id,
                Ticket.status.in_((TicketStatus.OPEN, TicketStatus.IN_PROGRESS)),
                Ticket.escalated_at.is_(None),
                Ticket.due_at
                < now
                - timedelta(hours=self._cfg.escalate_after_hours - self._cfg.ticket_sla_hours),
            )
        )
        count = 0
        for ticket in overdue:
            ticket.status, ticket.escalated_at = TicketStatus.ESCALATED, now
            await record_audit(
                session, hospital.id, "ticket.escalated", entity_type="ticket", entity_id=ticket.id
            )
            await self._alert(
                session,
                hospital,
                phones=hospital.contacts.unit_head_phones,
                emails=hospital.contacts.unit_head_emails,
                subject=f"[{hospital.name}] ESCALATED: complaint unresolved past SLA",
                ticket=ticket,
                score="-",
            )
            count += 1
        return count


class FeedbackService:
    """Feedback requests and the score/comment conversation.

    Args:
        container: Dependency container.
        messenger: Policy-aware sender.
        tickets: Ticket service.
    """

    def __init__(self, container: Container, messenger: Messenger, tickets: TicketService) -> None:
        self._c = container
        self._messenger = messenger
        self._tickets = tickets
        self._cfg = container.settings.feedback

    async def due_appointments(
        self, session: AsyncSession, hospital: HospitalConfig, now: datetime | None = None
    ) -> list[Appointment]:
        """Completed visits whose feedback delay has elapsed (within the window)."""
        now = now or utcnow()
        window = timedelta(hours=self._cfg.request_window_hours)
        no_feedback = ~exists().where(Feedback.appointment_id == Appointment.id)
        due: list[Appointment] = []
        for visit_type, delay_hours in (
            ("opd", self._cfg.opd_delay_hours),
            ("discharge", self._cfg.discharge_delay_hours),
        ):
            delay = timedelta(hours=delay_hours)
            due += list(
                await session.scalars(
                    select(Appointment).where(
                        Appointment.hospital_id == hospital.id,
                        Appointment.visit_type == visit_type,
                        Appointment.status == AppointmentStatus.COMPLETED,
                        Appointment.checked_out_at <= now - delay,
                        Appointment.checked_out_at > now - delay - window,
                        no_feedback,
                    )
                )
            )
        return due

    async def request(
        self, session: AsyncSession, hospital: HospitalConfig, appointment: Appointment
    ) -> bool:
        """Sends the feedback template for one visit and starts the score step."""
        patient = await session.get(Patient, appointment.patient_id)
        assert patient is not None
        conversation = await get_or_create_conversation(
            session, hospital.id, patient.phone_e164, language=patient.preferred_language
        )
        if not may_send_proactive(conversation, patient):
            return False
        if not await claim_notification(session, hospital.id, "feedback_request", appointment.id):
            return False
        feedback = Feedback(
            id=uuid.uuid4(),
            hospital_id=hospital.id,
            patient_id=patient.id,
            appointment_id=appointment.id,
            status=FeedbackStatus.REQUESTED,
            categories=[],
            review_invited=False,
        )
        session.add(feedback)
        message = self._messenger.template(
            hospital,
            "feedback_request",
            conversation.language,
            {"patient_name": first_name(patient.full_name), "hospital_name": hospital.name},
        )
        row = await self._messenger.send(session, hospital, conversation, message, sender="system")
        if row.status == MessageStatus.FAILED:
            await session.delete(feedback)
            await release_notification(session, hospital.id, "feedback_request", appointment.id)
            return False
        conversation.flow = "feedback"
        conversation.flow_state = {"step": "score", "feedback_id": str(feedback.id)}
        return True

    async def run_requests(self, hospital: HospitalConfig, now: datetime | None = None) -> int:
        """Sends all due feedback requests for a hospital (job entry point)."""
        if not hospital.features.feedback:
            return 0
        sent = 0
        async with self._c.db.tenant_session(hospital.id) as session:
            for appointment in await self.due_appointments(session, hospital, now):
                sent += await self.request(session, hospital, appointment)
        return sent

    async def request_for_appointment(
        self, hospital: HospitalConfig, appointment_id: uuid.UUID
    ) -> bool:
        """Sends the request for a specific visit (Durable Functions activity)."""
        async with self._c.db.tenant_session(hospital.id) as session:
            appointment = await session.get(Appointment, appointment_id)
            if appointment is None or appointment.status != AppointmentStatus.COMPLETED:
                return False
            return await self.request(session, hospital, appointment)

    async def status_for_appointment(
        self, hospital: HospitalConfig, appointment_id: uuid.UUID
    ) -> str:
        """Returns the feedback status for a visit (``none`` if never requested)."""
        async with self._c.db.tenant_session(hospital.id) as session:
            status = await session.scalar(
                select(Feedback.status).where(Feedback.appointment_id == appointment_id)
            )
            return status.value if status else "none"

    async def tag(self, hospital: HospitalConfig, comment: str) -> FeedbackTags:
        """Labels sentiment and categories with the tagger model."""
        system = self._c.settings.prompts["feedback_tagger"]["system"].format(
            hospital=hospital.name, categories=", ".join(self._cfg.categories)
        )
        try:
            tags = await self._c.llm.structured("tagger", FeedbackTags, system, comment[:2000])
        except Exception:  # noqa: BLE001 - tagging must never lose feedback
            _log.exception("feedback tagging failed; storing untagged")
            return FeedbackTags(sentiment="neutral", categories=["other"], summary=comment[:120])
        tags.categories = [c for c in tags.categories if c in self._cfg.categories] or ["other"]
        return tags

    def record_score(self, feedback: Feedback, score: int) -> None:
        """Stores the 0–10 score."""
        feedback.nps_score = score
        feedback.status = FeedbackStatus.SCORED
        feedback.responded_at = utcnow()

    async def record_comment(
        self,
        session: AsyncSession,
        hospital: HospitalConfig,
        conversation: Conversation,
        feedback: Feedback,
        comment: str | None,
    ) -> list[OutboundMessage]:
        """Stores the comment, runs service recovery and returns the replies."""
        language = conversation.language
        tags = await self.tag(hospital, comment) if comment else FeedbackTags(sentiment="neutral")
        feedback.comment = comment
        feedback.sentiment = tags.sentiment
        feedback.categories = tags.categories
        feedback.status = FeedbackStatus.COMPLETED
        clear_flow(conversation)

        replies = [
            OutboundMessage(
                kind=OutboundKind.TEXT,
                text=translate(self._c.settings, language, "feedback.thanks"),
            )
        ]
        detractor = (
            feedback.nps_score is not None and feedback.nps_score <= self._cfg.detractor_threshold
        )
        if detractor or tags.sentiment == "negative":
            await self._tickets.create(
                session,
                hospital,
                summary=tags.summary or (comment or "Low feedback score"),
                category=tags.categories[0] if tags.categories else "other",
                severity="high" if (feedback.nps_score or 10) <= 3 else "medium",
                patient_id=feedback.patient_id,
                feedback_id=feedback.id,
                conversation_id=conversation.id,
                score=feedback.nps_score,
            )
            replies.append(
                OutboundMessage(
                    kind=OutboundKind.TEXT,
                    text=translate(
                        self._c.settings,
                        language,
                        "feedback.sorry",
                        hours=int(self._cfg.ticket_sla_hours),
                    ),
                )
            )
        if self._cfg.send_review_invite and hospital.google_review_url:
            replies.append(
                OutboundMessage(
                    kind=OutboundKind.TEXT,
                    text=translate(
                        self._c.settings,
                        language,
                        "feedback.review_invite",
                        url=hospital.google_review_url,
                    ),
                )
            )
            feedback.review_invited = True
        return replies

    async def expire_stale(
        self, session: AsyncSession, hospital: HospitalConfig, now: datetime | None = None
    ) -> int:
        """Closes requests with no reply; a detractor score alone still opens a ticket."""
        now = now or utcnow()
        cutoff = now - timedelta(hours=self._cfg.reply_timeout_hours)
        stale = await session.scalars(
            select(Feedback).where(
                Feedback.hospital_id == hospital.id,
                Feedback.status.in_((FeedbackStatus.REQUESTED, FeedbackStatus.SCORED)),
                Feedback.requested_at < cutoff,
            )
        )
        count = 0
        for feedback in stale:
            if feedback.status == FeedbackStatus.SCORED:
                feedback.status = FeedbackStatus.COMPLETED
                if (feedback.nps_score or 10) <= self._cfg.detractor_threshold:
                    await self._tickets.create(
                        session,
                        hospital,
                        summary=f"Low score ({feedback.nps_score}) with no comment",
                        patient_id=feedback.patient_id,
                        feedback_id=feedback.id,
                        score=feedback.nps_score,
                    )
            else:
                feedback.status = FeedbackStatus.EXPIRED
            count += 1
        return count
