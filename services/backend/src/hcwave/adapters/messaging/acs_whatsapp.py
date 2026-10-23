"""Azure Communication Services (ACS) Advanced Messaging for WhatsApp.

Outbound: text, templates, media and interactive buttons/lists through the
``NotificationMessagesClient``. Requests are built as plain REST JSON, which
the SDK accepts directly, so interactive messages work as soon as the
configured ``api_version`` supports them – no SDK upgrade required.

Inbound: ACS publishes ``Microsoft.Communication.AdvancedMessageReceived``
and ``...AdvancedMessageDeliveryStatusUpdated`` events to Event Grid, which
delivers them to a Service Bus queue. The worker hands each event to
:meth:`AcsWhatsAppProvider.parse_events`. No public webhook is needed.

ACS has no staff inbox; the platform's own staff screen covers human takeover.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from datetime import datetime
from typing import Any

from hcwave.adapters.base import AdapterContext, AdapterSettings
from hcwave.adapters.messaging.base import (
    InboundEvent,
    InboundEventType,
    MessagingProvider,
    OutboundKind,
    OutboundMessage,
    SendResult,
    render_text_menu,
)
from hcwave.core.security import normalize_phone

_log = logging.getLogger(__name__)

_RECEIVED = "Microsoft.Communication.AdvancedMessageReceived"
_STATUS = "Microsoft.Communication.AdvancedMessageDeliveryStatusUpdated"
_ACS_SCOPE = "https://communication.azure.com/.default"


class AcsWhatsAppSettings(AdapterSettings):
    """Settings for the ACS WhatsApp provider.

    Attributes:
        endpoint: ACS resource endpoint, e.g. ``https://acs-x.india.communication.azure.com``.
        access_key: Optional ACS access key; leave empty to use Entra ID
            (workload identity) – the recommended, keyless option.
        api_version: Advanced Messaging API version. Interactive messages
            need ``2025-01-15-preview`` or later.
        supports_interactive: Set false to force numbered text menus.
    """

    endpoint: str
    access_key: str = ""
    api_version: str = "2025-01-15-preview"
    supports_interactive: bool = True


class AcsWhatsAppProvider(MessagingProvider):
    """WhatsApp through Azure Communication Services Advanced Messaging."""

    settings_model = AcsWhatsAppSettings
    name = "acs_whatsapp"

    def __init__(self, raw_settings: Mapping[str, Any], ctx: AdapterContext) -> None:
        super().__init__(raw_settings, ctx)
        self.supports_interactive = self.config.supports_interactive
        self._client: Any = None

    def _get_client(self) -> Any:
        """Creates the SDK client on first use (keeps imports lazy)."""
        if self._client is None:
            from azure.communication.messages.aio import NotificationMessagesClient

            if self.config.access_key:
                from azure.core.credentials import AzureKeyCredential

                credential: Any = AzureKeyCredential(self.config.access_key)
            else:
                credential = self.ctx.credentials.aio
            self._client = NotificationMessagesClient(
                self.config.endpoint, credential, api_version=self.config.api_version
            )
        return self._client

    # ------------------------------------------------------------------ #
    # Outbound
    # ------------------------------------------------------------------ #
    def build_request(self, channel_id: str, to: str, message: OutboundMessage) -> dict[str, Any]:
        """Builds the Advanced Messaging REST body for one message.

        Args:
            channel_id: ACS channel registration ID of the hospital's number.
            to: Recipient in E.164.
            message: Channel-neutral message.

        Returns:
            The JSON body accepted by ``NotificationMessagesClient.send``.
        """
        if (
            message.kind in (OutboundKind.BUTTONS, OutboundKind.LIST)
            and not self.supports_interactive
        ):
            message = render_text_menu(message)

        base = {"channelRegistrationId": channel_id, "to": [to]}
        if message.kind is OutboundKind.TEXT:
            return {**base, "kind": "text", "content": message.text}
        if message.kind is OutboundKind.TEMPLATE:
            return {**base, "kind": "template", "template": self._template(message)}
        if message.kind is OutboundKind.MEDIA:
            kind = message.media_type if message.media_type in {"image", "video"} else "document"
            body: dict[str, Any] = {**base, "kind": kind, "mediaUri": message.media_url}
            if message.text:
                body["caption"] = message.text
            return body
        return {**base, "kind": "interactive", "interactiveMessage": self._interactive(message)}

    @staticmethod
    def _template(message: OutboundMessage) -> dict[str, Any]:
        values: list[dict[str, Any]] = [
            {"kind": "text", "name": p.name, "text": p.value} for p in message.template_params
        ]
        buttons = []
        for index, button in enumerate(message.template_buttons):
            ref = f"button{index}"
            if button.sub_type == "url":
                values.append({"kind": "quickAction", "name": ref, "text": button.value})
                buttons.append({"subType": "url", "refValue": ref})
            else:
                values.append({"kind": "quickAction", "name": ref, "payload": button.value})
                buttons.append({"subType": "quickReply", "refValue": ref})
        bindings: dict[str, Any] = {
            "kind": "whatsApp",
            "body": [{"refValue": p.name} for p in message.template_params],
        }
        if buttons:
            bindings["buttons"] = buttons
        return {
            "name": message.template_name,
            "language": message.template_language,
            "values": values,
            "bindings": bindings,
        }

    @staticmethod
    def _interactive(message: OutboundMessage) -> dict[str, Any]:
        interactive: dict[str, Any] = {"body": {"kind": "text", "text": message.text}}
        if message.header:
            interactive["header"] = {"kind": "text", "text": message.header}
        if message.footer:
            interactive["footer"] = {"kind": "text", "text": message.footer}
        if message.kind is OutboundKind.BUTTONS:
            interactive["action"] = {
                "kind": "whatsAppButtonAction",
                "content": {
                    "kind": "buttonSet",
                    "buttons": [{"id": c.id, "title": c.title[:20]} for c in message.choices],
                },
            }
        else:
            interactive["action"] = {
                "kind": "whatsAppListAction",
                "content": {
                    "kind": "group",
                    "title": message.list_button[:20],
                    "groups": [
                        {
                            "title": (message.header or message.list_button)[:24],
                            "items": [
                                {
                                    "id": c.id,
                                    "title": c.title[:24],
                                    "description": c.description[:72],
                                }
                                for c in message.choices
                            ],
                        }
                    ],
                },
            }
        return interactive

    async def send(self, channel_id: str, to: str, message: OutboundMessage) -> SendResult:
        """Sends one message through ACS. See :meth:`MessagingProvider.send`."""
        body = self.build_request(channel_id, to, message)
        try:
            result = await self._get_client().send(body)
        except Exception as exc:  # noqa: BLE001 - surface provider errors as results
            _log.warning("ACS send failed: %s", exc)
            return SendResult(provider_message_id=None, accepted=False, error=str(exc)[:500])
        receipt = result.receipts[0] if result.receipts else None
        return SendResult(
            provider_message_id=receipt.message_id if receipt else None, accepted=True
        )

    # ------------------------------------------------------------------ #
    # Inbound
    # ------------------------------------------------------------------ #
    def parse_events(self, payload: Mapping[str, Any] | list[Any]) -> list[InboundEvent]:
        """Parses Event Grid events (Event Grid or CloudEvents schema)."""
        events = payload if isinstance(payload, list) else [payload]
        parsed: list[InboundEvent] = []
        for event in events:
            event_type = event.get("eventType") or event.get("type")
            data = event.get("data") or {}
            if event_type == _RECEIVED:
                parsed.append(self._parse_message(event, data))
            elif event_type == _STATUS:
                parsed.append(self._parse_status(data))
        return parsed

    def _parse_message(self, event: Mapping[str, Any], data: Mapping[str, Any]) -> InboundEvent:
        text = data.get("content") or ""
        reply_id = None
        interactive = data.get("interactiveContent") or {}
        if interactive:
            reply = interactive.get("buttonReply") or interactive.get("listReply") or {}
            reply_id, text = reply.get("id"), reply.get("title", text)
        elif data.get("button"):
            # Quick-reply button on a template.
            reply_id = data["button"].get("payload")
            text = data["button"].get("text", text)
        media = data.get("media") or {}
        return InboundEvent(
            type=InboundEventType.MESSAGE,
            provider=self.name,
            channel_id=str(data.get("to", "")),
            sender=normalize_phone(str(data.get("from", ""))),
            provider_message_id=data.get("messageId") or event.get("id"),
            text=text.strip(),
            reply_id=reply_id,
            media_url=media.get("id"),
            timestamp=_parse_time(data.get("receivedTimestamp")),
            raw=event,
        )

    def _parse_status(self, data: Mapping[str, Any]) -> InboundEvent:
        error = data.get("error") or {}
        return InboundEvent(
            type=InboundEventType.STATUS,
            provider=self.name,
            channel_id=str(data.get("from", "")),
            sender=normalize_phone(str(data.get("to", ""))),
            provider_message_id=data.get("messageId"),
            status=str(data.get("status", "")).lower(),
            error=error.get("channelMessage") or error.get("message"),
            timestamp=_parse_time(data.get("receivedTimestamp")),
            raw=data,
        )

    async def aclose(self) -> None:
        """Closes the SDK client."""
        if self._client is not None:
            await self._client.close()


def _parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
