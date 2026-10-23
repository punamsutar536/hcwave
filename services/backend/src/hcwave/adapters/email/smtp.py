"""SMTP email sender – portable to any provider (SES, SendGrid, ZeptoMail...)."""

from __future__ import annotations

import asyncio
import logging
import smtplib
from email.message import EmailMessage

from hcwave.adapters.base import AdapterSettings
from hcwave.adapters.email.base import EmailSender

_log = logging.getLogger(__name__)


class SmtpSettings(AdapterSettings):
    """Settings for SMTP (STARTTLS)."""

    host: str
    port: int = 587
    username: str = ""
    password: str = ""
    use_starttls: bool = True


class SmtpEmailSender(EmailSender):
    """Sends email over SMTP in a worker thread."""

    settings_model = SmtpSettings
    name = "smtp"

    def _send_sync(self, message: EmailMessage) -> None:
        with smtplib.SMTP(self.config.host, self.config.port, timeout=20) as smtp:
            if self.config.use_starttls:
                smtp.starttls()
            if self.config.username:
                smtp.login(self.config.username, self.config.password)
            smtp.send_message(message)

    async def send(
        self, sender: str, to: list[str], subject: str, text: str, html: str | None = None
    ) -> bool:
        """Sends one email."""
        message = EmailMessage()
        message["From"], message["To"], message["Subject"] = sender, ", ".join(to), subject
        message.set_content(text)
        if html:
            message.add_alternative(html, subtype="html")
        try:
            await asyncio.to_thread(self._send_sync, message)
            return True
        except (OSError, smtplib.SMTPException):
            _log.exception("SMTP send failed")
            return False
