"""Deterministic guided flows driven by buttons and lists.

* ``menu``         main menu
* ``booking``      department → doctor → date → slot → patient → confirm
* ``manage``       upcoming appointments → reschedule / cancel
* ``availability`` department → doctor → weekly OPD schedule
* ``feedback``     0–10 score → open comment → service recovery

Button/list payloads are ``<prefix>:<value>`` strings. Payloads that can
arrive at any time (main menu, reminder buttons) are handled globally by
:func:`dispatch_payload`, regardless of the active flow.
"""

from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime

from hcwave.adapters.messaging.base import Choice, OutboundMessage
from hcwave.agent.context import TurnContext
from hcwave.core.clock import format_local
from hcwave.core.errors import ConflictError
from hcwave.db.models import (
    ACTIVE_APPOINTMENT_STATUSES,
    Appointment,
    AppointmentStatus,
    Department,
    Doctor,
    Feedback,
    FeedbackStatus,
    Patient,
)
from hcwave.domain.context import doctor_with_department
from hcwave.domain.conversations import clear_flow
from hcwave.domain.patients import create_patient

_log = logging.getLogger(__name__)
_NAME_PATTERN = re.compile(r"^[^\d@#$%^&*_=+<>{}\[\]|\\/~`]{2,100}$")
_SCORE_PATTERN = re.compile(r"^\s*(\d{1,2})\s*(?:/\s*10)?\s*$")


@dataclass
class FlowResult:
    """Outcome of handling input inside a flow.

    Attributes:
        replies: Messages to send.
        handover_reason: Set to hand the conversation to staff.
        fallthrough: True when the flow did not handle the input and the
            intent classifier should take over.
        faq_query: Route to the FAQ node with this query.
    """

    replies: list[OutboundMessage] = field(default_factory=list)
    handover_reason: str | None = None
    fallthrough: bool = False
    faq_query: str | None = None


def _ids(ctx: TurnContext) -> list[uuid.UUID]:
    return [p.id for p in ctx.patients]


def _when(ctx: TurnContext, moment: datetime) -> str:
    return format_local(moment, ctx.hospital.timezone)


def _progress(ctx: TurnContext) -> None:
    ctx.conversation.bot_turns_without_progress = 0


def resolve_selection(ctx: TurnContext, text: str, reply_id: str | None) -> str | None:
    """Maps a button/list reply, a number or an option title to a payload."""
    if reply_id:
        return reply_id
    options = (ctx.conversation.flow_state or {}).get("options", [])
    cleaned = text.strip().rstrip(".")
    if cleaned.isdigit() and 1 <= int(cleaned) <= len(options):
        return options[int(cleaned) - 1]["id"]
    for option in options:
        if option["title"].casefold() == cleaned.casefold():
            return option["id"]
    return None


def invalid_input(ctx: TurnContext, key: str = "flow.invalid_choice") -> FlowResult:
    """Re-prompts; after too many invalid inputs, lets the classifier decide."""
    ctx.conversation.bot_turns_without_progress += 1
    if (
        ctx.conversation.bot_turns_without_progress
        > ctx.settings.conversation.max_invalid_flow_inputs
    ):
        clear_flow(ctx.conversation)
        _progress(ctx)
        return FlowResult(fallthrough=True)
    return FlowResult([ctx.text(key)])


# --------------------------------------------------------------------------- #
# Main menu and global payloads
# --------------------------------------------------------------------------- #
def main_menu(ctx: TurnContext) -> FlowResult:
    """Shows the main menu."""
    keys = ["book", "manage", "availability", "packages", "location", "insurance", "human"]
    choices = [Choice(f"menu:{k}", ctx.t(f"menu.{k}")[:24]) for k in keys]
    clear_flow(ctx.conversation)
    ctx.set_state(flow="menu", step="menu")
    message = ctx.options_message(
        ctx.t("menu.body"), ctx.t("menu.button"), choices, header=ctx.t("menu.header")
    )
    return FlowResult([message])


