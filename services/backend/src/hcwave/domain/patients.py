"""Patient identity: lookup by phone (self or family), creation and HIS upsert."""

from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from hcwave.adapters.his.base import HisPatient
from hcwave.core.clock import utcnow
from hcwave.core.security import normalize_phone
from hcwave.db.models import Patient, PatientContact


async def patients_for_phone(session: AsyncSession, hospital_id: str, phone: str) -> list[Patient]:
    """Patients this phone may act for: its own record plus registered family."""
    linked = select(PatientContact.patient_id).where(
        PatientContact.hospital_id == hospital_id, PatientContact.phone_e164 == phone
    )
    rows = await session.scalars(
        select(Patient)
        .where(
            Patient.hospital_id == hospital_id,
            or_(Patient.phone_e164 == phone, Patient.id.in_(linked)),
        )
        .order_by(Patient.created_at)
    )
    return list(rows)


async def create_patient(
    session: AsyncSession,
    hospital_id: str,
    *,
    full_name: str,
    phone: str,
    date_of_birth: date | None = None,
    language: str = "en",
    mrn: str | None = None,
    relationship: str = "self",
) -> Patient:
    """Creates a patient and links the phone that registered them."""
    patient = Patient(
        id=uuid.uuid4(),
        hospital_id=hospital_id,
        mrn=mrn,
        full_name=full_name.strip(),
        date_of_birth=date_of_birth,
        phone_e164=phone,
        preferred_language=language,
        whatsapp_opt_in=False,
    )
    session.add(patient)
    session.add(
        PatientContact(
            hospital_id=hospital_id,
            patient_id=patient.id,
            phone_e164=phone,
            relationship=relationship,
        )
    )
    await session.flush()
    return patient


async def upsert_patient_from_his(
    session: AsyncSession, hospital_id: str, source: HisPatient, country_code: str = "91"
) -> Patient:
    """Creates or updates a patient from HIS data, keyed by MRN."""
    phone = normalize_phone(source.phone, country_code)
    patient = await session.scalar(
        select(Patient).where(Patient.hospital_id == hospital_id, Patient.mrn == source.mrn)
    )
    if patient is None:
        patient = await create_patient(
            session,
            hospital_id,
            full_name=source.full_name or "Patient",
            phone=phone,
            date_of_birth=source.date_of_birth,
            mrn=source.mrn,
        )
    else:
        patient.full_name = source.full_name or patient.full_name
        patient.date_of_birth = source.date_of_birth or patient.date_of_birth
        if phone and phone != patient.phone_e164:
            patient.phone_e164 = phone
            await _ensure_contact(session, hospital_id, patient.id, phone)
    if source.whatsapp_consent and not patient.whatsapp_opt_in and patient.opted_out_at is None:
        patient.whatsapp_opt_in, patient.opt_in_at, patient.opt_in_source = (
            True,
            utcnow(),
            "registration",
        )
    return patient


async def _ensure_contact(
    session: AsyncSession, hospital_id: str, patient_id: uuid.UUID, phone: str
) -> None:
    exists = await session.scalar(
        select(PatientContact.id).where(
            PatientContact.patient_id == patient_id, PatientContact.phone_e164 == phone
        )
    )
    if not exists:
        session.add(
            PatientContact(hospital_id=hospital_id, patient_id=patient_id, phone_e164=phone)
        )


async def report_recipients(session: AsyncSession, patient: Patient) -> list[str]:
    """Phones allowed to receive this patient's reports (minors/family rule)."""
    contacts = await session.scalars(
        select(PatientContact.phone_e164).where(
            PatientContact.patient_id == patient.id, PatientContact.receives_reports.is_(True)
        )
    )
    phones = [patient.phone_e164, *contacts]
    return list(dict.fromkeys(p for p in phones if p))
