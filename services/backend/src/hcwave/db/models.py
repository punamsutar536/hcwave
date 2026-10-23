"""Relational data model.

Every tenant-owned table carries ``hospital_id``. When
``database.row_level_security`` is on, PostgreSQL RLS policies (created by the
migrations) restrict every query to the hospital set on the transaction with
``app.hospital_id`` – so a bug in one query cannot leak another hospital's
patients.

Core tables follow the build guide: patients (with consent flags), doctors,
schedules, appointments, messages (every inbound and outbound message, for
audit), reports, feedback, opt-ins (consent events) and staff users.
"""

from __future__ import annotations

import enum
import uuid
from datetime import date, datetime, time
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    SmallInteger,
    String,
    Text,
    Time,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Declarative base with a stable constraint naming convention."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


def _created_at() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


def _tenant() -> Mapped[str]:
    return mapped_column(String(64), ForeignKey("hospitals.id"), index=True, nullable=False)


def _enum(enum_cls: type[enum.Enum], name: str) -> Enum:
    """Stores enums as their string values (readable in SQL and dashboards)."""
    return Enum(enum_cls, name=name, values_callable=lambda e: [m.value for m in e])


# --------------------------------------------------------------------------- #
# Enumerations
# --------------------------------------------------------------------------- #
class AppointmentStatus(enum.StrEnum):
    """Lifecycle of an appointment."""

    BOOKED = "booked"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"
    RESCHEDULED = "rescheduled"
    COMPLETED = "completed"
    NO_SHOW = "no_show"


ACTIVE_APPOINTMENT_STATUSES = (AppointmentStatus.BOOKED, AppointmentStatus.CONFIRMED)


class ConversationStatus(enum.StrEnum):
    """Who currently owns a conversation."""

    BOT = "bot"
    HANDOVER_PENDING = "handover_pending"
    HUMAN = "human"


class MessageDirection(enum.StrEnum):
    """Direction of a message relative to the hospital."""

    INBOUND = "inbound"
    OUTBOUND = "outbound"


class MessageStatus(enum.StrEnum):
    """Delivery status reported by the channel."""

    RECEIVED = "received"
    QUEUED = "queued"
    SENT = "sent"
    DELIVERED = "delivered"
    READ = "read"
    FAILED = "failed"


class ReportStatus(enum.StrEnum):
    """Lifecycle of a report link."""

    READY = "ready"
    NOTIFIED = "notified"
    OPENED = "opened"
    FAILED = "failed"


class FeedbackStatus(enum.StrEnum):
    """Lifecycle of a feedback request."""

    REQUESTED = "requested"
    SCORED = "scored"
    COMPLETED = "completed"
    EXPIRED = "expired"


class TicketStatus(enum.StrEnum):
    """Service recovery ticket lifecycle."""

    OPEN = "open"
    IN_PROGRESS = "in_progress"
    ESCALATED = "escalated"
    RESOLVED = "resolved"
    CLOSED = "closed"


# --------------------------------------------------------------------------- #
# Tenancy and reference data
# --------------------------------------------------------------------------- #
class Hospital(Base):
    """A tenant. Synced from ``config/hospitals/*.yaml`` at start-up."""

    __tablename__ = "hospitals"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Kolkata")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = _created_at()


class Department(Base):
    """A clinical department (Cardiology, Orthopaedics...)."""

    __tablename__ = "departments"
    __table_args__ = (UniqueConstraint("hospital_id", "code"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    hospital_id: Mapped[str] = _tenant()
    code: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(200))
    # Optional localised names: {"ml": "...", "hi": "..."}.
    names: Mapped[dict[str, str]] = mapped_column(JSONB, default=dict)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Doctor(Base):
    """A doctor. Schedules come from the HIS."""

    __tablename__ = "doctors"
    __table_args__ = (UniqueConstraint("hospital_id", "external_id"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    hospital_id: Mapped[str] = _tenant()
    department_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("departments.id"), index=True)
    external_id: Mapped[str] = mapped_column(String(100))
    name: Mapped[str] = mapped_column(String(200))
    qualification: Mapped[str] = mapped_column(String(200), default="")
    languages: Mapped[list[str]] = mapped_column(ARRAY(String(8)), default=list)
    consultation_fee: Mapped[int | None] = mapped_column(Integer)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class DoctorSchedule(Base):
    """A recurring weekly OPD session for a doctor."""

    __tablename__ = "doctor_schedules"

    id: Mapped[uuid.UUID] = _uuid_pk()
    hospital_id: Mapped[str] = _tenant()
    doctor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("doctors.id"), index=True)
    weekday: Mapped[int] = mapped_column(SmallInteger)  # 0 = Monday
    start_time: Mapped[time] = mapped_column(Time)
    end_time: Mapped[time] = mapped_column(Time)
    slot_minutes: Mapped[int] = mapped_column(SmallInteger, default=15)
    capacity_per_slot: Mapped[int] = mapped_column(SmallInteger, default=1)
    valid_from: Mapped[date | None] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date)


