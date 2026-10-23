"""Outbound email contract (complaint alerts, briefing copies)."""

from __future__ import annotations

import abc

from hcwave.adapters.base import Adapter


class EmailSender(Adapter, abc.ABC):
    """Abstract email sender."""

    @abc.abstractmethod
    async def send(
        self, sender: str, to: list[str], subject: str, text: str, html: str | None = None
    ) -> bool:
        """Sends one email. Returns True when accepted by the provider."""
