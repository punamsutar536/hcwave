"""Outbound messaging with the platform's policies applied.

Every send goes through :class:`Messenger`, which enforces opt-out, the
WhatsApp 24-hour session window (templates outside it), logs the message for
audit and records delivery outcome.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from hcwave.adapters.messaging.base import (
    MessagingProvider,
    OutboundKind,
    OutboundMessage,
    TemplateButtonBinding,
    TemplateParameter,
)
from hcwave.config.schema import HospitalConfig, Settings
from hcwave.core.clock import utcnow
from hcwave.core.errors import ConfigurationError, PolicyViolationError
from hcwave.db.models import Conversation, Message, MessageDirection, MessageStatus
from hcwave.domain.conversations import in_session_window


class Messenger:
    """Policy-aware wrapper around the messaging provider.

    Args:
        settings: Root settings.
        provider: Configured messaging provider.
    """

    def __init__(self, settings: Settings, provider: MessagingProvider) -> None:
        self._settings = settings
        self._provider = provider

    @staticmethod
    def channel_id(hospital: HospitalConfig) -> str:
        """The hospital's sending channel (first configured channel ID)."""
        return hospital.channel_ids[0] if hospital.channel_ids else "default"

    def template(
        self, hospital: HospitalConfig, logical_name: str, language: str, values: Mapping[str, Any]
    ) -> OutboundMessage:
        """Builds a template message from ``templates.yaml``.

        Args:
            hospital: Sending hospital.
            logical_name: Key in ``templates.yaml`` (e.g. ``report_ready``).
            language: Preferred platform language.
            values: Values for body parameters and button patterns.

        Returns:
            The template message.

        Raises:
            ConfigurationError: If the template is not configured.
        """
        definition = self._settings.templates.get(logical_name)
        if definition is None:
            raise ConfigurationError(f"template '{logical_name}' missing from templates.yaml")
        lang_code = (
            definition.languages.get(language)
            or definition.languages.get(hospital.default_language)
            or next(iter(definition.languages.values()))
        )
        params = tuple(
            TemplateParameter(name, str(values.get(name, ""))) for name in definition.body_params
        )
        buttons = tuple(
            TemplateButtonBinding(
                button.sub_type,
                button.value.format(**values)
                if button.sub_type == "quick_reply"
                else str(values.get(button.value, "")),
            )
            for button in definition.buttons
        )
        return OutboundMessage(
            kind=OutboundKind.TEMPLATE,
            template_name=definition.name,
            template_language=lang_code,
            template_params=params,
            template_buttons=buttons,
            category=definition.category,
            metadata={"template": logical_name},
        )

    async def send(
        self,
        session: AsyncSession,
        hospital: HospitalConfig,
        conversation: Conversation,
        message: OutboundMessage,
        *,
        sender: str = "bot",
        staff_id: uuid.UUID | None = None,
        intent: str | None = None,
        confidence: float | None = None,
    ) -> Message:
        """Sends a message and logs it.

        Raises:
            PolicyViolationError: If the recipient opted out (except OTPs and
                consent notices) or a free-form message falls outside the
                24-hour session window.
        """
        now = utcnow()
        exempt = message.category == "authentication" or message.metadata.get("consent_notice")
        if conversation.consent_status == "opted_out" and not exempt:
            raise PolicyViolationError("recipient has opted out")
        window = self._settings.messaging.session_window_hours
        if not message.is_template and not in_session_window(conversation, window, now):
            raise PolicyViolationError(
                "outside the 24-hour session window; use an approved template"
            )

        result = await self._provider.send(
            self.channel_id(hospital), conversation.phone_e164, message
        )
        row = Message(
            hospital_id=conversation.hospital_id,
            conversation_id=conversation.id,
            direction=MessageDirection.OUTBOUND,
            sender=sender,
            staff_id=staff_id,
            provider=self._provider.name,
            provider_message_id=result.provider_message_id,
            kind=message.kind.value,
            body=message.summary()[:4000],
            payload={
                k: v
                for k, v in message.metadata.items()
                if isinstance(v, (str, int, float, bool, list))
            },
            intent=intent,
            confidence=confidence,
            language=conversation.language,
            status=MessageStatus.SENT if result.accepted else MessageStatus.FAILED,
            error=result.error,
        )
        session.add(row)
        if result.accepted:
            conversation.last_outbound_at = now
        await session.flush()
        return row