class ScheduleException(Base):
    """A date on which a doctor is unavailable (leave, conference...)."""

    __tablename__ = "schedule_exceptions"
    __table_args__ = (UniqueConstraint("doctor_id", "on_date"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    hospital_id: Mapped[str] = _tenant()
    doctor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("doctors.id"))
    on_date: Mapped[date] = mapped_column(Date)
    reason: Mapped[str] = mapped_column(String(200), default="")


# --------------------------------------------------------------------------- #
# Patients and consent
# --------------------------------------------------------------------------- #
class Patient(Base):
    """A patient record, linked to the HIS by MRN when known."""

    __tablename__ = "patients"
    __table_args__ = (UniqueConstraint("hospital_id", "mrn"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    hospital_id: Mapped[str] = _tenant()
    mrn: Mapped[str | None] = mapped_column(String(64))
    full_name: Mapped[str] = mapped_column(String(200))
    date_of_birth: Mapped[date | None] = mapped_column(Date)
    gender: Mapped[str | None] = mapped_column(String(16))
    phone_e164: Mapped[str] = mapped_column(String(20), index=True)
    preferred_language: Mapped[str] = mapped_column(String(8), default="en")
    whatsapp_opt_in: Mapped[bool] = mapped_column(Boolean, default=False)
    opt_in_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    opt_in_source: Mapped[str | None] = mapped_column(String(32))
    opted_out_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created_at()


class PatientContact(Base):
    """A phone number allowed to act for a patient (self, parent, guardian).

    Used for minors and family members: a report is only sent to numbers
    registered against that patient record.
    """

    __tablename__ = "patient_contacts"
    __table_args__ = (UniqueConstraint("patient_id", "phone_e164"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    hospital_id: Mapped[str] = _tenant()
    patient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("patients.id"), index=True)
    phone_e164: Mapped[str] = mapped_column(String(20), index=True)
    relationship: Mapped[str] = mapped_column(String(32), default="self")
    receives_reports: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = _created_at()


class ConsentEvent(Base):
    """Immutable record of every opt-in or opt-out (DPDP evidence)."""

    __tablename__ = "consent_events"

    id: Mapped[uuid.UUID] = _uuid_pk()
    hospital_id: Mapped[str] = _tenant()
    phone_e164: Mapped[str] = mapped_column(String(20), index=True)
    patient_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("patients.id"))
    action: Mapped[str] = mapped_column(String(16))  # opt_in | opt_out
    source: Mapped[str] = mapped_column(
        String(32)
    )  # registration | first_message | keyword | staff
    channel: Mapped[str] = mapped_column(String(32), default="whatsapp")
    evidence: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = _created_at()


# --------------------------------------------------------------------------- #
# Appointments
# --------------------------------------------------------------------------- #
class Appointment(Base):
    """An OPD appointment (or a discharge, for feedback purposes)."""

    __tablename__ = "appointments"
    __table_args__ = (
        Index("ix_appointments_doctor_start", "doctor_id", "start_at"),
        Index("ix_appointments_hospital_start", "hospital_id", "start_at"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    hospital_id: Mapped[str] = _tenant()
    patient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("patients.id"), index=True)
    doctor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("doctors.id"))
    department_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("departments.id"))
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[AppointmentStatus] = mapped_column(
        _enum(AppointmentStatus, "appointment_status"), default=AppointmentStatus.BOOKED
    )
    channel: Mapped[str] = mapped_column(String(32), default="whatsapp")
    visit_type: Mapped[str] = mapped_column(String(16), default="opd")  # opd | discharge
    external_id: Mapped[str | None] = mapped_column(String(100))
    rescheduled_from_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("appointments.id"))
    follow_up_date: Mapped[date | None] = mapped_column(Date)
    checked_out_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


# --------------------------------------------------------------------------- #
# Conversations and messages
# --------------------------------------------------------------------------- #
class Conversation(Base):
    """One running conversation per phone number per hospital."""

    __tablename__ = "conversations"
    __table_args__ = (UniqueConstraint("hospital_id", "phone_e164"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    hospital_id: Mapped[str] = _tenant()
    phone_e164: Mapped[str] = mapped_column(String(20))
    patient_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("patients.id"))
    status: Mapped[ConversationStatus] = mapped_column(
        _enum(ConversationStatus, "conversation_status"), default=ConversationStatus.BOT
    )
    handover_reason: Mapped[str | None] = mapped_column(String(64))
    assigned_staff_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("staff_users.id"))
    language: Mapped[str] = mapped_column(String(8), default="en")
    # Channel-level consent for this phone number: unknown | opted_in | opted_out.
    consent_status: Mapped[str] = mapped_column(String(16), default="unknown")
    consent_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    flow: Mapped[str | None] = mapped_column(String(32))
    flow_state: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    bot_turns_without_progress: Mapped[int] = mapped_column(SmallInteger, default=0)
    last_inbound_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_outbound_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    handover_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created_at()


class Message(Base):
    """Every inbound and outbound message, kept for audit."""

    __tablename__ = "messages"
    __table_args__ = (
        Index("ix_messages_conversation_created", "conversation_id", "created_at"),
        Index("ix_messages_provider_id", "provider_message_id"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    hospital_id: Mapped[str] = _tenant()
    conversation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("conversations.id"))
    direction: Mapped[MessageDirection] = mapped_column(
        _enum(MessageDirection, "message_direction")
    )
    sender: Mapped[str] = mapped_column(String(16))  # patient | bot | staff | system
    staff_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("staff_users.id"))
    provider: Mapped[str] = mapped_column(String(32))
    provider_message_id: Mapped[str | None] = mapped_column(String(128))
    kind: Mapped[str] = mapped_column(String(32))  # text | template | interactive | media | reply
    body: Mapped[str] = mapped_column(Text, default="")
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    intent: Mapped[str | None] = mapped_column(String(48))
    confidence: Mapped[float | None] = mapped_column(Float)
    language: Mapped[str | None] = mapped_column(String(8))
    status: Mapped[MessageStatus] = mapped_column(
        _enum(MessageStatus, "message_status"), default=MessageStatus.QUEUED
    )
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _created_at()


# --------------------------------------------------------------------------- #
# Reports
# --------------------------------------------------------------------------- #
class Report(Base):
    """A finished lab/radiology report, delivered through an expiring link."""

    __tablename__ = "reports"
    __table_args__ = (UniqueConstraint("hospital_id", "external_id"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    hospital_id: Mapped[str] = _tenant()
    patient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("patients.id"), index=True)
    external_id: Mapped[str] = mapped_column(String(100))
    title: Mapped[str] = mapped_column(String(200))
    report_type: Mapped[str] = mapped_column(String(32), default="lab")
    blob_path: Mapped[str] = mapped_column(String(500))
    status: Mapped[ReportStatus] = mapped_column(
        _enum(ReportStatus, "report_status"), default=ReportStatus.READY
    )
    link_token_hash: Mapped[str | None] = mapped_column(String(64), unique=True)
    link_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failed_verifications: Mapped[int] = mapped_column(SmallInteger, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ready_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    first_opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created_at()


class OtpChallenge(Base):
    """A one-time password issued for report access. Only the HMAC is stored."""

    __tablename__ = "otp_challenges"

    id: Mapped[uuid.UUID] = _uuid_pk()
    hospital_id: Mapped[str] = _tenant()
    report_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("reports.id"), index=True)
    phone_e164: Mapped[str] = mapped_column(String(20))
    code_hash: Mapped[str] = mapped_column(String(64))
    channel: Mapped[str] = mapped_column(String(16))
    attempts: Mapped[int] = mapped_column(SmallInteger, default=0)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created_at()


class ReportAccessLog(Base):
    """Audit trail of every report link event."""

    __tablename__ = "report_access_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    hospital_id: Mapped[str] = _tenant()
    report_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("reports.id"), index=True)
    event: Mapped[str] = mapped_column(String(32))
    ip_address: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(300))
    created_at: Mapped[datetime] = _created_at()


