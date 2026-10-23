"""Azure Communication Services Email sender (keyless via workload identity)."""

from __future__ import annotations

import logging

from hcwave.adapters.base import AdapterSettings
from hcwave.adapters.email.base import EmailSender

_log = logging.getLogger(__name__)


class AcsEmailSettings(AdapterSettings):
    """Settings for ACS Email."""

    endpoint: str
    access_key: str = ""


class AcsEmailSender(EmailSender):
    """Sends email through ACS Email."""

    settings_model = AcsEmailSettings
    name = "acs_email"

    async def send(
        self, sender: str, to: list[str], subject: str, text: str, html: str | None = None
    ) -> bool:
        """Sends and waits for the provider to accept the message."""
        from azure.communication.email.aio import EmailClient

        if self.config.access_key:
            from azure.core.credentials import AzureKeyCredential

            credential = AzureKeyCredential(self.config.access_key)
        else:
            credential = self.ctx.credentials.aio
        message = {
            "senderAddress": sender,
            "recipients": {"to": [{"address": address} for address in to]},
            "content": {"subject": subject, "plainText": text, **({"html": html} if html else {})},
        }
        try:
            async with EmailClient(self.config.endpoint, credential) as client:
                poller = await client.begin_send(message)
                result = await poller.result()
            return str(result.get("status", "")).lower() == "succeeded"
        except Exception:
            _log.exception("ACS email send failed")
            return False
