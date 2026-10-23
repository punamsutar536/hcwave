"""Appointment booking: departments, doctors, free slots and safe booking.

Slots are generated from HIS doctor schedules (weekly sessions with a slot
length and capacity) minus leave days and existing bookings. Booking locks the
doctor row, so two patients can never take the last place in a slot at once.
"""

from __future__ import annotations

import uuid
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from hcwave.config.schema import HospitalConfig, Settings
from hcwave.core.clock import utcnow
from hcwave.core.errors import ConflictError, NotFoundError
from hcwave.db.models import (
    ACTIVE_APPOINTMENT_STATUSES,
    Appointment,
    AppointmentStatus,
    Department,
    Doctor,
    DoctorSchedule,
    ScheduleException,
)


@dataclass(frozen=True)
class Slot:
    """A bookable slot.

    Attributes:
        start_at: Slot start (aware UTC).
        minutes: Slot length.
        remaining: Places left.
    """

    start_at: datetime
    minutes: int
    remaining: int


class BookingService:
    """Booking rules shared by the WhatsApp flow, staff screens and jobs.

    Args:
        settings: Root settings (``booking`` section).
    """

    def __init__(self, settings: Settings) -> None:
        self._cfg = settings.booking

    async def departments(self, session: AsyncSession, hospital_id: str) -> list[Department]:
        """Active departments that have at least one bookable doctor."""
        has_doctor = exists().where(
            Doctor.department_id == Department.id,
            Doctor.active.is_(True),
            exists().where(DoctorSchedule.doctor_id == Doctor.id),
        )
        rows = await session.scalars(
            select(Department)
            .where(Department.hospital_id == hospital_id, Department.active.is_(True), has_doctor)
            .order_by(Department.name)
        )
        return list(rows)

    async def doctors(
        self, session: AsyncSession, hospital_id: str, department_id: uuid.UUID
    ) -> list[Doctor]:
        """Active doctors in a department."""
        rows = await session.scalars(
            select(Doctor)
            .where(
                Doctor.hospital_id == hospital_id,
                Doctor.department_id == department_id,
                Doctor.active.is_(True),
            )
            .order_by(Doctor.name)
        )
        return list(rows)

    async def schedules(self, session: AsyncSession, doctor_id: uuid.UUID) -> list[DoctorSchedule]:
        """A doctor's weekly sessions ordered by weekday and time."""
        rows = await session.scalars(
            select(DoctorSchedule)
            .where(DoctorSchedule.doctor_id == doctor_id)
            .order_by(DoctorSchedule.weekday, DoctorSchedule.start_time)
        )
        return list(rows)

    async def slots_for_day(
        self,
        session: AsyncSession,
        hospital: HospitalConfig,
        doctor_id: uuid.UUID,
        day: date,
        now: datetime | None = None,
    ) -> list[Slot]:
        """Free slots for a doctor on a local calendar day.

        Args:
            session: Tenant-scoped session.
            hospital: Hospital (for its timezone).
            doctor_id: Doctor.
            day: Local date.
            now: Current time (UTC); slots earlier than ``now`` plus the
                configured lead time are excluded.

        Returns:
            Slots with at least one place left, in time order.
        """
        now = now or utcnow()
        on_leave = await session.scalar(
            select(ScheduleException.id).where(
                ScheduleException.doctor_id == doctor_id, ScheduleException.on_date == day
            )
        )
        if on_leave:
            return []
        tz = ZoneInfo(hospital.timezone)
        sessions = [
            s
            for s in await self.schedules(session, doctor_id)
            if s.weekday == day.weekday()
            and (s.valid_from is None or s.valid_from <= day)
            and (s.valid_to is None or s.valid_to >= day)
        ]
        if not sessions:
            return []

        day_start = datetime.combine(day, datetime.min.time(), tz)
        booked_rows = await session.execute(
            select(Appointment.start_at, func.count())
            .where(
                Appointment.doctor_id == doctor_id,
                Appointment.status.in_(ACTIVE_APPOINTMENT_STATUSES),
                Appointment.start_at >= day_start,
                Appointment.start_at < day_start + timedelta(days=1),
            )
            .group_by(Appointment.start_at)
        )
        booked = Counter({start.astimezone(UTC): count for start, count in booked_rows})
        earliest = now + timedelta(minutes=self._cfg.min_lead_minutes)

        slots: list[Slot] = []
        for block in sessions:
            step = timedelta(minutes=block.slot_minutes)
            cursor = datetime.combine(day, block.start_time, tz)
            end = datetime.combine(day, block.end_time, tz)
            while cursor + step <= end:
                start_utc = cursor.astimezone(UTC)
                remaining = block.capacity_per_slot - booked.get(start_utc, 0)
                if start_utc >= earliest and remaining > 0:
                    slots.append(Slot(start_utc, block.slot_minutes, remaining))
                cursor += step
        return sorted(slots, key=lambda s: s.start_at)

    async def available_dates(
        self,
        session: AsyncSession,
        hospital: HospitalConfig,
        doctor_id: uuid.UUID,
        now: datetime | None = None,
    ) -> list[date]:
        """Local dates in the booking horizon with at least one free slot."""
        now = now or utcnow()
        today = now.astimezone(ZoneInfo(hospital.timezone)).date()
        dates = []
        for offset in range(self._cfg.days_ahead):
            day = today + timedelta(days=offset)
            if await self.slots_for_day(session, hospital, doctor_id, day, now):
                dates.append(day)
        return dates

    async def book(
        self,
        session: AsyncSession,
        hospital: HospitalConfig,
        *,
        patient_id: uuid.UUID,
        doctor_id: uuid.UUID,
        start_at: datetime,
        channel: str = "whatsapp",
        reschedule_of: Appointment | None = None,
    ) -> Appointment:
        """Books a slot, re-checking availability under a row lock.

        Raises:
            NotFoundError: If the doctor does not exist in this hospital.
            ConflictError: If the slot is no longer available.
        """
        doctor = await session.scalar(
            select(Doctor)
            .where(Doctor.id == doctor_id, Doctor.hospital_id == hospital.id)
            .with_for_update()
        )
        if doctor is None or not doctor.active:
            raise NotFoundError("doctor not found")
        local_day = start_at.astimezone(ZoneInfo(hospital.timezone)).date()
        slot = next(
            (
                s
                for s in await self.slots_for_day(session, hospital, doctor_id, local_day)
                if s.start_at == start_at
            ),
            None,
        )
        if slot is None:
            raise ConflictError("slot no longer available")

        appointment = Appointment(
            id=uuid.uuid4(),
            hospital_id=hospital.id,
            patient_id=patient_id,
            doctor_id=doctor.id,
            department_id=doctor.department_id,
            start_at=start_at,
            end_at=start_at + timedelta(minutes=slot.minutes),
            status=AppointmentStatus.BOOKED,
            channel=channel,
            visit_type="opd",
        )
        if reschedule_of is not None:
            reschedule_of.status = AppointmentStatus.RESCHEDULED
            appointment.rescheduled_from_id = reschedule_of.id
        session.add(appointment)
        await session.flush()
        return appointment

    @staticmethod
    def cancel(appointment: Appointment) -> None:
        """Cancels an appointment; its slot becomes free immediately."""
        appointment.status = AppointmentStatus.CANCELLED
        appointment.cancelled_at = utcnow()

    @staticmethod
    def confirm(appointment: Appointment) -> None:
        """Marks an appointment as confirmed by the patient."""
        appointment.status = AppointmentStatus.CONFIRMED
        appointment.confirmed_at = utcnow()

    async def upcoming(
        self, session: AsyncSession, hospital_id: str, patient_ids: list[uuid.UUID], limit: int = 10
    ) -> list[Appointment]:
        """Active future appointments for the given patients."""
        if not patient_ids:
            return []
        rows = await session.scalars(
            select(Appointment)
            .where(
                Appointment.hospital_id == hospital_id,
                Appointment.patient_id.in_(patient_ids),
                Appointment.status.in_(ACTIVE_APPOINTMENT_STATUSES),
                Appointment.start_at >= utcnow(),
            )
            .order_by(Appointment.start_at)
            .limit(limit)
        )
        return list(rows)

    @staticmethod
    async def owned_appointment(
        session: AsyncSession, hospital_id: str, appointment_id: str, patient_ids: list[uuid.UUID]
    ) -> Appointment | None:
        """Loads an appointment only if it belongs to one of ``patient_ids``.

        Protects button payloads (``remind_cancel:<id>``) from being replayed
        by another phone number.
        """
        try:
            parsed = uuid.UUID(appointment_id)
        except ValueError:
            return None
        if not patient_ids:
            return None
        return await session.scalar(
            select(Appointment)
            .where(
                Appointment.id == parsed,
                Appointment.hospital_id == hospital_id,
                Appointment.patient_id.in_(patient_ids),
            )
            .with_for_update()
        )