# --------------------------------------------------------------------------- #
# Feedback and service recovery
# --------------------------------------------------------------------------- #
class Feedback(Base):
    """NPS score and open comment for a visit."""

    __tablename__ = "feedback"
    __table_args__ = (UniqueConstraint("appointment_id"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    hospital_id: Mapped[str] = _tenant()
    patient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("patients.id"))
    appointment_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("appointments.id"))
    status: Mapped[FeedbackStatus] = mapped_column(
        _enum(FeedbackStatus, "feedback_status"), default=FeedbackStatus.REQUESTED
    )
    nps_score: Mapped[int | None] = mapped_column(SmallInteger)
    comment: Mapped[str | None] = mapped_column(Text)
    sentiment: Mapped[str | None] = mapped_column(String(16))
    categories: Mapped[list[str]] = mapped_column(ARRAY(String(48)), default=list)
    review_invited: Mapped[bool] = mapped_column(Boolean, default=False)
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Ticket(Base):
    """A service-recovery ticket for the patient relations team."""

    __tablename__ = "tickets"

    id: Mapped[uuid.UUID] = _uuid_pk()
    hospital_id: Mapped[str] = _tenant()
    patient_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("patients.id"))
    feedback_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("feedback.id"))
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("conversations.id"))
    category: Mapped[str] = mapped_column(String(48), default="other")
    severity: Mapped[str] = mapped_column(String(16), default="medium")
    summary: Mapped[str] = mapped_column(Text)
    status: Mapped[TicketStatus] = mapped_column(
        _enum(TicketStatus, "ticket_status"), default=TicketStatus.OPEN
    )
    assigned_staff_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("staff_users.id"))
    resolution_note: Mapped[str | None] = mapped_column(Text)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    escalated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created_at()


