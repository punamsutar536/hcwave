"""Daily 5-line management briefing on WhatsApp (plus an email copy).

Keeps the product visible to management every morning.
"""

from __future__ import annotations

import logging
from datetime import datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from hcwave.config.schema import HospitalConfig
from hcwave.core.clock import utcnow
from hcwave.core.container import Container
from hcwave.core.errors import PolicyViolationError
from hcwave.domain.conversations import get_or_create_conversation
from hcwave.domain.dashboard import summary
from hcwave.domain.messenger import Messenger

_log = logging.getLogger(__name__)


def _pct(value: float | None) -> str:
    return "–" if value is None else f"{value * 100:.0f}%"


class BriefingService:
    """Builds and sends the daily briefing.

    Args:
        container: Dependency container.
        messenger: Policy-aware sender.
    """

    def __init__(self, container: Container, messenger: Messenger) -> None:
        self._c = container
        self._messenger = messenger

    async def build(self, hospital: HospitalConfig, now: datetime | None = None) -> dict[str, Any]:
        """Computes yesterday's figures (hospital local day) and the 5 lines."""
        tz = ZoneInfo(hospital.timezone)
        today = (now or utcnow()).astimezone(tz).date()
        start = datetime.combine(today - timedelta(days=1), time.min, tz)
        end = start + timedelta(days=1)
        async with self._c.db.tenant_session(hospital.id) as session:
            data = await summary(session, hospital.id, start, end)
        acc, appt, rep, exp = (
            data["access"],
            data["appointments"],
            data["reports"],
            data["experience"],
        )
        values = {
            "hospital_name": hospital.name,
            "date": start.strftime("%d %b %Y"),
            "bookings": f"{acc['bookings_total']} ({acc['bookings_whatsapp']} via WhatsApp)",
            "no_show": _pct(appt["no_show_rate"]),
            "reports": f"{rep['notified']} sent, {rep['opened']} opened",
            "nps": "–"
            if exp["nps"] is None
            else f"{exp['nps']:.0f} ({exp['open_tickets']} open complaints)",
            "bot_share": _pct(acc["bot_handled_share"]),
        }
        lines = [
            f"1. Bookings: {values['bookings']}",
            f"2. No-show rate: {values['no_show']}",
            f"3. Reports: {values['reports']}",
            f"4. NPS: {values['nps']}",
            f"5. Handled by assistant: {values['bot_share']}",
        ]
        return {"values": values, "lines": lines, "metrics": data}

    async def send(self, hospital: HospitalConfig, now: datetime | None = None) -> dict[str, Any]:
        """Sends the briefing to the unit heads configured for the hospital."""
        cfg = self._c.settings.briefing
        if not (cfg.enabled and hospital.features.briefing):
            return {"sent": 0}
        briefing = await self.build(hospital, now)
        sent = 0
        if cfg.send_whatsapp:
            async with self._c.db.tenant_session(hospital.id) as session:
                for phone in hospital.contacts.unit_head_phones:
                    conversation = await get_or_create_conversation(
                        session, hospital.id, phone, lock=False
                    )
                    message = self._messenger.template(
                        hospital, "daily_briefing", "en", briefing["values"]
                    )
                    try:
                        await self._messenger.send(
                            session, hospital, conversation, message, sender="system"
                        )
                        sent += 1
                    except PolicyViolationError:
                        _log.warning("briefing blocked for a recipient")
        if cfg.send_email and hospital.contacts.unit_head_emails:
            subject = f"{hospital.name} – daily briefing {briefing['values']['date']}"
            await self._c.email.send(
                self._c.settings.email.sender,
                hospital.contacts.unit_head_emails,
                subject,
                "\n".join(briefing["lines"]),
            )
        return {"sent": sent, "lines": briefing["lines"]}
