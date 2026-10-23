"""Meta WhatsApp Cloud API provider (direct Graph API).

Kept as a drop-in alternative to ACS: switch ``messaging.provider`` to
``meta_cloud``. Inbound messages arrive on ``POST /webhooks/meta_cloud``,
are verified with the ``X-Hub-Signature-256`` HMAC and queued for the worker.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

import httpx

from hcwave.adapters.base import AdapterContext, AdapterSettings
from hcwave.adapters.messaging.base import (
    InboundEvent,
    InboundEventType,
    MessagingProvider,
    OutboundKind,
    OutboundMessage,
    SendResult,
    WebhookVerificationError,
)
from hcwave.core.security import normalize_phone

_log = logging.getLogger(__name__)


class MetaCloudSettings(AdapterSettings):
    """Settings for the Meta Cloud API.

    Attributes:
        graph_url: Graph API base URL including version.
        access_token: System-user access token (secret, from env).
        app_secret: App secret used to verify webhook signatures (secret).
        verify_token: Token echoed during webhook subscription (secret).
        timeout_seconds: HTTP timeout.
    """

    graph_url: str = "https://graph.facebook.com/v21.0"
    access_token: str
    app_secret: str
    verify_token: str
    timeout_seconds: float = 15.0


class MetaCloudProvider(MessagingProvider):
    """WhatsApp via the Meta Cloud API."""

    settings_model = MetaCloudSettings
    name = "meta_cloud"

    def __init__(self, raw_settings: Mapping[str, Any], ctx: AdapterContext) -> None:
        super().__init__(raw_settings, ctx)
        self._http = httpx.AsyncClient(
            timeout=self.config.timeout_seconds,
            headers={"Authorization": f"Bearer {self.config.access_token}"},
        )

    def build_request(self, to: str, message: OutboundMessage) -> dict[str, Any]:
        """Builds the Graph API message body."""
        base: dict[str, Any] = {"messaging_product": "whatsapp", "to": to.lstrip("+")}
        if message.kind is OutboundKind.TEXT:
            return {**base, "type": "text", "text": {"body": message.text}}
        if message.kind is OutboundKind.TEMPLATE:
            components: list[dict[str, Any]] = []
            if message.template_params:
                components.append(
                    {
                        "type": "body",
                        "parameters": [
                            {"type": "text", "text": p.value} for p in message.template_params
                        ],
                    }
                )
            for index, button in enumerate(message.template_buttons):
                param = (
                    {"type": "text", "text": button.value}
                    if button.sub_type == "url"
                    else {"type": "payload", "payload": button.value}
                )
                components.append(
                    {
                        "type": "button",
                        "sub_type": button.sub_type,
                        "index": str(index),
                        "parameters": [param],
                    }
                )
            return {
                **base,
                "type": "template",
                "template": {
                    "name": message.template_name,
                    "language": {"code": message.template_language},
                    "components": components,
                },
            }
        if message.kind is OutboundKind.MEDIA:
            media_type = (
                message.media_type if message.media_type in {"image", "video"} else "document"
            )
            media: dict[str, Any] = {"link": message.media_url}
            if message.text:
                media["caption"] = message.text
            return {**base, "type": media_type, media_type: media}
        interactive: dict[str, Any] = {"body": {"text": message.text}}
        if message.header:
            interactive["header"] = {"type": "text", "text": message.header}
        if message.footer:
            interactive["footer"] = {"text": message.footer}
        if message.kind is OutboundKind.BUTTONS:
            interactive["type"] = "button"
            interactive["action"] = {
                "buttons": [
                    {"type": "reply", "reply": {"id": c.id, "title": c.title[:20]}}
                    for c in message.choices
                ]
            }
        else:
            interactive["type"] = "list"
            interactive["action"] = {
                "button": message.list_button[:20],
                "sections": [
                    {
                        "title": (message.header or message.list_button)[:24],
                        "rows": [
                            {"id": c.id, "title": c.title[:24], "description": c.description[:72]}
                            for c in message.choices
                        ],
                    }
                ],
            }
        return {**base, "type": "interactive", "interactive": interactive}

    async def send(self, channel_id: str, to: str, message: OutboundMessage) -> SendResult:
        """Sends via ``POST /{phone_number_id}/messages``."""
        url = f"{self.config.graph_url}/{channel_id}/messages"
        try:
            response = await self._http.post(url, json=self.build_request(to, message))
        except httpx.HTTPError as exc:
            return SendResult(provider_message_id=None, accepted=False, error=str(exc))
        if response.status_code >= 400:
            return SendResult(provider_message_id=None, accepted=False, error=response.text[:500])
        messages = response.json().get("messages") or [{}]
        return SendResult(provider_message_id=messages[0].get("id"), accepted=True)

    def verify_webhook(self, headers: Mapping[str, str], body: bytes) -> None:
        """Checks ``X-Hub-Signature-256`` against the app secret."""
        signature = headers.get("x-hub-signature-256", "")
        expected = (
            "sha256=" + hmac.new(self.config.app_secret.encode(), body, hashlib.sha256).hexdigest()
        )
        if not hmac.compare_digest(signature, expected):
            raise WebhookVerificationError("invalid Meta webhook signature")

    def webhook_challenge(self, params: Mapping[str, str]) -> str | None:
        """Answers Meta's ``hub.challenge`` GET handshake."""
        if params.get("hub.mode") == "subscribe" and hmac.compare_digest(
            params.get("hub.verify_token", ""), self.config.verify_token
        ):
            return params.get("hub.challenge", "")
        return None

    def parse_events(self, payload: Mapping[str, Any]) -> list[InboundEvent]:
        """Parses a Cloud API webhook body (may batch several events)."""
        events: list[InboundEvent] = []
        for entry in payload.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})
                channel_id = value.get("metadata", {}).get("phone_number_id", "")
                for msg in value.get("messages", []):
                    events.append(self._parse_message(channel_id, msg))
                for status in value.get("statuses", []):
                    errors = status.get("errors") or [{}]
                    events.append(
                        InboundEvent(
                            type=InboundEventType.STATUS,
                            provider=self.name,
                            channel_id=channel_id,
                            sender=normalize_phone(status.get("recipient_id", "")),
                            provider_message_id=status.get("id"),
                            status=status.get("status"),
                            error=errors[0].get("title"),
                            raw=status,
                        )
                    )
        return events

    def _parse_message(self, channel_id: str, msg: Mapping[str, Any]) -> InboundEvent:
        text, reply_id = "", None
        kind = msg.get("type")
        if kind == "text":
            text = msg.get("text", {}).get("body", "")
        elif kind == "interactive":
            interactive = msg.get("interactive", {})
            reply = interactive.get("button_reply") or interactive.get("list_reply") or {}
            reply_id, text = reply.get("id"), reply.get("title", "")
        elif kind == "button":
            reply_id = msg.get("button", {}).get("payload")
            text = msg.get("button", {}).get("text", "")
        timestamp = msg.get("timestamp")
        return InboundEvent(
            type=InboundEventType.MESSAGE,
            provider=self.name,
            channel_id=channel_id,
            sender=normalize_phone(msg.get("from", "")),
            provider_message_id=msg.get("id"),
            text=text.strip(),
            reply_id=reply_id,
            timestamp=datetime.fromtimestamp(int(timestamp), UTC) if timestamp else None,
            raw=msg,
        )

    async def aclose(self) -> None:
        """Closes the HTTP client."""
        await self._http.aclose()