async def dispatch_payload(ctx: TurnContext, payload: str) -> FlowResult | None:
    """Handles payloads valid at any time. Returns None if not global."""
    prefix, _, value = payload.partition(":")
    if prefix == "menu":
        return await _menu_choice(ctx, value)
    if prefix in {
        "remind_confirm",
        "remind_cancel",
        "remind_resched",
        "appt_cancel",
        "appt_resched",
    }:
        return await _appointment_action(ctx, prefix.split("_", 1)[1], value)
    if prefix in {"followup_book", "book_doc"}:
        return await start_booking(ctx, doctor_id=value)
    return None


async def _menu_choice(ctx: TurnContext, value: str) -> FlowResult:
    if value == "book":
        return await start_booking(ctx)
    if value == "manage":
        return await start_manage(ctx)
    if value == "availability":
        return await start_availability(ctx)
    if value in {"packages", "location", "insurance"}:
        clear_flow(ctx.conversation)
        return FlowResult(faq_query=ctx.t(f"menu.query.{value}"))
    if value == "human":
        return FlowResult(handover_reason="requested")
    return main_menu(ctx)


async def _appointment_action(ctx: TurnContext, action: str, appointment_id: str) -> FlowResult:
    """Confirm / cancel / reschedule from reminder buttons or the manage flow."""
    booking = ctx.services.booking
    appointment = await booking.owned_appointment(
        ctx.session, ctx.hospital.id, appointment_id, _ids(ctx)
    )
    allowed = ACTIVE_APPOINTMENT_STATUSES + (
        (AppointmentStatus.NO_SHOW,) if action == "resched" else ()
    )
    if appointment is None or appointment.status not in allowed:
        clear_flow(ctx.conversation)
        return FlowResult([ctx.text("reminder.not_found")])
    doctor, _department = await doctor_with_department(ctx.session, appointment.doctor_id)
    when = _when(ctx, appointment.start_at)
    if action == "confirm":
        booking.confirm(appointment)
        return FlowResult([ctx.text("reminder.confirmed", when=when)])
    if action == "cancel":
        booking.cancel(appointment)
        clear_flow(ctx.conversation)
        return FlowResult(
            [ctx.text("manage.cancelled", doctor=doctor.name if doctor else "", when=when)]
        )
    reschedule_of = appointment.id if appointment.status in ACTIVE_APPOINTMENT_STATUSES else None
    return await start_booking(
        ctx,
        doctor_id=str(appointment.doctor_id),
        reschedule_of=reschedule_of,
        patient_id=appointment.patient_id,
    )


# --------------------------------------------------------------------------- #
# Booking
# --------------------------------------------------------------------------- #
async def start_booking(
    ctx: TurnContext,
    *,
    doctor_id: str | None = None,
    reschedule_of: uuid.UUID | None = None,
    patient_id: uuid.UUID | None = None,
) -> FlowResult:
    """Starts (or restarts) the booking flow, optionally with a preset doctor."""
    if not (ctx.hospital.features.booking and ctx.hospital.features.assistant):
        return FlowResult([ctx.text("feature.disabled")])
    clear_flow(ctx.conversation)
    ctx.set_state(
        flow="booking",
        step="department",
        reschedule_of=str(reschedule_of) if reschedule_of else None,
        patient_id=str(patient_id) if patient_id else None,
    )
    if doctor_id:
        doctor = await _doctor(ctx, doctor_id)
        if doctor is not None:
            ctx.set_state(doctor_id=str(doctor.id))
            return await _present_dates(ctx, doctor)
    return await _present_departments(ctx)


async def _doctor(ctx: TurnContext, doctor_id: str) -> Doctor | None:
    try:
        doctor = await ctx.session.get(Doctor, uuid.UUID(doctor_id))
    except ValueError:
        return None
    return (
        doctor
        if doctor is not None and doctor.active and doctor.hospital_id == ctx.hospital.id
        else None
    )


def _department_name(ctx: TurnContext, department: Department) -> str:
    return (department.names or {}).get(ctx.language) or department.name


