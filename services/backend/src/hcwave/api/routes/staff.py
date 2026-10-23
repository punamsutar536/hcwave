"""Staff API used by the React staff app.

ACS has no staff inbox, so the platform provides the takeover screen:
front-office staff see conversations waiting for a human, take them over,
reply, and hand them back to the bot. Patient relations manage tickets;
management sees the dashboard. Every action is audited.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, time, timedelta
from typing import Annotated, Any, Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import case, select

from hcwave.adapters.messaging.base import OutboundKind, OutboundMessage
from hcwave.api.deps import ServicesDep, StaffDep, StaffScope, require_roles
from hcwave.core.clock import utcnow
from hcwave.core.errors import PolicyViolationError
from hcwave.core.security import normalize_phone
from hcwave.db.audit import record_audit
from hcwave.db.models import (
    Appointment,
    Conversation,
    ConversationStatus,
    Department,
    Doctor,
    Message,
    Patient,
    Ticket,
    TicketStatus,
)
from hcwave.domain import conversations as conv
from hcwave.domain.consent import record_consent
from hcwave.domain.dashboard import summary_for_days
from hcwave.domain.patients import create_patient, patients_for_phone
from hcwave.domain.staff import provision_staff

router = APIRouter(prefix="/staff", tags=["staff"])

FrontOffice = require_roles("front_office", "patient_relations")
PatientRelations = require_roles("patient_relations")
Management = require_roles("unit_head", "patient_relations")


class ReplyRequest(BaseModel):
    """A staff reply to a patient."""

    text: str = Field(min_length=1, max_length=4000)


class TicketUpdate(BaseModel):
    """Changes to a ticket."""

    status: Literal["open", "in_progress", "resolved", "closed"] | None = None
    resolution_note: str | None = Field(default=None, max_length=4000)
    assign_to_me: bool = False


class ConsentRequest(BaseModel):
    """Consent captured at the front desk (registration)."""

    phone: str
    opt_in: bool = True
    full_name: str | None = None
    note: str = Field(default="", max_length=500)


def _conversation_view(c: Conversation, patient_name: str | None) -> dict[str, Any]:
    return {
        "id": str(c.id),
        "phone": c.phone_e164,
        "patient_name": patient_name,
        "status": c.status.value,
        "handover_reason": c.handover_reason,
        "language": c.language,
        "assigned_staff_id": str(c.assigned_staff_id) if c.assigned_staff_id else None,
        "last_inbound_at": c.last_inbound_at.isoformat() if c.last_inbound_at else None,
        "handover_at": c.handover_at.isoformat() if c.handover_at else None,
        "session_open": conv.in_session_window(c, 24),
    }


async def _staff_id(services: ServicesDep, scope: StaffScope) -> uuid.UUID:
    async with services.container.db.tenant_session(scope.hospital.id) as session:
        return (await provision_staff(session, scope.hospital.id, scope.principal)).id


async def _load_conversation(
    session: Any, hospital_id: str, conversation_id: uuid.UUID
) -> Conversation:
    conversation = await session.scalar(
        select(Conversation)
        .where(Conversation.id == conversation_id, Conversation.hospital_id == hospital_id)
        .with_for_update()
    )
    if conversation is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "conversation not found")
    return conversation


@router.get("/me")
async def me(principal: StaffDep, services: ServicesDep) -> dict[str, Any]:
    """The signed-in user and the hospitals they can access."""
    hospitals = services.container.settings.hospitals
    allowed = [
        h
        for h in hospitals.values()
        if h.id in principal.hospital_ids or "*" in principal.hospital_ids
    ]
    return {
        "name": principal.name,
        "email": principal.email,
        "roles": sorted(principal.roles),
        "hospitals": [{"id": h.id, "name": h.name} for h in allowed],
    }


@router.get("/conversations")
async def list_conversations(
    services: ServicesDep,
    scope: StaffScope = FrontOffice,
    state: Annotated[Literal["waiting", "mine", "all"], Query()] = "waiting",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[dict[str, Any]]:
    """Conversations for the takeover screen (emergencies first)."""
    staff_id = await _staff_id(services, scope)
    async with services.container.db.tenant_session(scope.hospital.id) as session:
        query = select(Conversation, Patient.full_name).outerjoin(
            Patient,
            (Patient.phone_e164 == Conversation.phone_e164)
            & (Patient.hospital_id == Conversation.hospital_id),
        )
        if state == "waiting":
            query = query.where(Conversation.status != ConversationStatus.BOT)
        elif state == "mine":
            query = query.where(Conversation.assigned_staff_id == staff_id)
        urgent = case((Conversation.handover_reason.in_(("emergency", "self_harm")), 0), else_=1)
        rows = await session.execute(
            query.order_by(urgent, Conversation.last_inbound_at.desc().nulls_last()).limit(limit)
        )
        seen: set[uuid.UUID] = set()
        result = []
        for conversation, name in rows:
            if conversation.id not in seen:
                seen.add(conversation.id)
                result.append(_conversation_view(conversation, name))
        return result


@router.get("/conversations/{conversation_id}/messages")
async def conversation_messages(
    conversation_id: uuid.UUID,
    services: ServicesDep,
    scope: StaffScope = FrontOffice,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[dict[str, Any]]:
    """Message history (newest last)."""
    async with services.container.db.tenant_session(scope.hospital.id) as session:
        rows = await session.scalars(
            select(Message)
            .where(
                Message.conversation_id == conversation_id, Message.hospital_id == scope.hospital.id
            )
            .order_by(Message.created_at.desc())
            .limit(limit)
        )
        await record_audit(
            session,
            scope.hospital.id,
            "conversation.viewed",
            actor_type="staff",
            actor_id=scope.principal.oid,
            entity_type="conversation",
            entity_id=conversation_id,
        )
        return [
            {
                "id": str(m.id),
                "direction": m.direction.value,
                "sender": m.sender,
                "kind": m.kind,
                "body": m.body,
                "status": m.status.value,
                "intent": m.intent,
                "created_at": m.created_at.isoformat(),
            }
            for m in reversed(list(rows))
        ]


@router.post("/conversations/{conversation_id}/takeover")
async def take_over(
    conversation_id: uuid.UUID, services: ServicesDep, scope: StaffScope = FrontOffice
) -> dict[str, Any]:
    """Assigns the conversation to the caller; the bot goes quiet."""
    staff_id = await _staff_id(services, scope)
    async with services.container.db.tenant_session(scope.hospital.id) as session:
        conversation = await _load_conversation(session, scope.hospital.id, conversation_id)
        conv.takeover(conversation, staff_id)
        await record_audit(
            session,
            scope.hospital.id,
            "conversation.takeover",
            actor_type="staff",
            actor_id=str(staff_id),
            entity_type="conversation",
            entity_id=conversation_id,
        )
        return _conversation_view(conversation, None)


@router.post("/conversations/{conversation_id}/reply")
async def reply(
    conversation_id: uuid.UUID,
    body: ReplyRequest,
    services: ServicesDep,
    scope: StaffScope = FrontOffice,
) -> dict[str, Any]:
    """Sends a free-text staff reply (only inside the 24-hour window)."""
    staff_id = await _staff_id(services, scope)
    async with services.container.db.tenant_session(scope.hospital.id) as session:
        conversation = await _load_conversation(session, scope.hospital.id, conversation_id)
        if conversation.status != ConversationStatus.HUMAN:
            conv.takeover(conversation, staff_id)
        message = OutboundMessage(kind=OutboundKind.TEXT, text=body.text)
        try:
            row = await services.messenger.send(
                session, scope.hospital, conversation, message, sender="staff", staff_id=staff_id
            )
        except PolicyViolationError as exc:
            raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
        await record_audit(
            session,
            scope.hospital.id,
            "conversation.reply",
            actor_type="staff",
            actor_id=str(staff_id),
            entity_type="conversation",
            entity_id=conversation_id,
        )
        return {"id": str(row.id), "status": row.status.value, "error": row.error}


@router.post("/conversations/{conversation_id}/release")
async def release(
    conversation_id: uuid.UUID, services: ServicesDep, scope: StaffScope = FrontOffice
) -> dict[str, Any]:
    """Hands the conversation back to the bot."""
    async with services.container.db.tenant_session(scope.hospital.id) as session:
        conversation = await _load_conversation(session, scope.hospital.id, conversation_id)
        conv.release(conversation)
        await record_audit(
            session,
            scope.hospital.id,
            "conversation.release",
            actor_type="staff",
            actor_id=scope.principal.oid,
            entity_type="conversation",
            entity_id=conversation_id,
        )
        return _conversation_view(conversation, None)


@router.get("/tickets")
async def list_tickets(
    services: ServicesDep,
    scope: StaffScope = PatientRelations,
    state: Annotated[Literal["open", "all"], Query()] = "open",
) -> list[dict[str, Any]]:
    """Service-recovery tickets, most urgent first."""
    async with services.container.db.tenant_session(scope.hospital.id) as session:
        query = select(Ticket, Patient.full_name, Patient.phone_e164).outerjoin(
            Patient, Patient.id == Ticket.patient_id
        )
        if state == "open":
            query = query.where(
                Ticket.status.in_(
                    (TicketStatus.OPEN, TicketStatus.IN_PROGRESS, TicketStatus.ESCALATED)
                )
            )
        rows = await session.execute(query.order_by(Ticket.due_at).limit(200))
        return [
            {
                "id": str(t.id),
                "category": t.category,
                "severity": t.severity,
                "summary": t.summary,
                "status": t.status.value,
                "patient_name": name,
                "patient_phone": phone,
                "due_at": t.due_at.isoformat(),
                "overdue": t.due_at < utcnow()
                and t.status not in (TicketStatus.RESOLVED, TicketStatus.CLOSED),
                "created_at": t.created_at.isoformat(),
                "resolution_note": t.resolution_note,
            }
            for t, name, phone in rows
        ]


@router.patch("/tickets/{ticket_id}")
async def update_ticket(
    ticket_id: uuid.UUID,
    body: TicketUpdate,
    services: ServicesDep,
    scope: StaffScope = PatientRelations,
) -> dict[str, str]:
    """Updates status, note or assignment of a ticket."""
    staff_id = await _staff_id(services, scope)
    async with services.container.db.tenant_session(scope.hospital.id) as session:
        ticket = await session.scalar(
            select(Ticket)
            .where(Ticket.id == ticket_id, Ticket.hospital_id == scope.hospital.id)
            .with_for_update()
        )
        if ticket is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "ticket not found")
        if body.status:
            ticket.status = TicketStatus(body.status)
            if ticket.status in (TicketStatus.RESOLVED, TicketStatus.CLOSED):
                ticket.resolved_at = ticket.resolved_at or utcnow()
        if body.resolution_note is not None:
            ticket.resolution_note = body.resolution_note
        if body.assign_to_me:
            ticket.assigned_staff_id = staff_id
        await record_audit(
            session,
            scope.hospital.id,
            "ticket.updated",
            actor_type="staff",
            actor_id=str(staff_id),
            entity_type="ticket",
            entity_id=ticket_id,
            status=ticket.status.value,
        )
        return {"id": str(ticket.id), "status": ticket.status.value}


@router.get("/appointments")
async def appointments_for_day(
    services: ServicesDep,
    scope: StaffScope = FrontOffice,
    day: Annotated[date | None, Query()] = None,
) -> list[dict[str, Any]]:
    """The day's appointments for the front desk."""
    tz = ZoneInfo(scope.hospital.timezone)
    day = day or utcnow().astimezone(tz).date()
    start = datetime.combine(day, time.min, tz)
    async with services.container.db.tenant_session(scope.hospital.id) as session:
        rows = await session.execute(
            select(Appointment, Patient.full_name, Patient.phone_e164, Doctor.name, Department.name)
            .join(Patient, Patient.id == Appointment.patient_id)
            .join(Doctor, Doctor.id == Appointment.doctor_id)
            .join(Department, Department.id == Appointment.department_id)
            .where(
                Appointment.hospital_id == scope.hospital.id,
                Appointment.start_at >= start,
                Appointment.start_at < start + timedelta(days=1),
            )
            .order_by(Appointment.start_at)
        )
        return [
            {
                "id": str(a.id),
                "start_at": a.start_at.isoformat(),
                "status": a.status.value,
                "channel": a.channel,
                "patient_name": patient,
                "patient_phone": phone,
                "doctor": doctor,
                "department": department,
            }
            for a, patient, phone, doctor, department in rows
        ]


