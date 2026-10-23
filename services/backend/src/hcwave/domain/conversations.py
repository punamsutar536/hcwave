"""Conversation lifecycle.

Covers creation, inbound logging, the 24-hour session window and human
handover/takeover.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from hcwave.adapters.messaging.base import InboundEvent
from hcwave.core.clock import utcnow
from hcwave.db.models import (
    Conversation,
    ConversationStatus,
    Message,
    MessageDirection,
    MessageStatus,
)


async def get_or_create_conversation(
    session: AsyncSession, hospital_id: str, phone: str, *, lock: bool = True, language: str = "en"
) -> Conversation:
    """Returns the conversation for a phone number, creating it if needed.

    Args:
        session: Tenant-scoped session.
        hospital_id: Tenant.
        phone: E.164 phone number.
        lock: Take a row lock (``FOR UPDATE``) so concurrent workers process
            one patient's messages strictly one at a time.
        language: Initial language for a new conversation.

    Returns:
        The conversation row.
    """
    await session.execute(
        insert(Conversation)
        .values(
            id=uuid.uuid4(),
            hospital_id=hospital_id,
            phone_e164=phone,
            status=ConversationStatus.BOT,
            language=language,
            consent_status="unknown",
            flow_state={},
            bot_turns_without_progress=0,
        )
        .on_conflict_do_nothing(index_elements=["hospital_id", "phone_e164"])
    )
    query = select(Conversation).where(
        Conversation.hospital_id == hospital_id, Conversation.phone_e164 == phone
    )
    if lock:
        query = query.with_for_update()
    return (await session.execute(query)).scalar_one()


async def store_inbound(
    session: AsyncSession, conversation: Conversation, event: InboundEvent
) -> Message | None:
    """Logs an inbound message, skipping duplicates delivered twice.

    Returns:
        The stored message, or None if this provider message ID was already
        processed (queues guarantee at-least-once delivery).
    """
    if event.provider_message_id:
        duplicate = await session.scalar(
            select(Message.id).where(
                Message.hospital_id == conversation.hospital_id,
                Message.provider_message_id == event.provider_message_id,
                Message.direction == MessageDirection.INBOUND,
            )
        )
        if duplicate:
            return None
    message = Message(
        hospital_id=conversation.hospital_id,
        conversation_id=conversation.id,
        direction=MessageDirection.INBOUND,
        sender="patient",
        provider=event.provider,
        provider_message_id=event.provider_message_id,
        kind="reply" if event.reply_id else ("media" if event.media_url else "text"),
        body=event.text,
        payload={"reply_id": event.reply_id} if event.reply_id else {},
        status=MessageStatus.RECEIVED,
    )
    session.add(message)
    conversation.last_inbound_at = event.timestamp or utcnow()
    await session.flush()
    return message


def in_session_window(conversation: Conversation, hours: int, now: datetime | None = None) -> bool:
    """True while free-form replies are allowed (24 h after the last inbound)."""
    if conversation.last_inbound_at is None:
        return False
    return (now or utcnow()) - conversation.last_inbound_at < timedelta(hours=hours)


def clear_flow(conversation: Conversation) -> None:
    """Ends any guided flow (booking, feedback...)."""
    conversation.flow = None
    conversation.flow_state = {}


def request_handover(conversation: Conversation, reason: str) -> None:
    """Queues the conversation for front-office takeover."""
    if conversation.status == ConversationStatus.BOT:
        conversation.status = ConversationStatus.HANDOVER_PENDING
        conversation.handover_at = utcnow()
    conversation.handover_reason = reason
    clear_flow(conversation)


def takeover(conversation: Conversation, staff_id: uuid.UUID) -> None:
    """A staff member takes the conversation; the bot stops replying."""
    conversation.status = ConversationStatus.HUMAN
    conversation.assigned_staff_id = staff_id
    conversation.handover_at = conversation.handover_at or utcnow()


def release(conversation: Conversation) -> None:
    """Returns the conversation to the bot."""
    conversation.status = ConversationStatus.BOT
    conversation.assigned_staff_id = None
    conversation.handover_reason = None
    conversation.bot_turns_without_progress = 0
    clear_flow(conversation)


async def auto_release_stale(session: AsyncSession, hospital_id: str, idle_minutes: int) -> int:
    """Returns idle human/handover conversations to the bot.

    Returns:
        Number of conversations released.
    """
    cutoff = utcnow() - timedelta(minutes=idle_minutes)
    result = await session.execute(
        update(Conversation)
        .where(
            Conversation.hospital_id == hospital_id,
            Conversation.status != ConversationStatus.BOT,
            Conversation.last_inbound_at < cutoff,
        )
        .values(
            status=ConversationStatus.BOT,
            assigned_staff_id=None,
            handover_reason=None,
            flow=None,
            flow_state={},
        )
    )
    return result.rowcount or 0
