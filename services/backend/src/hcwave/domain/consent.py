"""WhatsApp consent (DPDP): explicit opt-in, instant STOP, full evidence trail."""

from __future__ import annotations

import uuid
from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hcwave.config.schema import Settings
from hcwave.core.clock import utcnow
from hcwave.db.models import ConsentEvent, Conversation, Patient


def _normalise(text: str) -> str:
    return " ".join(text.lower().strip().strip(".!").split())


def is_stop(text: str, settings: Settings) -> bool:
    """True if the message is an opt-out keyword (STOP works instantly)."""
    return _normalise(text) in {k.lower() for k in settings.conversation.stop_keywords}


def is_start(text: str, settings: Settings) -> bool:
    """True if the message is an opt-in keyword."""
    return _normalise(text) in {k.lower() for k in settings.conversation.start_keywords}


async def record_consent(
    session: AsyncSession,
    conversation: Conversation,
    *,
    opt_in: bool,
    source: str,
    evidence: str = "",
    patients: Iterable[Patient] = (),
) -> None:
    """Records an opt-in or opt-out for a phone number and its patients.

    Args:
        session: Tenant-scoped session.
        conversation: Conversation for the phone number.
        opt_in: True for opt-in, False for opt-out.
        source: ``first_message``, ``keyword``, ``registration`` or ``staff``.
        evidence: The message text or staff note that evidences consent.
        patients: Patients registered against this number.
    """
    now = utcnow()
    patient_list = list(patients)
    session.add(
        ConsentEvent(
            hospital_id=conversation.hospital_id,
            phone_e164=conversation.phone_e164,
            patient_id=patient_list[0].id if len(patient_list) == 1 else None,
            action="opt_in" if opt_in else "opt_out",
            source=source,
            channel="whatsapp",
            evidence=evidence[:500],
        )
    )
    conversation.consent_status = "opted_in" if opt_in else "opted_out"
    conversation.consent_updated_at = now
    for patient in patient_list:
        if patient.phone_e164 != conversation.phone_e164:
            continue  # a family member's consent is their own
        patient.whatsapp_opt_in = opt_in
        if opt_in:
            patient.opt_in_at, patient.opt_in_source, patient.opted_out_at = now, source, None
        else:
            patient.opted_out_at = now


def may_send_proactive(conversation: Conversation, patient: Patient | None) -> bool:
    """True if templates the patient did not ask for may be sent.

    An explicit opt-out always wins; otherwise either channel-level opt-in
    (first message / START) or registration consent on the patient record.
    """
    if conversation.consent_status == "opted_out":
        return False
    if conversation.consent_status == "opted_in":
        return True
    return bool(patient and patient.whatsapp_opt_in and patient.opted_out_at is None)


async def consent_history(
    session: AsyncSession, hospital_id: str, phone: str
) -> list[ConsentEvent]:
    """Returns the consent evidence trail for a phone number (for audits)."""
    rows = await session.scalars(
        select(ConsentEvent)
        .where(ConsentEvent.hospital_id == hospital_id, ConsentEvent.phone_e164 == phone)
        .order_by(ConsentEvent.created_at)
    )
    return list(rows)


async def record_registration_consent(
    session: AsyncSession,
    conversation: Conversation,
    patient: Patient,
    *,
    staff_id: uuid.UUID | None,
    note: str,
) -> None:
    """Front-office records consent given at registration."""
    await record_consent(
        session,
        conversation,
        opt_in=True,
        source="registration" if staff_id is None else "staff",
        evidence=note,
        patients=[patient],
    )
