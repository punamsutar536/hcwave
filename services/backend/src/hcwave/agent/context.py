"""Per-turn context shared by graph nodes and flows."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from hcwave.adapters.messaging.base import Choice, OutboundKind, OutboundMessage
from hcwave.config.schema import HospitalConfig
from hcwave.core.i18n import translate
from hcwave.db.models import Conversation, Patient
from hcwave.domain.services import Services


@dataclass
class TurnContext:
    """Everything a node needs to handle one inbound message.

    Attributes:
        services: Domain services.
        session: Tenant-scoped DB session (one transaction per turn).
        hospital: Tenant configuration.
        conversation: Locked conversation row.
        patients: Patients this phone may act for.
        audit: Notes collected during the turn (intent, safety...).
    """

    services: Services
    session: AsyncSession
    hospital: HospitalConfig
    conversation: Conversation
    patients: list[Patient]
    audit: dict[str, Any] = field(default_factory=dict)

    @property
    def settings(self) -> Any:
        """Root settings."""
        return self.services.container.settings

    @property
    def language(self) -> str:
        """Current conversation language."""
        return self.conversation.language

    def t(self, key: str, **params: Any) -> str:
        """Localised string with hospital defaults filled in."""
        defaults = {
            "hospital": self.hospital.name,
            "phone": self.hospital.contacts.front_office_phone,
        }
        return translate(self.settings, self.language, key, **{**defaults, **params})

    def text(self, key: str, **params: Any) -> OutboundMessage:
        """A plain localised text message."""
        return OutboundMessage(kind=OutboundKind.TEXT, text=self.t(key, **params))

    def set_state(self, flow: str | None = None, **updates: Any) -> dict[str, Any]:
        """Replaces the flow state (reassignment so JSONB changes persist)."""
        if flow is not None:
            self.conversation.flow = flow
        state = {**(self.conversation.flow_state or {}), **updates}
        self.conversation.flow_state = state
        return state

    def options_message(
        self, body: str, button: str, choices: list[Choice], header: str = ""
    ) -> OutboundMessage:
        """Buttons for ≤3 short choices, otherwise a list; remembers options.

        The remembered options let patients answer with a number or the title
        (also used when the channel falls back to numbered text menus).
        """
        cfg = self.settings.messaging
        self.set_state(options=[{"id": c.id, "title": c.title} for c in choices])
        if len(choices) <= cfg.max_buttons and all(len(c.title) <= 20 for c in choices):
            return OutboundMessage(
                kind=OutboundKind.BUTTONS, text=body, choices=tuple(choices), header=header
            )
        return OutboundMessage(
            kind=OutboundKind.LIST,
            text=body,
            choices=tuple(choices[: cfg.max_list_rows]),
            list_button=button,
            header=header,
        )
