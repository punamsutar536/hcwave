"""End-to-end assistant behaviour through the /dev/simulate endpoint."""

from sqlalchemy import select

from hcwave.db.models import (
    Appointment,
    AppointmentStatus,
    ConsentEvent,
    Conversation,
    ConversationStatus,
    Patient,
)
from hcwave.knowledge.ingest import reindex

from .conftest import HOSPITAL, PHONE, say


def _ids(replies, prefix):
    return [c["id"] for r in replies for c in r["choices"] if c["id"].startswith(prefix)]


async def test_greeting_shows_menu_and_records_first_message_consent(client, clean, container):
    replies = await say(client, "hi")
    assert replies[0]["kind"] == "list"
    assert "menu:book" in _ids(replies, "menu:")
    async with container.db.tenant_session(HOSPITAL) as session:
        conversation = await session.scalar(select(Conversation))
        assert conversation.consent_status == "opted_in"
        event = await session.scalar(select(ConsentEvent))
        assert event.source == "first_message"


async def test_full_booking_flow_creates_appointment(client, clean, container):
    replies = await say(client, reply_id="menu:book")
    dept = _ids(replies, "dept:")[0]
    doctor = _ids(await say(client, reply_id=dept), "doc:")[0]
    date_choice = _ids(await say(client, reply_id=doctor), "date:")[-1]
    slot = _ids(await say(client, reply_id=date_choice), "slot:")[0]
    replies = await say(client, reply_id=slot)
    assert "full name" in replies[0]["text"]
    assert "date of birth" in (await say(client, "Asha Menon"))[0]["text"]
    replies = await say(client, "05-08-1984")
    assert "Asha Menon" in replies[0]["text"]
    replies = await say(client, reply_id="book:confirm")
    assert "booked" in replies[0]["text"]

    async with container.db.tenant_session(HOSPITAL) as session:
        appointment = await session.scalar(select(Appointment))
        patient = await session.scalar(select(Patient))
        assert appointment.status == AppointmentStatus.BOOKED
        assert patient.full_name == "Asha Menon" and patient.phone_e164 == PHONE
        assert str(patient.date_of_birth) == "1984-08-05"


async def test_numbered_text_reply_selects_option(client, clean):
    await say(client, reply_id="menu:book")
    replies = await say(client, "1")  # first department by number
    assert _ids(replies, "doc:")


async def test_stop_opts_out_and_blocks_proactive(client, clean, container):
    await say(client, "hello")
    replies = await say(client, "STOP")
    assert "unsubscribed" in replies[0]["text"]
    async with container.db.tenant_session(HOSPITAL) as session:
        assert (await session.scalar(select(Conversation))).consent_status == "opted_out"
    replies = await say(client, "book appointment")
    assert "START" in replies[0]["text"]  # only the consent notice


async def test_emergency_keyword_replies_and_hands_over(client, clean, container):
    replies = await say(client, "my father has severe chest pain")
    assert "108" in replies[0]["text"]
    async with container.db.tenant_session(HOSPITAL) as session:
        conversation = await session.scalar(select(Conversation))
        assert conversation.status == ConversationStatus.HANDOVER_PENDING
        assert conversation.handover_reason == "emergency"


async def test_malayalam_emergency_keyword(client, clean):
    replies = await say(client, "അമ്മയ്ക്ക് നെഞ്ചുവേദന")
    assert "108" in replies[0]["text"] and "അടിയന്തര" in replies[0]["text"]


async def test_faq_answer_from_hospital_content(client, clean, container):
    await reindex(container, [HOSPITAL])
    replies = await say(client, "What are the health check package prices?")
    assert "1,499" in replies[0]["text"]


async def test_unclear_message_goes_to_human(client, clean, container):
    replies = await say(client, "qwerty zxcv")
    assert "front-office" in replies[0]["text"]
    async with container.db.tenant_session(HOSPITAL) as session:
        conversation = await session.scalar(select(Conversation))
        assert conversation.handover_reason == "low_confidence"
    # The bot stays quiet while staff own the conversation.
    assert await say(client, "hello?") == []
