"""Console SMS sender for development and tests."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from hcwave.adapters.base import AdapterContext
from hcwave.adapters.sms.base import SmsSender

_log = logging.getLogger(__name__)


class ConsoleSmsSender(SmsSender):
    """Logs SMS and keeps them in ``sent``."""

    name = "console"

    def __init__(self, raw_settings: Mapping[str, Any], ctx: AdapterContext) -> None:
        super().__init__(raw_settings, ctx)
        self.sent: list[dict[str, Any]] = []

    async def send(self, to: str, text: str, purpose: str, variables: Mapping[str, str]) -> bool:
        """Records the SMS (text is not logged: it may contain an OTP)."""
        self.sent.append({"to": to, "text": text, "purpose": purpose, "variables": dict(variables)})
        _log.info("console sms to=%s purpose=%s", to, purpose)
        return True
