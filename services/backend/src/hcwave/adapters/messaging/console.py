"""Console messaging provider for local development and tests.

Outbound messages are logged and kept in memory (``sent``) so tests can assert
on them; inbound messages are injected through ``POST /dev/simulate``.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Mapping
from typing import Any

from hcwave.adapters.base import AdapterContext, AdapterSettings
from hcwave.adapters.messaging.base import (
    InboundEvent,
    InboundEventType,
    MessagingProvider,
    OutboundMessage,
    SendResult,
)
from hcwave.core.security import normalize_phone

_log = logging.getLogger(__name__)


class ConsoleSettings(AdapterSettings):
    """Settings for the console provider."""

    supports_interactive: bool = True


class ConsoleProvider(MessagingProvider):
    """Logs outbound messages; accepts simulated inbound payloads."""

    settings_model = ConsoleSettings
    name = "console"

    def __init__(self, raw_settings: Mapping[str, Any], ctx: AdapterContext) -> None:
        super().__init__(raw_settings, ctx)
        self.supports_interactive = self.config.supports_interactive
        self.sent: list[tuple[str, OutboundMessage]] = []

    async def send(self, channel_id: str, to: str, message: OutboundMessage) -> SendResult:
        """Records and logs the message."""
        self.sent.append((to, message))
        _log.info("console send to=%s kind=%s text=%s", to, message.kind, message.summary()[:200])
        return SendResult(provider_message_id=f"console-{uuid.uuid4()}", accepted=True)

    def verify_webhook(self, headers: Mapping[str, str], body: bytes) -> None:
        """Accepts everything (development only)."""

    def parse_events(self, payload: Mapping[str, Any]) -> list[InboundEvent]:
        """Parses ``{"from", "text", "reply_id", "channel_id"}`` payloads."""
        if payload.get("status"):
            return [
                InboundEvent(
                    type=InboundEventType.STATUS,
                    provider=self.name,
                    channel_id=payload.get("channel_id", "console"),
                    provider_message_id=payload.get("message_id"),
                    status=payload["status"],
                )
            ]
        return [
            InboundEvent(
                type=InboundEventType.MESSAGE,
                provider=self.name,
                channel_id=payload.get("channel_id", "console"),
                sender=normalize_phone(payload.get("from", "")),
                provider_message_id=payload.get("message_id") or str(uuid.uuid4()),
                text=str(payload.get("text", "")).strip(),
                reply_id=payload.get("reply_id"),
                raw=payload,
            )
        ]
