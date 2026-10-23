"""Console email sender for development and tests."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from hcwave.adapters.base import AdapterContext
from hcwave.adapters.email.base import EmailSender

_log = logging.getLogger(__name__)


class ConsoleEmailSender(EmailSender):
    """Logs emails and keeps them in ``sent``."""

    name = "console"

    def __init__(self, raw_settings: Mapping[str, Any], ctx: AdapterContext) -> None:
        super().__init__(raw_settings, ctx)
        self.sent: list[dict[str, Any]] = []

    async def send(
        self, sender: str, to: list[str], subject: str, text: str, html: str | None = None
    ) -> bool:
        """Records the email."""
        self.sent.append({"to": to, "subject": subject, "text": text})
        _log.info("console email to=%s subject=%s", to, subject)
        return True
