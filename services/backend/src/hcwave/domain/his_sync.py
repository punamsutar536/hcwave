"""HIS synchronisation: doctor schedules, visits and finished reports.

Pulls are incremental (``sync_states`` watermarks) and idempotent, so the job
can run every few minutes from Logic Apps or a CronJob.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from hcwave.adapters.his.base import HisDoctor, HisVisit
from hcwave.config.schema import HospitalConfig
from hcwave.core.clock import utcnow
from hcwave.core.container import Container
from hcwave.db.models import (
    Appointment,
    AppointmentStatus,
    Department,
    Doctor,
    DoctorSchedule,
    Patient,
    ScheduleException,
    SyncState,
)
from hcwave.domain.durable import DurableClient
from hcwave.domain.patients import upsert_patient_from_his
from hcwave.domain.reports import ReportService

_log = logging.getLogger(__name__)
_DEFAULT_LOOKBACK = timedelta(days=2)
# Re-read a little before the watermark: exports can land late. Ingestion is
# idempotent (external IDs), so overlap never duplicates anything.
_OVERLAP = timedelta(hours=24)


async def _watermark(session: AsyncSession, hospital_id: str, name: str) -> datetime:
    value = await session.scalar(
        select(SyncState.watermark).where(
            SyncState.hospital_id == hospital_id, SyncState.name == name
        )
    )
    return value or utcnow() - _DEFAULT_LOOKBACK


async def _set_watermark(
    session: AsyncSession, hospital_id: str, name: str, value: datetime
) -> None:
    statement = insert(SyncState).values(hospital_id=hospital_id, name=name, watermark=value)
    await session.execute(
        statement.on_conflict_do_update(
            index_elements=["hospital_id", "name"], set_={"watermark": value}
        )
    )


class HisSyncService:
    """Pulls data from the hospital's HIS connector.

    Args:
        container: Dependency container.
        reports: Report service (ingestion + notification).
    """

    def __init__(self, container: Container, reports: ReportService) -> None:
        self._c = container
        self._reports = reports
        self._durable = DurableClient(container)

    async def sync_doctors(self, hospital: HospitalConfig) -> int:
        """Upserts departments, doctors, weekly schedules and leave days.

        Doctors missing from the feed are deactivated (not deleted), so past
        appointments keep their references.
        """
        doctors = await self._c.his_for(hospital).fetch_doctors(hospital)
        if not doctors:
            return 0
        async with self._c.db.tenant_session(hospital.id) as session:
            departments = {
                d.code: d
                for d in await session.scalars(
                    select(Department).where(Department.hospital_id == hospital.id)
                )
            }
            existing = {
                d.external_id: d
                for d in await session.scalars(
                    select(Doctor).where(Doctor.hospital_id == hospital.id)
                )
            }
            seen: set[str] = set()
            for source in doctors:
                department = departments.get(source.department_code)
                if department is None:
                    department = Department(
                        id=uuid.uuid4(),
                        hospital_id=hospital.id,
                        code=source.department_code,
                        name=source.department_name,
                        names={},
                        active=True,
                    )
                    session.add(department)
                    departments[source.department_code] = department
                doctor = existing.get(source.external_id)
                if doctor is None:
                    doctor = Doctor(
                        id=uuid.uuid4(), hospital_id=hospital.id, external_id=source.external_id
                    )
                    session.add(doctor)
                self._apply_doctor(doctor, department, source)
                await session.flush()
                await self._replace_schedule(session, hospital.id, doctor, source)
                seen.add(source.external_id)
            for external_id, doctor in existing.items():
                if external_id not in seen:
                    doctor.active = False
        _log.info("synced %s doctors for %s", len(doctors), hospital.id)
        return len(doctors)

    @staticmethod
    def _apply_doctor(doctor: Doctor, department: Department, source: HisDoctor) -> None:
        doctor.department_id = department.id
        doctor.name = source.name
        doctor.qualification = source.qualification
        doctor.languages = list(source.languages)
        doctor.consultation_fee = source.consultation_fee
        doctor.active = True

    @staticmethod
    async def _replace_schedule(
        session: AsyncSession, hospital_id: str, doctor: Doctor, source: HisDoctor
    ) -> None:
        await session.execute(delete(DoctorSchedule).where(DoctorSchedule.doctor_id == doctor.id))
        for block in source.schedules:
            session.add(
                DoctorSchedule(
                    hospital_id=hospital_id,
                    doctor_id=doctor.id,
                    weekday=block.weekday,
                    start_time=block.start_time,
                    end_time=block.end_time,
                    slot_minutes=block.slot_minutes,
                    capacity_per_slot=block.capacity_per_slot,
                )
            )
        for leave in source.leave_dates:
            await session.execute(
                insert(ScheduleException)
                .values(
                    id=uuid.uuid4(),
                    hospital_id=hospital_id,
                    doctor_id=doctor.id,
                    on_date=leave,
                    reason="HIS",
                )
                .on_conflict_do_nothing(index_elements=["doctor_id", "on_date"])
            )

    async def sync_visits(self, hospital: HospitalConfig) -> int:
        """Updates appointment outcomes (completed / no-show / discharge)."""
        started = utcnow()
        async with self._c.db.tenant_session(hospital.id) as session:
            since = await _watermark(session, hospital.id, "visits") - _OVERLAP
            visits = await self._c.his_for(hospital).fetch_visits(hospital, since)
            completed: list[Appointment] = []
            for visit in visits:
                appointment = await self._match_or_create(session, hospital, visit)
                if appointment is not None and appointment.status == AppointmentStatus.COMPLETED:
                    completed.append(appointment)
            await _set_watermark(session, hospital.id, "visits", started)
        for appointment in completed:
            await self._durable.start_feedback(
                {
                    "hospital_id": hospital.id,
                    "appointment_id": str(appointment.id),
                    "visit_type": appointment.visit_type,
                    "checked_out_at": (appointment.checked_out_at or started).isoformat(),
                }
            )
        return len(visits)

    async def _match_or_create(
        self, session: AsyncSession, hospital: HospitalConfig, visit: HisVisit
    ) -> Appointment | None:
        doctor = await session.scalar(
            select(Doctor).where(
                Doctor.hospital_id == hospital.id, Doctor.external_id == visit.doctor_external_id
            )
        )
        if doctor is None:
            return None
        patient = await upsert_patient_from_his(
            session, hospital.id, visit.patient, self._c.settings.conversation.default_country_code
        )
        appointment = await session.scalar(
            select(Appointment).where(
                Appointment.hospital_id == hospital.id, Appointment.external_id == visit.external_id
            )
        )
        if appointment is None:
            # A WhatsApp booking for the same patient/doctor around the same time.
            appointment = await session.scalar(
                select(Appointment)
                .join(Patient, Patient.id == Appointment.patient_id)
                .where(
                    Appointment.hospital_id == hospital.id,
                    Appointment.doctor_id == doctor.id,
                    Patient.phone_e164 == patient.phone_e164,
                    Appointment.external_id.is_(None),
                    Appointment.start_at.between(
                        visit.start_at - timedelta(minutes=45),
                        visit.start_at + timedelta(minutes=45),
                    ),
                )
                .limit(1)
            )
        if appointment is None:
            appointment = Appointment(
                id=uuid.uuid4(),
                hospital_id=hospital.id,
                patient_id=patient.id,
                doctor_id=doctor.id,
                department_id=doctor.department_id,
                start_at=visit.start_at,
                end_at=visit.start_at + timedelta(minutes=15),
                channel="his",
            )
            session.add(appointment)
        appointment.external_id = visit.external_id
        appointment.follow_up_date = visit.follow_up_date or appointment.follow_up_date
        if visit.status == "no_show":
            appointment.status = AppointmentStatus.NO_SHOW
        else:
            appointment.status = AppointmentStatus.COMPLETED
            appointment.visit_type = "discharge" if visit.status == "discharged" else "opd"
            appointment.checked_out_at = visit.checked_out_at or visit.start_at
        await session.flush()
        return appointment

    async def sync_reports(self, hospital: HospitalConfig) -> dict[str, int]:
        """Ingests newly finalised reports and sends report-ready alerts."""
        if not hospital.features.reports:
            return {"ingested": 0, "notified": 0}
        connector = self._c.his_for(hospital)
        started = utcnow()
        ingested = notified = 0
        async with self._c.db.tenant_session(hospital.id) as session:
            since = await _watermark(session, hospital.id, "reports") - _OVERLAP
            for source in await connector.fetch_reports(hospital, since):
                try:
                    pdf = await connector.fetch_report_file(hospital, source)
                except FileNotFoundError:
                    _log.warning("report file missing for external id %s", source.external_id)
                    continue
                report = await self._reports.ingest(session, hospital, source, pdf)
                if report is None:
                    continue
                ingested += 1
                notified += await self._reports.notify(session, hospital, report)
            await _set_watermark(session, hospital.id, "reports", started)
        return {"ingested": ingested, "notified": notified}
