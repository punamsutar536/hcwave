"""Shared helpers that turn entities into template/locale values."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hcwave.config.schema import HospitalConfig
from hcwave.core.clock import format_local
from hcwave.db.models import Appointment, Department, Doctor, Patient


def first_name(full_name: str) -> str:
    """First word of a name, used to keep messages short and less identifying."""
    return (full_name or "").split(" ")[0] or "there"


async def appointment_values(
    session: AsyncSession, hospital: HospitalConfig, appointment: Appointment
) -> tuple[dict[str, Any], Patient, Doctor]:
    """Loads related rows and builds the values used by templates and texts.

    Returns:
        ``(values, patient, doctor)``.
    """
    patient = await session.get(Patient, appointment.patient_id)
    doctor = await session.get(Doctor, appointment.doctor_id)
    department = await session.get(Department, appointment.department_id)
    assert patient is not None and doctor is not None  # FK-guaranteed
    values = {
        "appointment_id": str(appointment.id),
        "doctor_id": str(doctor.id),
        "patient_name": first_name(patient.full_name),
        "doctor_name": doctor.name,
        "department": department.name if department else "",
        "date_time": format_local(appointment.start_at, hospital.timezone),
        "when": format_local(appointment.start_at, hospital.timezone),
        "time": format_local(appointment.start_at, hospital.timezone, "%I:%M %p"),
        "follow_up_date": appointment.follow_up_date.strftime("%d %b %Y")
        if appointment.follow_up_date
        else "",
        "hospital_name": hospital.name,
        "hospital": hospital.name,
    }
    return values, patient, doctor


async def doctor_with_department(
    session: AsyncSession, doctor_id: Any
) -> tuple[Doctor | None, Department | None]:
    """Loads a doctor and their department."""
    row = (
        await session.execute(
            select(Doctor, Department)
            .join(Department, Department.id == Doctor.department_id)
            .where(Doctor.id == doctor_id)
        )
    ).first()
    return (row[0], row[1]) if row else (None, None)
