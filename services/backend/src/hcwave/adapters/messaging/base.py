"""Channel-neutral messaging contract.

Business logic builds :class:`OutboundMessage` objects (text, buttons, lists,
templates, media) and receives :class:`InboundEvent` objects. Each provider
translates between these and its wire format, so adding Telegram, Gupshup or
an SMS channel means writing one class – nothing else changes.
"""

from __future__ import annotations

import abc
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

from hcwave.adapters.base import Adapter


class OutboundKind(StrEnum):
    """Shapes of outbound messages."""

    TEXT = "text"
    BUTTONS = "buttons"
    LIST = "list"
    TEMPLATE = "template"
    MEDIA = "media"


@dataclass(frozen=True)
class Choice:
    """A selectable option rendered as a button or list row.

    Attributes:
        id: Machine-readable payload returned when the option is chosen
            (e.g. ``dept:3fa85f64``).
        title: Label shown to the patient (≤20 chars for buttons, ≤24 rows).
        description: Optional secondary text (list rows only).
    """

    id: str
    title: str
    description: str = ""


@dataclass(frozen=True)
class TemplateParameter:
    """One value bound into an approved template."""

    name: str
    value: str


@dataclass(frozen=True)
class TemplateButtonBinding:
    """A value bound to a template button (quick-reply payload or URL suffix)."""

    sub_type: str  # quick_reply | url
    value: str


@dataclass(frozen=True)
class OutboundMessage:
    """A message to send, independent of the channel.

    Attributes:
        kind: Message shape.
        text: Body text (all kinds except pure media/template).
        choices: Buttons or list rows.
        list_button: Label of the button that opens a list.
        header: Optional header text.
        footer: Optional footer text.
        template_name: Channel template name (``TEMPLATE``).
        template_language: Channel language code (``TEMPLATE``).
        template_params: Ordered body parameters (``TEMPLATE``).
        template_buttons: Button bindings (``TEMPLATE``).
        media_url: Public or SAS URL of the media (``MEDIA``).
        media_type: ``image``, ``document`` or ``video``.
        category: Template category (``authentication`` OTPs are allowed
            even to opted-out numbers because the patient requested them).
        metadata: Free-form data stored with the message row.
    """

    kind: OutboundKind
    text: str = ""
    choices: tuple[Choice, ...] = ()
    list_button: str = "Choose"
    header: str = ""
    footer: str = ""
    template_name: str = ""
    template_language: str = ""
    template_params: tuple[TemplateParameter, ...] = ()
    template_buttons: tuple[TemplateButtonBinding, ...] = ()
    media_url: str = ""
    media_type: str = "document"
    category: str = "service"
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @property
    def is_template(self) -> bool:
        """True for pre-approved templates (allowed outside the 24h window)."""
        return self.kind is OutboundKind.TEMPLATE

    def summary(self) -> str:
        """Human-readable text stored in the audit message row."""
        if self.kind is OutboundKind.TEMPLATE:
            params = ", ".join(p.value for p in self.template_params)
            return f"[template:{self.template_name}] {params}".strip()
        if self.choices:
            return self.text + "\n" + "\n".join(f"- {c.title}" for c in self.choices)
        return self.text or self.media_url


@dataclass(frozen=True)
class SendResult:
    """Outcome of a send call."""

    provider_message_id: str | None
    accepted: bool
    error: str | None = None


class InboundEventType(StrEnum):
    """Kinds of inbound events."""

    MESSAGE = "message"
    STATUS = "status"


@dataclass(frozen=True)
class InboundEvent:
    """A normalised inbound event from any channel.

    Attributes:
        type: Message or delivery status.
        provider: Provider name that produced the event.
        channel_id: Receiving channel (routes the event to a hospital).
        sender: Patient phone in E.164 (messages only).
        provider_message_id: Channel message ID (for idempotency/status).
        text: Message text, or the title of a chosen button/list row.
        reply_id: Payload of the chosen button/list row, if any.
        media_url: Media reference for image/document messages.
        status: Delivery status (``sent``/``delivered``/``read``/``failed``).
        error: Error text for failed deliveries.
        timestamp: Event time.
        raw: Original payload (kept for troubleshooting, never logged).
    """

    type: InboundEventType
    provider: str
    channel_id: str
    sender: str = ""
    provider_message_id: str | None = None
    text: str = ""
    reply_id: str | None = None
    media_url: str | None = None
    status: str | None = None
    error: str | None = None
    timestamp: datetime | None = None
    raw: Mapping[str, Any] = field(default_factory=dict, repr=False)


class WebhookVerificationError(Exception):
    """Raised when an inbound webhook fails signature verification."""


class MessagingProvider(Adapter, abc.ABC):
    """Abstract messaging channel."""

    #: Whether the channel can render native buttons and lists.
    supports_interactive: bool = True

    @abc.abstractmethod
    async def send(self, channel_id: str, to: str, message: OutboundMessage) -> SendResult:
        """Sends one message.

        Args:
            channel_id: Sending channel (the hospital's number registration).
            to: Recipient phone in E.164.
            message: Channel-neutral message.

        Returns:
            The provider's result. Implementations should not raise for
            provider-side rejections; they return ``accepted=False``.
        """

    @abc.abstractmethod
    def parse_events(self, payload: Mapping[str, Any]) -> list[InboundEvent]:
        """Converts a raw provider payload into normalised events.

        Args:
            payload: One queued event / webhook body.

        Returns:
            Zero or more events (one webhook may batch several messages).
        """

    def verify_webhook(self, headers: Mapping[str, str], body: bytes) -> None:
        """Verifies an HTTP webhook signature. Default: no HTTP webhooks.

        Raises:
            WebhookVerificationError: If verification fails.
        """
        raise WebhookVerificationError(f"{self.name} does not accept HTTP webhooks")

    def webhook_challenge(self, params: Mapping[str, str]) -> str | None:
        """Answers a subscription handshake (e.g. Meta's GET verify)."""
        return None


def render_text_menu(message: OutboundMessage) -> OutboundMessage:
    """Turns buttons/lists into a numbered text menu for plain-text channels.

    The conversation layer maps a numeric reply back to the choice, so the
    patient experience degrades gracefully instead of failing.
    """
    lines = [message.header, message.text] if message.header else [message.text]
    lines += [f"{index}. {choice.title}" for index, choice in enumerate(message.choices, 1)]
    if message.footer:
        lines.append(message.footer)
    return OutboundMessage(
        kind=OutboundKind.TEXT,
        text="\n".join(line for line in lines if line),
        category=message.category,
        metadata={**message.metadata, "menu": [c.id for c in message.choices]},
    )