async def _present_departments(ctx: TurnContext, flow_step: str = "department") -> FlowResult:
    departments = await ctx.services.booking.departments(ctx.session, ctx.hospital.id)
    if not departments:
        clear_flow(ctx.conversation)
        return FlowResult([ctx.text("booking.no_doctors")])
    ctx.set_state(step=flow_step)
    choices = [Choice(f"dept:{d.id}", _department_name(ctx, d)[:24]) for d in departments]
    return FlowResult(
        [
            ctx.options_message(
                ctx.t("booking.choose_department"), ctx.t("booking.department_button"), choices
            )
        ]
    )


async def _present_doctors(
    ctx: TurnContext, department_id: str, flow_step: str = "doctor"
) -> FlowResult:
    try:
        department = await ctx.session.get(Department, uuid.UUID(department_id))
    except ValueError:
        department = None
    if department is None:
        return invalid_input(ctx)
    doctors = await ctx.services.booking.doctors(ctx.session, ctx.hospital.id, department.id)
    if not doctors:
        return FlowResult([ctx.text("booking.no_doctors")])
    ctx.set_state(step=flow_step, department_id=str(department.id))
    choices = [Choice(f"doc:{d.id}", d.name[:24], d.qualification[:72]) for d in doctors]
    body = ctx.t("booking.choose_doctor", department=_department_name(ctx, department))
    return FlowResult([ctx.options_message(body, ctx.t("booking.doctor_button"), choices)])


async def _present_dates(ctx: TurnContext, doctor: Doctor) -> FlowResult:
    dates = await ctx.services.booking.available_dates(ctx.session, ctx.hospital, doctor.id)
    if not dates:
        ctx.set_state(step="doctor")
        days = ctx.settings.booking.days_ahead
        return FlowResult([ctx.text("booking.no_dates", doctor=doctor.name, days=days)])
    ctx.set_state(step="date", doctor_id=str(doctor.id))
    choices = [
        Choice(f"date:{d.isoformat()}", f"{ctx.t(f'day.{d.weekday()}')[:10]} {d.strftime('%d %b')}")
        for d in dates
    ]
    body = ctx.t("booking.choose_date", doctor=doctor.name)
    return FlowResult([ctx.options_message(body, ctx.t("booking.date_button"), choices)])


async def _present_slots(ctx: TurnContext, doctor: Doctor, day: date) -> FlowResult:
    slots = await ctx.services.booking.slots_for_day(ctx.session, ctx.hospital, doctor.id, day)
    if not slots:
        return await _present_dates(ctx, doctor)
    limit = ctx.settings.booking.max_slots_shown
    ctx.set_state(step="slot", date=day.isoformat())
    choices = [
        Choice(
            f"slot:{s.start_at.isoformat()}",
            format_local(s.start_at, ctx.hospital.timezone, "%I:%M %p"),
        )
        for s in slots[:limit]
    ]
    body = ctx.t("booking.choose_slot", date=day.strftime("%d %b %Y"))
    return FlowResult([ctx.options_message(body, ctx.t("booking.slot_button"), choices)])


async def _after_slot(ctx: TurnContext) -> FlowResult:
    state = ctx.conversation.flow_state
    if state.get("patient_id"):
        return await _confirm_prompt(ctx)
    if ctx.patients:
        ctx.set_state(step="patient")
        choices = [Choice(f"pat:{p.id}", p.full_name[:24]) for p in ctx.patients[:9]]
        choices.append(Choice("pat:new", ctx.t("booking.new_patient")[:24]))
        return FlowResult(
            [
                ctx.options_message(
                    ctx.t("booking.choose_patient"), ctx.t("booking.patient_button"), choices
                )
            ]
        )
    ctx.set_state(step="name")
    return FlowResult([ctx.text("booking.ask_name")])


