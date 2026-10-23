import uuid
from datetime import timedelta

from sqlalchemy import select

from hcwave.core.clock import utcnow
from hcwave.db.models import (
    Appointment,
    AppointmentStatus,
    Feedback,
    FeedbackStatus,
    Ticket,
    TicketStatus,
)
from hcwave.domain.conversations import get_or_create_conversation
from hcwave.domain.patients import create_patient

from .conftest import HOSPITAL, PHONE, say


async def _completed_visit(container, seed, hours_ago=4):
    async with container.db.tenant_session(HOSPITAL) as session:
        patient = await create_patient(session, HOSPITAL, full_name="Meera Das", phone=PHONE)
        conversation = await get_or_create_conversation(session, HOSPITAL, PHONE)
        conversation.consent_status = "opted_in"
        start = utcnow() - timedelta(hours=hours_ago + 1)
        session.add(
            Appointment(
                id=uuid.uuid4(),
                hospital_id=HOSPITAL,
                patient_id=patient.id,
                doctor_id=seed["doctor_id"],
                department_id=seed["department_id"],
                start_at=start,
                end_at=start + timedelta(minutes=15),
                status=AppointmentStatus.COMPLETED,
                checked_out_at=utcnow() - timedelta(hours=hours_ago),
            )
        )


async def test_detractor_creates_ticket_alerts_and_invites_review(
    container, services, client, clean
):
    await _completed_visit(container, clean)
    hospital = container.hospital(HOSPITAL)
    assert await services.feedback.run_requests(hospital) == 1
    assert container.messaging.sent[-1][1].template_name == "hcw_feedback_request"
    assert await services.feedback.run_requests(hospital) == 0  # idempotent

    replies = await say(client, "3")
    assert "What could we do better" in replies[0]["text"]
    replies = await say(client, "Waiting time was very long and staff were rude")
    texts = " ".join(r["text"] for r in replies)
    assert "Thank you" in texts and "patient relations" in texts and "google" in texts.lower()

    async with container.db.tenant_session(HOSPITAL) as session:
        feedback = await session.scalar(select(Feedback))
        ticket = await session.scalar(select(Ticket))
        assert feedback.status == FeedbackStatus.COMPLETED and feedback.nps_score == 3
        assert "waiting_time" in feedback.categories and feedback.review_invited
        assert ticket.status == TicketStatus.OPEN and ticket.severity == "high"
    assert any(m.template_name == "hcw_staff_ticket_alert" for _to, m in container.messaging.sent)
    assert container.email.sent and "complaint" in container.email.sent[-1]["subject"]


async def test_promoter_gets_review_invite_without_ticket(container, services, client, clean):
    await _completed_visit(container, clean)
    await services.feedback.run_requests(container.hospital(HOSPITAL))
    await say(client, "10")
    replies = await say(client, "skip")
    assert any("google" in r["text"].lower() for r in replies)
    async with container.db.tenant_session(HOSPITAL) as session:
        assert await session.scalar(select(Ticket)) is None


async def test_ticket_escalation_after_sla(container, services, clean):
    hospital = container.hospital(HOSPITAL)
    async with container.db.tenant_session(HOSPITAL) as session:
        ticket = await services.tickets.create(
            session, hospital, summary="Billing dispute", category="billing"
        )
        ticket.due_at = utcnow() - timedelta(hours=10)
    async with container.db.tenant_session(HOSPITAL) as session:
        assert await services.tickets.escalate_overdue(session, hospital) == 1
        assert (await session.scalar(select(Ticket))).status == TicketStatus.ESCALATED
    assert "ESCALATED" in container.email.sent[-1]["subject"]