# --------------------------------------------------------------------------- #
# Staff, audit and idempotency
# --------------------------------------------------------------------------- #
class StaffUser(Base):
    """A staff member, provisioned just-in-time from their Entra ID token."""

    __tablename__ = "staff_users"
    __table_args__ = (UniqueConstraint("hospital_id", "external_oid"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    hospital_id: Mapped[str] = _tenant()
    external_oid: Mapped[str] = mapped_column(String(64))
    email: Mapped[str] = mapped_column(String(200), default="")
    display_name: Mapped[str] = mapped_column(String(200), default="")
    roles: Mapped[list[str]] = mapped_column(ARRAY(String(32)), default=list)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuditLog(Base):
    """Who did what, when – for NABH audits and DPDP accountability."""

    __tablename__ = "audit_logs"
    __table_args__ = (Index("ix_audit_logs_hospital_created", "hospital_id", "created_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    hospital_id: Mapped[str] = _tenant()
    actor_type: Mapped[str] = mapped_column(String(16))  # staff | system | patient
    actor_id: Mapped[str | None] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(64))
    entity_type: Mapped[str | None] = mapped_column(String(32))
    entity_id: Mapped[str | None] = mapped_column(String(64))
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = _created_at()


class NotificationLog(Base):
    """Idempotency guard: one row per (kind, entity) ever notified.

    Scheduled jobs can safely re-run (Logic Apps retries, overlapping CronJobs)
    without sending a patient the same reminder twice.
    """

    __tablename__ = "notification_logs"
    __table_args__ = (UniqueConstraint("hospital_id", "kind", "entity_id"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    hospital_id: Mapped[str] = _tenant()
    kind: Mapped[str] = mapped_column(String(48))
    entity_id: Mapped[str] = mapped_column(String(64))
    provider_message_id: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = _created_at()


class SyncState(Base):
    """High-water marks for incremental HIS pulls (visits, reports)."""

    __tablename__ = "sync_states"
    __table_args__ = (UniqueConstraint("hospital_id", "name"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    hospital_id: Mapped[str] = _tenant()
    name: Mapped[str] = mapped_column(String(48))
    watermark: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class KnowledgeChunk(Base):
    """FAQ/policy chunk for the ``pgvector`` knowledge provider.

    The ``embedding`` column is added by the migration with the configured
    dimension (``vector(N)``) so the ORM stays portable when pgvector is not
    installed; the pgvector adapter queries it with SQL.
    """

    __tablename__ = "knowledge_chunks"

    id: Mapped[uuid.UUID] = _uuid_pk()
    hospital_id: Mapped[str] = _tenant()
    source: Mapped[str] = mapped_column(String(200))
    title: Mapped[str] = mapped_column(String(300))
    content: Mapped[str] = mapped_column(Text)
    language: Mapped[str] = mapped_column(String(8), default="en")
    created_at: Mapped[datetime] = _created_at()


# Tables protected by row-level security (all tenant tables).
TENANT_TABLES = [
    table.name
    for table in Base.metadata.sorted_tables
    if "hospital_id" in table.columns and table.name != "hospitals"
]
