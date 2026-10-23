"""Appointment reminders driven by YAML rules.

Rules (24 h before, 2–3 h before, missed appointment, follow-up due) are
evaluated by a scheduled job – Logic Apps, a Kubernetes CronJob or the CLI.
Each (rule, appointment) is sent at most once thanks to ``NotificationLog``,
so overlapping or retried runs are harmless.
"""

from __future__ import annotations

import logging
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import and_, exists, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from hcwave.config.schema import HospitalConfig, ReminderRule
from hcwave.core.clock import utcnow
from hcwave.core.container import Container
from hcwave.core.errors import PolicyViolationError
from hcwave.db.models import (
    ACTIVE_APPOINTMENT_STATUSES,
    Appointment,
    AppointmentStatus,
    MessageStatus,
    Patient,
)
from hcwave.domain.consent import may_send_proactive
from hcwave.domain.context import appointment_values
from hcwave.domain.conversations import get_or_create_conversation
from hcwave.domain.messenger import Messenger
from hcwave.domain.notifications import claim_notification, release_notification

_log = logging.getLogger(__name__)


class ReminderService:
    """Evaluates reminder rules and sends due reminders.

    Args:
        container: Dependency container.
        messenger: Policy-aware sender.
    """

    def __init__(self, container: Container, messenger: Messenger) -> None:
        self._c = container
        self._messenger = messenger

    async def run(
        self,
        hospital: HospitalConfig,
        now: datetime | None = None,
        rule_ids: list[str] | None = None,
    ) -> dict[str, int]:
        """Sends all due reminders for one hospital.

        Args:
            hospital: Tenant.
            now: Evaluation time (UTC); defaults to the current time.
            rule_ids: Restrict to these rule IDs.

        Returns:
            Number of reminders sent per rule ID.
        """
        if not hospital.features.reminders:
            return {}
        now = now or utcnow()
        sent: dict[str, int] = {}
        for rule in self._c.settings.reminders.rules:
            if not rule.enabled or (rule_ids and rule.id not in rule_ids):
                continue
            async with self._c.db.tenant_session(hospital.id) as session:
                sent[rule.id] = await self._run_rule(session, hospital, rule, now)
        return sent

    async def _candidates(
        self, session: AsyncSession, hospital: HospitalConfig, rule: ReminderRule, now: datetime
    ) -> list[Appointment]:
        offset = timedelta(minutes=rule.offset_minutes)
        window = timedelta(minutes=rule.window_minutes)
        base = select(Appointment).where(
            Appointment.hospital_id == hospital.id, Appointment.visit_type == "opd"
        )
        if rule.kind in ("before_appointment", "missed_appointment"):
            # due = start + offset; send while due <= now < due + window.
            statuses = (
                ACTIVE_APPOINTMENT_STATUSES
                if rule.kind == "before_appointment"
                else (AppointmentStatus.NO_SHOW,)
            )
            query = base.where(
                Appointment.status.in_(statuses),
                Appointment.start_at > now - offset - window,
                Appointment.start_at <= now - offset,
            )
            return list(await session.scalars(query))

        # follow_up_due: anchor is 09:00 local on the follow-up date.
        tz = ZoneInfo(hospital.timezone)
        today = now.astimezone(tz).date()
        later = aliased(Appointment)
        has_newer_booking = exists().where(
            and_(
                later.patient_id == Appointment.patient_id,
                later.doctor_id == Appointment.doctor_id,
                later.status.in_(ACTIVE_APPOINTMENT_STATUSES),
                later.start_at >= now,
            )
        )
        rows = await session.scalars(
            base.where(
                Appointment.status == AppointmentStatus.COMPLETED,
                Appointment.follow_up_date.between(
                    today - timedelta(days=3), today + timedelta(days=3)
                ),
                ~has_newer_booking,
            )
        )
        due = []
        for appointment in rows:
            anchor = datetime.combine(appointment.follow_up_date, time(9, 0), tz)
            if anchor + offset <= now < anchor + offset + window:
                due.append(appointment)
        return due

    async def _run_rule(
        self, session: AsyncSession, hospital: HospitalConfig, rule: ReminderRule, now: datetime
    ) -> int:
        count = 0
        kind = f"reminder:{rule.id}"
        for appointment in await self._candidates(session, hospital, rule, now):
            values, patient, _doctor = await appointment_values(session, hospital, appointment)
            conversation = await get_or_create_conversation(
                session, hospital.id, patient.phone_e164, language=patient.preferred_language
            )
            if not may_send_proactive(conversation, patient):
                continue
            if not await claim_notification(session, hospital.id, kind, appointment.id):
                continue
            message = self._messenger.template(
                hospital, rule.template, conversation.language, values
            )
            try:
                row = await self._messenger.send(
                    session, hospital, conversation, message, sender="system"
                )
            except PolicyViolationError:
                continue
            if row.status == MessageStatus.FAILED:
                await release_notification(session, hospital.id, kind, appointment.id)
                continue
            count += 1
        _log.info("reminders rule=%s hospital=%s sent=%s", rule.id, hospital.id, count)
        return count


async def patient_language(session: AsyncSession, patient_id: object) -> str:
    """Returns a patient's preferred language (helper for other modules)."""
    patient = await session.get(Patient, patient_id)
    return patient.preferred_language if patient else "en"
