"""Queue message handlers.

Handles inbound patient messages, delivery receipts and report-file events.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from sqlalchemy import select

from hcwave.adapters.messaging.base import InboundEvent, InboundEventType
from hcwave.agent.runner import Assistant
from hcwave.config import hospital_for_channel
from hcwave.core.errors import PolicyViolationError
from hcwave.db.models import Message, MessageDirection, MessageStatus
from hcwave.domain.conversations import get_or_create_conversation, store_inbound
from hcwave.domain.patients import patients_for_phone
from hcwave.domain.services import Services

_log = logging.getLogger(__name__)

# Delivery receipts can arrive out of order; only move forward.
_STATUS_RANK = {
    MessageStatus.QUEUED: 0,
    MessageStatus.SENT: 1,
    MessageStatus.DELIVERED: 2,
    MessageStatus.READ: 3,
}


class EventHandlers:
    """Processes messages taken from the queues.

    Args:
        services: Domain services.
        assistant: The conversational assistant.
    """

    def __init__(self, services: Services, assistant: Assistant) -> None:
        self._s = services
        self._c = services.container
        self._assistant = assistant

    async def handle_channel_event(self, payload: Mapping[str, Any]) -> None:
        """Entry point for the inbound and delivery queues."""
        for event in self._c.messaging.parse_events(payload):
            if event.type is InboundEventType.STATUS:
                await self._handle_status(event)
            elif event.sender:
                await self._handle_message(event)

    async def _handle_message(self, event: InboundEvent) -> None:
        hospital = hospital_for_channel(self._c.settings, event.channel_id)
        if hospital is None:
            _log.warning("dropping message for unknown channel %s", event.channel_id)
            return
        async with self._c.db.tenant_session(hospital.id) as session:
            conversation = await get_or_create_conversation(
                session, hospital.id, event.sender, language=hospital.default_language
            )
            stored = await store_inbound(session, conversation, event)
            if stored is None:
                return  # duplicate delivery
            patients = await patients_for_phone(session, hospital.id, event.sender)
            outcome = await self._assistant.handle(session, hospital, conversation, patients, event)
            stored.intent, stored.confidence, stored.language = (
                outcome.intent,
                outcome.confidence,
                conversation.language,
            )
            for reply in outcome.replies:
                try:
                    await self._s.messenger.send(
                        session,
                        hospital,
                        conversation,
                        reply,
                        sender="bot",
                        intent=outcome.intent,
                        confidence=outcome.confidence,
                    )
                except PolicyViolationError as exc:
                    _log.info("reply suppressed: %s", exc)

    async def _handle_status(self, event: InboundEvent) -> None:
        hospital = hospital_for_channel(self._c.settings, event.channel_id)
        if hospital is None or not event.provider_message_id:
            return
        try:
            status = MessageStatus(event.status or "")
        except ValueError:
            return
        async with self._c.db.tenant_session(hospital.id) as session:
            message = await session.scalar(
                select(Message).where(
                    Message.hospital_id == hospital.id,
                    Message.provider_message_id == event.provider_message_id,
                    Message.direction == MessageDirection.OUTBOUND,
                )
            )
            if message is None:
                return
            if status is MessageStatus.FAILED:
                message.status, message.error = status, (event.error or "")[:1000]
            elif _STATUS_RANK.get(status, -1) > _STATUS_RANK.get(message.status, -1):
                message.status = status

    async def handle_report_event(self, payload: Mapping[str, Any]) -> None:
        """Runs an incremental report sync when a report file or HIS event arrives.

        Triggered by Event Grid ``BlobCreated`` on the imports container, or by
        an HIS notification carrying ``hospital_id``.
        """
        hospital_id = payload.get("hospital_id")
        subject = str(payload.get("subject", ""))
        if not hospital_id and "/blobs/" in subject:
            hospital_id = subject.split("/blobs/", 1)[1].split("/", 1)[0]
        hospital = self._c.settings.hospitals.get(hospital_id or "")
        if hospital is None:
            _log.warning("report event for unknown hospital")
            return
        result = await self._s.his_sync.sync_reports(hospital)
        _log.info("report event processed for %s: %s", hospital.id, result)
