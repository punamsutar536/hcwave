import uuid
from datetime import timedelta

from sqlalchemy import select

from hcwave.core.clock import utcnow
from hcwave.db.models import Appointment, AppointmentStatus, Conversation
from hcwave.domain.conversations import get_or_create_conversation
from hcwave.domain.patients import create_patient

from .conftest import HOSPITAL, PHONE, say


async def _book(container, seed, start_at, status=AppointmentStatus.BOOKED, consent="opted_in"):
    async with container.db.tenant_session(HOSPITAL) as session:
        patient = await create_patient(session, HOSPITAL, full_name="Ravi Nair", phone=PHONE)
        conversation = await get_or_create_conversation(session, HOSPITAL, PHONE)
        conversation.consent_status = consent
        appointment = Appointment(
            id=uuid.uuid4(),
            hospital_id=HOSPITAL,
            patient_id=patient.id,
            doctor_id=seed["doctor_id"],
            department_id=seed["department_id"],
            start_at=start_at,
            end_at=start_at + timedelta(minutes=15),
            status=status,
        )
        session.add(appointment)
    return appointment.id


async def test_day_before_reminder_sent_once_with_buttons(container, services, clean):
    appointment_id = await _book(container, clean, utcnow() + timedelta(hours=23, minutes=30))
    hospital = container.hospital(HOSPITAL)
    assert (await services.reminders.run(hospital, rule_ids=["day_before"]))["day_before"] == 1
    _to, message = container.messaging.sent[-1]
    assert message.template_name == "hcw_appointment_reminder"
    assert [b.value for b in message.template_buttons][0] == f"remind_confirm:{appointment_id}"
    # Re-running (Logic Apps retry, overlapping CronJob) never double-sends.
    assert (await services.reminders.run(hospital, rule_ids=["day_before"]))["day_before"] == 0


async def test_reminder_respects_opt_out(container, services, clean):
    await _book(container, clean, utcnow() + timedelta(hours=23, minutes=30), consent="opted_out")
    assert (await services.reminders.run(container.hospital(HOSPITAL), rule_ids=["day_before"]))[
        "day_before"
    ] == 0


async def test_confirm_and_cancel_buttons(container, client, clean):
    appointment_id = await _book(container, clean, utcnow() + timedelta(hours=23, minutes=30))
    replies = await say(client, reply_id=f"remind_confirm:{appointment_id}")
    assert "confirmed" in replies[0]["text"]
    replies = await say(client, reply_id=f"remind_cancel:{appointment_id}")
    assert "cancelled" in replies[0]["text"]
    async with container.db.tenant_session(HOSPITAL) as session:
        appointment = await session.get(Appointment, appointment_id)
        assert (
            appointment.status == AppointmentStatus.CANCELLED
            and appointment.confirmed_at is not None
        )


async def test_buttons_from_another_phone_are_rejected(container, client, clean):
    appointment_id = await _book(container, clean, utcnow() + timedelta(hours=23, minutes=30))
    replies = await say(client, reply_id=f"remind_cancel:{appointment_id}", phone="+919800099999")
    assert "couldn't find" in replies[0]["text"]
    async with container.db.tenant_session(HOSPITAL) as session:
        assert (await session.get(Appointment, appointment_id)).status == AppointmentStatus.BOOKED


async def test_missed_appointment_rebook_offer(container, services, clean):
    await _book(container, clean, utcnow() - timedelta(hours=3), status=AppointmentStatus.NO_SHOW)
    assert (await services.reminders.run(container.hospital(HOSPITAL), rule_ids=["missed"]))[
        "missed"
    ] == 1
    async with container.db.tenant_session(HOSPITAL) as session:
        assert (await session.scalar(select(Conversation))).last_outbound_at is not None