async def _confirm_prompt(ctx: TurnContext) -> FlowResult:
    state = ctx.conversation.flow_state
    doctor, department = await doctor_with_department(ctx.session, uuid.UUID(state["doctor_id"]))
    if state.get("patient_id"):
        patient = await ctx.session.get(Patient, uuid.UUID(state["patient_id"]))
        patient_name = patient.full_name if patient else ""
    else:
        patient_name = state.get("new_name", "")
    ctx.set_state(step="confirm")
    body = ctx.t(
        "booking.confirm",
        patient=patient_name,
        doctor=doctor.name if doctor else "",
        department=department.name if department else "",
        when=_when(ctx, datetime.fromisoformat(state["start_at"])),
    )
    choices = [
        Choice("book:confirm", ctx.t("booking.confirm_yes")[:20]),
        Choice("book:cancel", ctx.t("booking.confirm_no")[:20]),
    ]
    return FlowResult([ctx.options_message(body, ctx.t("booking.confirm_yes"), choices)])


def _parse_dob(text: str) -> date | None:
    match = re.match(r"^\s*(\d{1,2})[-/. ](\d{1,2})[-/. ](\d{4})\s*$", text)
    if not match:
        return None
    try:
        parsed = date(int(match.group(3)), int(match.group(2)), int(match.group(1)))
    except ValueError:
        return None
    return parsed if date(1900, 1, 1) <= parsed <= date.today() else None


async def _complete_booking(ctx: TurnContext) -> FlowResult:
    state = ctx.conversation.flow_state
    session, hospital = ctx.session, ctx.hospital
    if state.get("patient_id"):
        patient_id = uuid.UUID(state["patient_id"])
        if patient_id not in _ids(ctx):
            return main_menu(ctx)
    else:
        patient = await create_patient(
            session,
            hospital.id,
            full_name=state["new_name"],
            phone=ctx.conversation.phone_e164,
            date_of_birth=date.fromisoformat(state["new_dob"]) if state.get("new_dob") else None,
            language=ctx.language,
            relationship="self" if not ctx.patients else "family",
        )
        ctx.patients.append(patient)
        patient_id = patient.id
        ctx.set_state(patient_id=str(patient_id))

    reschedule_of = None
    if state.get("reschedule_of"):
        reschedule_of = await ctx.services.booking.owned_appointment(
            session, hospital.id, state["reschedule_of"], _ids(ctx)
        )
    doctor = await _doctor(ctx, state["doctor_id"])
    if doctor is None:
        return main_menu(ctx)
    try:
        appointment = await ctx.services.booking.book(
            session,
            hospital,
            patient_id=patient_id,
            doctor_id=doctor.id,
            start_at=datetime.fromisoformat(state["start_at"]),
            reschedule_of=reschedule_of,
        )
    except ConflictError:
        result = await _present_slots(ctx, doctor, date.fromisoformat(state["date"]))
        return FlowResult([ctx.text("booking.slot_taken"), *result.replies])
    await _push_to_his(ctx, appointment, doctor)
    clear_flow(ctx.conversation)
    _progress(ctx)
    key = "booking.rescheduled" if reschedule_of else "booking.confirmed"
    return FlowResult([ctx.text(key, doctor=doctor.name, when=_when(ctx, appointment.start_at))])


async def _push_to_his(ctx: TurnContext, appointment: Appointment, doctor: Doctor) -> None:
    """Pushes the booking to the HIS when it exposes a write API."""
    try:
        external_id = await ctx.services.container.his_for(ctx.hospital).push_appointment(
            ctx.hospital,
            {
                "appointment_id": str(appointment.id),
                "doctor_external_id": doctor.external_id,
                "start_at": appointment.start_at.isoformat(),
                "patient_phone": ctx.conversation.phone_e164,
            },
        )
    except Exception:  # noqa: BLE001 - HIS outages must not block booking
        _log.exception("HIS push failed; appointment kept locally")
        return
    if external_id:
        appointment.external_id = external_id


