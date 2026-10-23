"""Internal job API – served only on the private listener (port 8001).

Called by Azure Logic Apps (recurrence workflows), Azure Durable Functions
activities and, optionally, Kubernetes CronJobs. Authenticated with managed
identity tokens (or a shared secret on other clouds).
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field

from hcwave.api.deps import InternalDep, ServicesDep
from hcwave.core.security import normalize_phone
from hcwave.domain.consent import record_consent
from hcwave.domain.conversations import get_or_create_conversation
from hcwave.domain.patients import patients_for_phone
from hcwave.jobs.runner import JOB_NAMES, JobRunner

router = APIRouter(prefix="/internal", tags=["internal"])


class JobRequest(BaseModel):
    """Optional job parameters."""

    hospital_ids: list[str] | None = None
    rules: list[str] | None = None


class ConsentEvent(BaseModel):
    """Consent captured by the HIS at registration."""

    hospital_id: str
    phone: str
    opt_in: bool
    source: str = Field(default="registration", pattern="^(registration|staff|his)$")
    evidence: str = Field(default="", max_length=500)


@router.post("/jobs/{name}")
async def run_job(
    name: str, request: Request, services: ServicesDep, caller: InternalDep
) -> dict[str, Any]:
    """Runs a scheduled job (reminders, feedback, briefing, his-*...)."""
    if name not in JOB_NAMES:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"unknown job; known: {', '.join(JOB_NAMES)}"
        )
    body = JobRequest.model_validate(await request.json()) if await request.body() else JobRequest()
    options = {"rules": body.rules} if body.rules else {}
    return {
        "job": name,
        "caller": caller,
        "results": await JobRunner(services).run(name, body.hospital_ids, **options),
    }


@router.post("/feedback/{hospital_id}/{appointment_id}/request")
async def feedback_request(
    hospital_id: str, appointment_id: uuid.UUID, services: ServicesDep, caller: InternalDep
) -> dict[str, Any]:
    """Durable Functions activity: send the feedback template for one visit."""
    hospital = services.container.settings.hospitals.get(hospital_id)
    if hospital is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown hospital")
    return {"sent": await services.feedback.request_for_appointment(hospital, appointment_id)}


@router.get("/feedback/{hospital_id}/{appointment_id}/status")
async def feedback_status(
    hospital_id: str, appointment_id: uuid.UUID, services: ServicesDep, caller: InternalDep
) -> dict[str, str]:
    """Durable Functions activity: has the patient replied?"""
    hospital = services.container.settings.hospitals.get(hospital_id)
    if hospital is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown hospital")
    return {"status": await services.feedback.status_for_appointment(hospital, appointment_id)}


@router.post("/consent")
async def consent(
    event: ConsentEvent, services: ServicesDep, caller: InternalDep
) -> dict[str, str]:
    """Records consent captured in the HIS at registration."""
    hospital = services.container.settings.hospitals.get(event.hospital_id)
    if hospital is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown hospital")
    phone = normalize_phone(
        event.phone, services.container.settings.conversation.default_country_code
    )
    async with services.container.db.tenant_session(hospital.id) as session:
        conversation = await get_or_create_conversation(
            session, hospital.id, phone, language=hospital.default_language
        )
        patients = await patients_for_phone(session, hospital.id, phone)
        await record_consent(
            session,
            conversation,
            opt_in=event.opt_in,
            source=event.source,
            evidence=event.evidence,
            patients=patients,
        )
        return {"status": conversation.consent_status}