@router.post("/consent")
async def capture_consent(
    body: ConsentRequest, services: ServicesDep, scope: StaffScope = FrontOffice
) -> dict[str, str]:
    """Records WhatsApp consent given at registration (DPDP evidence)."""
    staff_id = await _staff_id(services, scope)
    phone = normalize_phone(
        body.phone, services.container.settings.conversation.default_country_code
    )
    async with services.container.db.tenant_session(scope.hospital.id) as session:
        conversation = await conv.get_or_create_conversation(
            session, scope.hospital.id, phone, language=scope.hospital.default_language
        )
        patients = await patients_for_phone(session, scope.hospital.id, phone)
        if not patients and body.full_name:
            patients = [
                await create_patient(
                    session, scope.hospital.id, full_name=body.full_name, phone=phone
                )
            ]
        await record_consent(
            session,
            conversation,
            opt_in=body.opt_in,
            source="staff",
            evidence=f"staff:{staff_id} {body.note}".strip(),
            patients=patients,
        )
        await record_audit(
            session,
            scope.hospital.id,
            "consent.captured",
            actor_type="staff",
            actor_id=str(staff_id),
            entity_type="conversation",
            entity_id=conversation.id,
            opt_in=body.opt_in,
        )
        return {"status": conversation.consent_status}


@router.get("/dashboard/summary")
async def dashboard_summary(
    services: ServicesDep,
    scope: StaffScope = Management,
    days: Annotated[int, Query(ge=1, le=365)] = 30,
) -> dict[str, Any]:
    """Built-in KPI tiles: access, appointments, reports, experience."""
    async with services.container.db.tenant_session(scope.hospital.id) as session:
        return await summary_for_days(session, scope.hospital.id, days)


@router.get("/dashboard/embed")
async def dashboard_embed(services: ServicesDep, scope: StaffScope = Management) -> dict[str, Any]:
    """Embed configuration for Power BI Embedded / Grafana / built-in tiles."""
    return await services.container.dashboard.embed_config(scope.hospital.id, scope.principal.email)