async def booking_step(ctx: TurnContext, text: str, reply_id: str | None) -> FlowResult:
    """Advances the booking flow by one input."""
    state = ctx.conversation.flow_state
    step = state.get("step")

    if step == "name":
        if not _NAME_PATTERN.match(text.strip()):
            return invalid_input(ctx, "booking.invalid_name")
        _progress(ctx)
        ctx.set_state(new_name=" ".join(text.split()))
        if ctx.settings.booking.collect_date_of_birth:
            ctx.set_state(step="dob")
            return FlowResult([ctx.text("booking.ask_dob")])
        return await _confirm_prompt(ctx)
    if step == "dob":
        dob = _parse_dob(text)
        if dob is None:
            return invalid_input(ctx, "booking.invalid_dob")
        _progress(ctx)
        ctx.set_state(new_dob=dob.isoformat())
        return await _confirm_prompt(ctx)

    selection = resolve_selection(ctx, text, reply_id)
    if selection is None:
        return invalid_input(ctx)
    prefix, _, value = selection.partition(":")
    _progress(ctx)
    if step == "department" and prefix == "dept":
        return await _present_doctors(ctx, value)
    if step in {"doctor", "date"} and prefix == "doc":
        doctor = await _doctor(ctx, value)
        return await _present_dates(ctx, doctor) if doctor else invalid_input(ctx)
    if step == "date" and prefix == "date":
        doctor = await _doctor(ctx, state["doctor_id"])
        return (
            await _present_slots(ctx, doctor, date.fromisoformat(value))
            if doctor
            else main_menu(ctx)
        )
    if step == "slot" and prefix == "slot":
        ctx.set_state(start_at=value)
        return await _after_slot(ctx)
    if step == "patient" and prefix == "pat":
        if value == "new":
            ctx.set_state(step="name", patient_id=None)
            return FlowResult([ctx.text("booking.ask_name")])
        ctx.set_state(patient_id=value)
        return await _confirm_prompt(ctx)
    if step == "confirm" and prefix == "book":
        if value == "confirm":
            return await _complete_booking(ctx)
        clear_flow(ctx.conversation)
        return FlowResult([ctx.text("booking.aborted")])
    return await dispatch_payload(ctx, selection) or invalid_input(ctx)


# --------------------------------------------------------------------------- #
# Manage appointments
# --------------------------------------------------------------------------- #
async def start_manage(ctx: TurnContext) -> FlowResult:
    """Lists upcoming appointments for every patient linked to this phone."""
    appointments = await ctx.services.booking.upcoming(ctx.session, ctx.hospital.id, _ids(ctx))
    if not appointments:
        clear_flow(ctx.conversation)
        return FlowResult([ctx.text("manage.none")])
    clear_flow(ctx.conversation)
    ctx.set_state(flow="manage", step="appointment")
    choices = []
    for appointment in appointments:
        doctor, _department = await doctor_with_department(ctx.session, appointment.doctor_id)
        choices.append(
            Choice(
                f"appt:{appointment.id}",
                (doctor.name if doctor else "")[:24],
                _when(ctx, appointment.start_at),
            )
        )
    return FlowResult(
        [ctx.options_message(ctx.t("manage.choose"), ctx.t("manage.button"), choices)]
    )


async def manage_step(ctx: TurnContext, text: str, reply_id: str | None) -> FlowResult:
    """Handles the chosen appointment and the action on it."""
    selection = resolve_selection(ctx, text, reply_id)
    if selection is None:
        return invalid_input(ctx)
    prefix, _, value = selection.partition(":")
    if prefix == "appt":
        appointment = await ctx.services.booking.owned_appointment(
            ctx.session, ctx.hospital.id, value, _ids(ctx)
        )
        if appointment is None:
            return FlowResult([ctx.text("reminder.not_found")])
        ctx.set_state(step="action")
        choices = [
            Choice(f"appt_resched:{appointment.id}", ctx.t("manage.reschedule")[:20]),
            Choice(f"appt_cancel:{appointment.id}", ctx.t("manage.cancel")[:20]),
            Choice("menu:main", ctx.t("manage.back")[:20]),
        ]
        body = ctx.t("manage.what", when=_when(ctx, appointment.start_at))
        return FlowResult([ctx.options_message(body, ctx.t("manage.button"), choices)])
    return await dispatch_payload(ctx, selection) or invalid_input(ctx)


# --------------------------------------------------------------------------- #
# Doctor availability
# --------------------------------------------------------------------------- #
async def start_availability(ctx: TurnContext) -> FlowResult:
    """Department → doctor → weekly schedule."""
    clear_flow(ctx.conversation)
    ctx.set_state(flow="availability")
    return await _present_departments(ctx, flow_step="department")


