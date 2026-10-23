"""Initial schema: tenants, reference data, patients, consent, appointments,
conversations, messages, reports, feedback, tickets, staff and audit tables.

Revision ID: 0001
Revises:
Create Date: 2026-10-13 18:07:41.069110+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "hospitals",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_hospitals")),
    )
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("hospital_id", sa.String(length=64), nullable=False),
        sa.Column("actor_type", sa.String(length=16), nullable=False),
        sa.Column("actor_id", sa.String(length=64), nullable=True),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("entity_type", sa.String(length=32), nullable=True),
        sa.Column("entity_id", sa.String(length=64), nullable=True),
        sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["hospital_id"], ["hospitals.id"], name=op.f("fk_audit_logs_hospital_id_hospitals")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_logs")),
    )
    op.create_index(
        "ix_audit_logs_hospital_created", "audit_logs", ["hospital_id", "created_at"], unique=False
    )
    op.create_index(op.f("ix_audit_logs_hospital_id"), "audit_logs", ["hospital_id"], unique=False)
    op.create_table(
        "departments",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("hospital_id", sa.String(length=64), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("names", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(
            ["hospital_id"], ["hospitals.id"], name=op.f("fk_departments_hospital_id_hospitals")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_departments")),
        sa.UniqueConstraint("hospital_id", "code", name=op.f("uq_departments_hospital_id")),
    )
    op.create_index(
        op.f("ix_departments_hospital_id"), "departments", ["hospital_id"], unique=False
    )
    op.create_table(
        "knowledge_chunks",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("hospital_id", sa.String(length=64), nullable=False),
        sa.Column("source", sa.String(length=200), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("language", sa.String(length=8), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["hospital_id"],
            ["hospitals.id"],
            name=op.f("fk_knowledge_chunks_hospital_id_hospitals"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_knowledge_chunks")),
    )
    op.create_index(
        op.f("ix_knowledge_chunks_hospital_id"), "knowledge_chunks", ["hospital_id"], unique=False
    )
    op.create_table(
        "notification_logs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("hospital_id", sa.String(length=64), nullable=False),
        sa.Column("kind", sa.String(length=48), nullable=False),
        sa.Column("entity_id", sa.String(length=64), nullable=False),
        sa.Column("provider_message_id", sa.String(length=128), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["hospital_id"],
            ["hospitals.id"],
            name=op.f("fk_notification_logs_hospital_id_hospitals"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_notification_logs")),
        sa.UniqueConstraint(
            "hospital_id", "kind", "entity_id", name=op.f("uq_notification_logs_hospital_id")
        ),
    )
    op.create_index(
        op.f("ix_notification_logs_hospital_id"), "notification_logs", ["hospital_id"], unique=False
    )
    op.create_table(
        "patients",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("hospital_id", sa.String(length=64), nullable=False),
        sa.Column("mrn", sa.String(length=64), nullable=True),
        sa.Column("full_name", sa.String(length=200), nullable=False),
        sa.Column("date_of_birth", sa.Date(), nullable=True),
        sa.Column("gender", sa.String(length=16), nullable=True),
        sa.Column("phone_e164", sa.String(length=20), nullable=False),
        sa.Column("preferred_language", sa.String(length=8), nullable=False),
        sa.Column("whatsapp_opt_in", sa.Boolean(), nullable=False),
        sa.Column("opt_in_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("opt_in_source", sa.String(length=32), nullable=True),
        sa.Column("opted_out_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["hospital_id"], ["hospitals.id"], name=op.f("fk_patients_hospital_id_hospitals")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_patients")),
        sa.UniqueConstraint("hospital_id", "mrn", name=op.f("uq_patients_hospital_id")),
    )
    op.create_index(op.f("ix_patients_hospital_id"), "patients", ["hospital_id"], unique=False)
    op.create_index(op.f("ix_patients_phone_e164"), "patients", ["phone_e164"], unique=False)
    op.create_table(
        "staff_users",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("hospital_id", sa.String(length=64), nullable=False),
        sa.Column("external_oid", sa.String(length=64), nullable=False),
        sa.Column("email", sa.String(length=200), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=False),
        sa.Column("roles", postgresql.ARRAY(sa.String(length=32)), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["hospital_id"], ["hospitals.id"], name=op.f("fk_staff_users_hospital_id_hospitals")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_staff_users")),
        sa.UniqueConstraint("hospital_id", "external_oid", name=op.f("uq_staff_users_hospital_id")),
    )
    op.create_index(
        op.f("ix_staff_users_hospital_id"), "staff_users", ["hospital_id"], unique=False
    )
    op.create_table(
        "sync_states",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("hospital_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=48), nullable=False),
        sa.Column("watermark", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["hospital_id"], ["hospitals.id"], name=op.f("fk_sync_states_hospital_id_hospitals")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sync_states")),
        sa.UniqueConstraint("hospital_id", "name", name=op.f("uq_sync_states_hospital_id")),
    )
    op.create_index(
        op.f("ix_sync_states_hospital_id"), "sync_states", ["hospital_id"], unique=False
    )
    op.create_table(
        "consent_events",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("hospital_id", sa.String(length=64), nullable=False),
        sa.Column("phone_e164", sa.String(length=20), nullable=False),
        sa.Column("patient_id", sa.UUID(), nullable=True),
        sa.Column("action", sa.String(length=16), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("channel", sa.String(length=32), nullable=False),
        sa.Column("evidence", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["hospital_id"], ["hospitals.id"], name=op.f("fk_consent_events_hospital_id_hospitals")
        ),
        sa.ForeignKeyConstraint(
            ["patient_id"], ["patients.id"], name=op.f("fk_consent_events_patient_id_patients")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_consent_events")),
    )
    op.create_index(
        op.f("ix_consent_events_hospital_id"), "consent_events", ["hospital_id"], unique=False
    )
    op.create_index(
        op.f("ix_consent_events_phone_e164"), "consent_events", ["phone_e164"], unique=False
    )
    op.create_table(
        "conversations",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("hospital_id", sa.String(length=64), nullable=False),
        sa.Column("phone_e164", sa.String(length=20), nullable=False),
        sa.Column("patient_id", sa.UUID(), nullable=True),
        sa.Column(
            "status",
            sa.Enum("bot", "handover_pending", "human", name="conversation_status"),
            nullable=False,
        ),
        sa.Column("handover_reason", sa.String(length=64), nullable=True),
        sa.Column("assigned_staff_id", sa.UUID(), nullable=True),
        sa.Column("language", sa.String(length=8), nullable=False),
        sa.Column("consent_status", sa.String(length=16), nullable=False),
        sa.Column("consent_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("flow", sa.String(length=32), nullable=True),
        sa.Column("flow_state", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("bot_turns_without_progress", sa.SmallInteger(), nullable=False),
        sa.Column("last_inbound_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_outbound_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("handover_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["assigned_staff_id"],
            ["staff_users.id"],
            name=op.f("fk_conversations_assigned_staff_id_staff_users"),
        ),
        sa.ForeignKeyConstraint(
            ["hospital_id"], ["hospitals.id"], name=op.f("fk_conversations_hospital_id_hospitals")
        ),
        sa.ForeignKeyConstraint(
            ["patient_id"], ["patients.id"], name=op.f("fk_conversations_patient_id_patients")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_conversations")),
        sa.UniqueConstraint("hospital_id", "phone_e164", name=op.f("uq_conversations_hospital_id")),
    )
    op.create_index(
        op.f("ix_conversations_hospital_id"), "conversations", ["hospital_id"], unique=False
    )
    op.create_table(
        "doctors",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("hospital_id", sa.String(length=64), nullable=False),
        sa.Column("department_id", sa.UUID(), nullable=False),
        sa.Column("external_id", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("qualification", sa.String(length=200), nullable=False),
        sa.Column("languages", postgresql.ARRAY(sa.String(length=8)), nullable=False),
        sa.Column("consultation_fee", sa.Integer(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(
            ["department_id"], ["departments.id"], name=op.f("fk_doctors_department_id_departments")
        ),
        sa.ForeignKeyConstraint(
            ["hospital_id"], ["hospitals.id"], name=op.f("fk_doctors_hospital_id_hospitals")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_doctors")),
        sa.UniqueConstraint("hospital_id", "external_id", name=op.f("uq_doctors_hospital_id")),
    )
    op.create_index(op.f("ix_doctors_department_id"), "doctors", ["department_id"], unique=False)
    op.create_index(op.f("ix_doctors_hospital_id"), "doctors", ["hospital_id"], unique=False)
    op.create_table(
        "patient_contacts",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("hospital_id", sa.String(length=64), nullable=False),
        sa.Column("patient_id", sa.UUID(), nullable=False),
        sa.Column("phone_e164", sa.String(length=20), nullable=False),
        sa.Column("relationship", sa.String(length=32), nullable=False),
        sa.Column("receives_reports", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["hospital_id"],
            ["hospitals.id"],
            name=op.f("fk_patient_contacts_hospital_id_hospitals"),
        ),
        sa.ForeignKeyConstraint(
            ["patient_id"], ["patients.id"], name=op.f("fk_patient_contacts_patient_id_patients")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_patient_contacts")),
        sa.UniqueConstraint(
            "patient_id", "phone_e164", name=op.f("uq_patient_contacts_patient_id")
        ),
    )
    op.create_index(
        op.f("ix_patient_contacts_hospital_id"), "patient_contacts", ["hospital_id"], unique=False
    )
    op.create_index(
        op.f("ix_patient_contacts_patient_id"), "patient_contacts", ["patient_id"], unique=False
    )
    op.create_index(
        op.f("ix_patient_contacts_phone_e164"), "patient_contacts", ["phone_e164"], unique=False
    )
    op.create_table(
        "reports",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("hospital_id", sa.String(length=64), nullable=False),
        sa.Column("patient_id", sa.UUID(), nullable=False),
        sa.Column("external_id", sa.String(length=100), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("report_type", sa.String(length=32), nullable=False),
        sa.Column("blob_path", sa.String(length=500), nullable=False),
        sa.Column(
            "status",
            sa.Enum("ready", "notified", "opened", "failed", name="report_status"),
            nullable=False,
        ),
        sa.Column("link_token_hash", sa.String(length=64), nullable=True),
        sa.Column("link_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_verifications", sa.SmallInteger(), nullable=False),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "ready_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("notified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("first_opened_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["hospital_id"], ["hospitals.id"], name=op.f("fk_reports_hospital_id_hospitals")
        ),
        sa.ForeignKeyConstraint(
            ["patient_id"], ["patients.id"], name=op.f("fk_reports_patient_id_patients")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_reports")),
        sa.UniqueConstraint("hospital_id", "external_id", name=op.f("uq_reports_hospital_id")),
        sa.UniqueConstraint("link_token_hash", name=op.f("uq_reports_link_token_hash")),
    )
    op.create_index(op.f("ix_reports_hospital_id"), "reports", ["hospital_id"], unique=False)
    op.create_index(op.f("ix_reports_patient_id"), "reports", ["patient_id"], unique=False)
    op.create_table(
        "appointments",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("hospital_id", sa.String(length=64), nullable=False),
        sa.Column("patient_id", sa.UUID(), nullable=False),
        sa.Column("doctor_id", sa.UUID(), nullable=False),
        sa.Column("department_id", sa.UUID(), nullable=False),
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "booked",
                "confirmed",
                "cancelled",
                "rescheduled",
                "completed",
                "no_show",
                name="appointment_status",
            ),
            nullable=False,
        ),
        sa.Column("channel", sa.String(length=32), nullable=False),
        sa.Column("visit_type", sa.String(length=16), nullable=False),
        sa.Column("external_id", sa.String(length=100), nullable=True),
        sa.Column("rescheduled_from_id", sa.UUID(), nullable=True),
        sa.Column("follow_up_date", sa.Date(), nullable=True),
        sa.Column("checked_out_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["department_id"],
            ["departments.id"],
            name=op.f("fk_appointments_department_id_departments"),
        ),
        sa.ForeignKeyConstraint(
            ["doctor_id"], ["doctors.id"], name=op.f("fk_appointments_doctor_id_doctors")
        ),
        sa.ForeignKeyConstraint(
            ["hospital_id"], ["hospitals.id"], name=op.f("fk_appointments_hospital_id_hospitals")
        ),
        sa.ForeignKeyConstraint(
            ["patient_id"], ["patients.id"], name=op.f("fk_appointments_patient_id_patients")
        ),
        sa.ForeignKeyConstraint(
            ["rescheduled_from_id"],
            ["appointments.id"],
            name=op.f("fk_appointments_rescheduled_from_id_appointments"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_appointments")),
    )
    op.create_index(
        "ix_appointments_doctor_start", "appointments", ["doctor_id", "start_at"], unique=False
    )
    op.create_index(
        op.f("ix_appointments_hospital_id"), "appointments", ["hospital_id"], unique=False
    )
    op.create_index(
        "ix_appointments_hospital_start", "appointments", ["hospital_id", "start_at"], unique=False
    )
    op.create_index(
        op.f("ix_appointments_patient_id"), "appointments", ["patient_id"], unique=False
    )
    op.create_table(
        "doctor_schedules",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("hospital_id", sa.String(length=64), nullable=False),
        sa.Column("doctor_id", sa.UUID(), nullable=False),
        sa.Column("weekday", sa.SmallInteger(), nullable=False),
        sa.Column("start_time", sa.Time(), nullable=False),
        sa.Column("end_time", sa.Time(), nullable=False),
        sa.Column("slot_minutes", sa.SmallInteger(), nullable=False),
        sa.Column("capacity_per_slot", sa.SmallInteger(), nullable=False),
        sa.Column("valid_from", sa.Date(), nullable=True),
        sa.Column("valid_to", sa.Date(), nullable=True),
        sa.ForeignKeyConstraint(
            ["doctor_id"], ["doctors.id"], name=op.f("fk_doctor_schedules_doctor_id_doctors")
        ),
        sa.ForeignKeyConstraint(
            ["hospital_id"],
            ["hospitals.id"],
            name=op.f("fk_doctor_schedules_hospital_id_hospitals"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_doctor_schedules")),
    )
    op.create_index(
        op.f("ix_doctor_schedules_doctor_id"), "doctor_schedules", ["doctor_id"], unique=False
    )
    op.create_index(
        op.f("ix_doctor_schedules_hospital_id"), "doctor_schedules", ["hospital_id"], unique=False
    )
    op.create_table(
        "messages",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("hospital_id", sa.String(length=64), nullable=False),
        sa.Column("conversation_id", sa.UUID(), nullable=False),
        sa.Column(
            "direction", sa.Enum("inbound", "outbound", name="message_direction"), nullable=False
        ),
        sa.Column("sender", sa.String(length=16), nullable=False),
        sa.Column("staff_id", sa.UUID(), nullable=True),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("provider_message_id", sa.String(length=128), nullable=True),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("intent", sa.String(length=48), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("language", sa.String(length=8), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "received", "queued", "sent", "delivered", "read", "failed", name="message_status"
            ),
            nullable=False,
        ),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversations.id"],
            name=op.f("fk_messages_conversation_id_conversations"),
        ),
        sa.ForeignKeyConstraint(
            ["hospital_id"], ["hospitals.id"], name=op.f("fk_messages_hospital_id_hospitals")
        ),
        sa.ForeignKeyConstraint(
            ["staff_id"], ["staff_users.id"], name=op.f("fk_messages_staff_id_staff_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_messages")),
    )
    op.create_index(
        "ix_messages_conversation_created",
        "messages",
        ["conversation_id", "created_at"],
        unique=False,
    )
    op.create_index(op.f("ix_messages_hospital_id"), "messages", ["hospital_id"], unique=False)
    op.create_index("ix_messages_provider_id", "messages", ["provider_message_id"], unique=False)
    op.create_table(
        "otp_challenges",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("hospital_id", sa.String(length=64), nullable=False),
        sa.Column("report_id", sa.UUID(), nullable=False),
        sa.Column("phone_e164", sa.String(length=20), nullable=False),
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column("channel", sa.String(length=16), nullable=False),
        sa.Column("attempts", sa.SmallInteger(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["hospital_id"], ["hospitals.id"], name=op.f("fk_otp_challenges_hospital_id_hospitals")
        ),
        sa.ForeignKeyConstraint(
            ["report_id"], ["reports.id"], name=op.f("fk_otp_challenges_report_id_reports")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_otp_challenges")),
    )
    op.create_index(
        op.f("ix_otp_challenges_hospital_id"), "otp_challenges", ["hospital_id"], unique=False
    )
    op.create_index(
        op.f("ix_otp_challenges_report_id"), "otp_challenges", ["report_id"], unique=False
    )
    op.create_table(
        "report_access_logs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("hospital_id", sa.String(length=64), nullable=False),
        sa.Column("report_id", sa.UUID(), nullable=False),
        sa.Column("event", sa.String(length=32), nullable=False),
        sa.Column("ip_address", sa.String(length=64), nullable=True),
        sa.Column("user_agent", sa.String(length=300), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["hospital_id"],
            ["hospitals.id"],
            name=op.f("fk_report_access_logs_hospital_id_hospitals"),
        ),
        sa.ForeignKeyConstraint(
            ["report_id"], ["reports.id"], name=op.f("fk_report_access_logs_report_id_reports")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_report_access_logs")),
    )
    op.create_index(
        op.f("ix_report_access_logs_hospital_id"),
        "report_access_logs",
        ["hospital_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_report_access_logs_report_id"), "report_access_logs", ["report_id"], unique=False
    )
    op.create_table(
        "schedule_exceptions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("hospital_id", sa.String(length=64), nullable=False),
        sa.Column("doctor_id", sa.UUID(), nullable=False),
        sa.Column("on_date", sa.Date(), nullable=False),
        sa.Column("reason", sa.String(length=200), nullable=False),
        sa.ForeignKeyConstraint(
            ["doctor_id"], ["doctors.id"], name=op.f("fk_schedule_exceptions_doctor_id_doctors")
        ),
        sa.ForeignKeyConstraint(
            ["hospital_id"],
            ["hospitals.id"],
            name=op.f("fk_schedule_exceptions_hospital_id_hospitals"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_schedule_exceptions")),
        sa.UniqueConstraint("doctor_id", "on_date", name=op.f("uq_schedule_exceptions_doctor_id")),
    )
    op.create_index(
        op.f("ix_schedule_exceptions_hospital_id"),
        "schedule_exceptions",
        ["hospital_id"],
        unique=False,
    )
    op.create_table(
        "feedback",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("hospital_id", sa.String(length=64), nullable=False),
        sa.Column("patient_id", sa.UUID(), nullable=False),
        sa.Column("appointment_id", sa.UUID(), nullable=False),
        sa.Column(
            "status",
            sa.Enum("requested", "scored", "completed", "expired", name="feedback_status"),
            nullable=False,
        ),
        sa.Column("nps_score", sa.SmallInteger(), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("sentiment", sa.String(length=16), nullable=True),
        sa.Column("categories", postgresql.ARRAY(sa.String(length=48)), nullable=False),
        sa.Column("review_invited", sa.Boolean(), nullable=False),
        sa.Column(
            "requested_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("responded_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["appointment_id"],
            ["appointments.id"],
            name=op.f("fk_feedback_appointment_id_appointments"),
        ),
        sa.ForeignKeyConstraint(
            ["hospital_id"], ["hospitals.id"], name=op.f("fk_feedback_hospital_id_hospitals")
        ),
        sa.ForeignKeyConstraint(
            ["patient_id"], ["patients.id"], name=op.f("fk_feedback_patient_id_patients")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_feedback")),
        sa.UniqueConstraint("appointment_id", name=op.f("uq_feedback_appointment_id")),
    )
    op.create_index(op.f("ix_feedback_hospital_id"), "feedback", ["hospital_id"], unique=False)
    op.create_table(
        "tickets",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("hospital_id", sa.String(length=64), nullable=False),
        sa.Column("patient_id", sa.UUID(), nullable=True),
        sa.Column("feedback_id", sa.UUID(), nullable=True),
        sa.Column("conversation_id", sa.UUID(), nullable=True),
        sa.Column("category", sa.String(length=48), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column(
            "status",
            sa.Enum("open", "in_progress", "escalated", "resolved", "closed", name="ticket_status"),
            nullable=False,
        ),
        sa.Column("assigned_staff_id", sa.UUID(), nullable=True),
        sa.Column("resolution_note", sa.Text(), nullable=True),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("escalated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["assigned_staff_id"],
            ["staff_users.id"],
            name=op.f("fk_tickets_assigned_staff_id_staff_users"),
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversations.id"],
            name=op.f("fk_tickets_conversation_id_conversations"),
        ),
        sa.ForeignKeyConstraint(
            ["feedback_id"], ["feedback.id"], name=op.f("fk_tickets_feedback_id_feedback")
        ),
        sa.ForeignKeyConstraint(
            ["hospital_id"], ["hospitals.id"], name=op.f("fk_tickets_hospital_id_hospitals")
        ),
        sa.ForeignKeyConstraint(
            ["patient_id"], ["patients.id"], name=op.f("fk_tickets_patient_id_patients")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tickets")),
    )
    op.create_index(op.f("ix_tickets_hospital_id"), "tickets", ["hospital_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_tickets_hospital_id"), table_name="tickets")
    op.drop_table("tickets")
    op.drop_index(op.f("ix_feedback_hospital_id"), table_name="feedback")
    op.drop_table("feedback")
    op.drop_index(op.f("ix_schedule_exceptions_hospital_id"), table_name="schedule_exceptions")
    op.drop_table("schedule_exceptions")
    op.drop_index(op.f("ix_report_access_logs_report_id"), table_name="report_access_logs")
    op.drop_index(op.f("ix_report_access_logs_hospital_id"), table_name="report_access_logs")
    op.drop_table("report_access_logs")
    op.drop_index(op.f("ix_otp_challenges_report_id"), table_name="otp_challenges")
    op.drop_index(op.f("ix_otp_challenges_hospital_id"), table_name="otp_challenges")
    op.drop_table("otp_challenges")
    op.drop_index("ix_messages_provider_id", table_name="messages")
    op.drop_index(op.f("ix_messages_hospital_id"), table_name="messages")
    op.drop_index("ix_messages_conversation_created", table_name="messages")
    op.drop_table("messages")
    op.drop_index(op.f("ix_doctor_schedules_hospital_id"), table_name="doctor_schedules")
    op.drop_index(op.f("ix_doctor_schedules_doctor_id"), table_name="doctor_schedules")
    op.drop_table("doctor_schedules")
    op.drop_index(op.f("ix_appointments_patient_id"), table_name="appointments")
    op.drop_index("ix_appointments_hospital_start", table_name="appointments")
    op.drop_index(op.f("ix_appointments_hospital_id"), table_name="appointments")
    op.drop_index("ix_appointments_doctor_start", table_name="appointments")
    op.drop_table("appointments")
    op.drop_index(op.f("ix_reports_patient_id"), table_name="reports")
    op.drop_index(op.f("ix_reports_hospital_id"), table_name="reports")
    op.drop_table("reports")
    op.drop_index(op.f("ix_patient_contacts_phone_e164"), table_name="patient_contacts")
    op.drop_index(op.f("ix_patient_contacts_patient_id"), table_name="patient_contacts")
    op.drop_index(op.f("ix_patient_contacts_hospital_id"), table_name="patient_contacts")
    op.drop_table("patient_contacts")
    op.drop_index(op.f("ix_doctors_hospital_id"), table_name="doctors")
    op.drop_index(op.f("ix_doctors_department_id"), table_name="doctors")
    op.drop_table("doctors")
    op.drop_index(op.f("ix_conversations_hospital_id"), table_name="conversations")
    op.drop_table("conversations")
    op.drop_index(op.f("ix_consent_events_phone_e164"), table_name="consent_events")
    op.drop_index(op.f("ix_consent_events_hospital_id"), table_name="consent_events")
    op.drop_table("consent_events")
    op.drop_index(op.f("ix_sync_states_hospital_id"), table_name="sync_states")
    op.drop_table("sync_states")
    op.drop_index(op.f("ix_staff_users_hospital_id"), table_name="staff_users")
    op.drop_table("staff_users")
    op.drop_index(op.f("ix_patients_phone_e164"), table_name="patients")
    op.drop_index(op.f("ix_patients_hospital_id"), table_name="patients")
    op.drop_table("patients")
    op.drop_index(op.f("ix_notification_logs_hospital_id"), table_name="notification_logs")
    op.drop_table("notification_logs")
    op.drop_index(op.f("ix_knowledge_chunks_hospital_id"), table_name="knowledge_chunks")
    op.drop_table("knowledge_chunks")
    op.drop_index(op.f("ix_departments_hospital_id"), table_name="departments")
    op.drop_table("departments")
    op.drop_index(op.f("ix_audit_logs_hospital_id"), table_name="audit_logs")
    op.drop_index("ix_audit_logs_hospital_created", table_name="audit_logs")
    op.drop_table("audit_logs")
    op.drop_table("hospitals")
    for enum_name in (
        "ticket_status",
        "feedback_status",
        "message_status",
        "message_direction",
        "appointment_status",
        "report_status",
        "conversation_status",
    ):
        sa.Enum(name=enum_name).drop(op.get_bind(), checkfirst=True)