async def availability_step(ctx: TurnContext, text: str, reply_id: str | None) -> FlowResult:
    """Shows the doctor's weekly OPD schedule with a Book button."""
    selection = resolve_selection(ctx, text, reply_id)
    if selection is None:
        return invalid_input(ctx)
    prefix, _, value = selection.partition(":")
    if prefix == "dept":
        return await _present_doctors(ctx, value, flow_step="doctor")
    if prefix == "doc":
        doctor = await _doctor(ctx, value)
        if doctor is None:
            return invalid_input(ctx)
        _doc, department = await doctor_with_department(ctx.session, doctor.id)
        sessions = await ctx.services.booking.schedules(ctx.session, doctor.id)
        clear_flow(ctx.conversation)
        if not sessions:
            return FlowResult([ctx.text("availability.no_schedule", doctor=doctor.name)])
        lines = [
            f"• {ctx.t(f'day.{s.weekday}')}: {s.start_time.strftime('%I:%M %p')} – {s.end_time.strftime('%I:%M %p')}"
            for s in sessions
        ]
        body = ctx.t(
            "availability.schedule",
            doctor=doctor.name,
            department=department.name if department else "",
            schedule="\n".join(lines),
        )
        choices = [
            Choice(f"book_doc:{doctor.id}", ctx.t("availability.book")[:20]),
            Choice("menu:main", ctx.t("manage.back")[:20]),
        ]
        return FlowResult([ctx.options_message(body, ctx.t("menu.button"), choices)])
    return await dispatch_payload(ctx, selection) or invalid_input(ctx)


# --------------------------------------------------------------------------- #
# Feedback
# --------------------------------------------------------------------------- #
async def feedback_step(ctx: TurnContext, text: str, reply_id: str | None) -> FlowResult:
    """Collects the 0–10 score, then the open comment."""
    state = ctx.conversation.flow_state
    try:
        feedback = await ctx.session.get(Feedback, uuid.UUID(state.get("feedback_id", "")))
    except ValueError:
        feedback = None
    if feedback is None or feedback.status not in (FeedbackStatus.REQUESTED, FeedbackStatus.SCORED):
        clear_flow(ctx.conversation)
        return FlowResult(fallthrough=True)
    service = ctx.services.feedback

    if state.get("step") == "score":
        match = _SCORE_PATTERN.match(text)
        if not match or int(match.group(1)) > 10:
            if reply_id:  # a button from another message – handle it normally
                return await dispatch_payload(ctx, reply_id) or invalid_input(
                    ctx, "feedback.invalid_score"
                )
            return invalid_input(ctx, "feedback.invalid_score")
        service.record_score(feedback, int(match.group(1)))
        _progress(ctx)
        ctx.set_state(step="comment")
        return FlowResult([ctx.text("feedback.ask_comment")])

    skip_words = {ctx.t("feedback.skip_keyword").casefold(), "skip", "no", "nothing"}
    comment = None if text.strip().casefold() in skip_words else text.strip()[:2000]
    replies = await service.record_comment(
        ctx.session, ctx.hospital, ctx.conversation, feedback, comment
    )
    return FlowResult(replies)


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #
_FLOW_HANDLERS = {
    "booking": booking_step,
    "manage": manage_step,
    "availability": availability_step,
    "feedback": feedback_step,
}


async def handle_flow_input(ctx: TurnContext, text: str, reply_id: str | None) -> FlowResult:
    """Routes input to the active flow, or to a global payload handler."""
    flow = ctx.conversation.flow
    if flow in _FLOW_HANDLERS:
        return await _FLOW_HANDLERS[flow](ctx, text, reply_id)
    selection = resolve_selection(ctx, text, reply_id) if flow == "menu" else reply_id
    if selection:
        result = await dispatch_payload(ctx, selection)
        if result is not None:
            return result
    clear_flow(ctx.conversation)
    return FlowResult(fallthrough=True)
