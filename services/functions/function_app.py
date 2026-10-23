"""Azure Durable Functions: multi-step waits that are awkward in Logic Apps.

Feedback orchestration (one instance per visit):

    visit completed ──▶ wait N hours (OPD 3 h / discharge 24 h)
                   ──▶ send feedback template (backend activity)
                   ──▶ wait for the reply timeout
                   ──▶ no reply? close the request and let service recovery
                       pick up detractor scores (backend job)

The orchestrator holds no business logic: every activity calls the backend's
internal API over the VNet with the Function App's managed identity, so the
rules live in one place (Python domain services) and stay portable.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta

import azure.durable_functions as df
import azure.functions as func
import httpx
from azure.identity.aio import ManagedIdentityCredential

# The Function App is protected by App Service Authentication (Entra ID), so
# HTTP triggers use anonymous level and rely on the platform to reject callers.
app = df.DFApp(http_auth_level=func.AuthLevel.ANONYMOUS)

_TERMINAL = {
    df.OrchestrationRuntimeStatus.Completed,
    df.OrchestrationRuntimeStatus.Failed,
    df.OrchestrationRuntimeStatus.Terminated,
}


def _setting(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


async def _backend(method: str, path: str, body: dict | None = None) -> dict:
    """Calls the backend internal API with a managed-identity token."""
    credential = ManagedIdentityCredential(client_id=_setting("AZURE_CLIENT_ID") or None)
    try:
        token = await credential.get_token(f"{_setting('HCWAVE_INTERNAL_AUDIENCE')}/.default")
    finally:
        await credential.close()
    async with httpx.AsyncClient(base_url=_setting("HCWAVE_INTERNAL_URL"), timeout=60) as client:
        response = await client.request(
            method, path, json=body, headers={"Authorization": f"Bearer {token.token}"}
        )
        response.raise_for_status()
        return response.json()


# --------------------------------------------------------------------------- #
# HTTP starter (called by the backend when a visit is completed)
# --------------------------------------------------------------------------- #
@app.route(route="feedback/start", methods=["POST"])
@app.durable_client_input(client_name="client")
async def start_feedback(
    req: func.HttpRequest, client: df.DurableOrchestrationClient
) -> func.HttpResponse:
    """Starts one feedback orchestration per visit (idempotent by instance ID)."""
    body = req.get_json()
    instance_id = f"feedback-{body['hospital_id']}-{body['appointment_id']}"
    existing = await client.get_status(instance_id)
    if existing and existing.runtime_status and existing.runtime_status not in _TERMINAL:
        return func.HttpResponse(status_code=202, body=instance_id)
    body["delays"] = {
        "opd_hours": float(_setting("FEEDBACK_OPD_DELAY_HOURS", "3")),
        "discharge_hours": float(_setting("FEEDBACK_DISCHARGE_DELAY_HOURS", "24")),
        "reply_timeout_hours": float(_setting("FEEDBACK_REPLY_TIMEOUT_HOURS", "24")),
    }
    await client.start_new("feedback_orchestrator", instance_id, body)
    logging.info("started feedback orchestration %s", instance_id)
    return client.create_check_status_response(req, instance_id)


# --------------------------------------------------------------------------- #
# Orchestrator (must be deterministic: no I/O, no wall-clock reads)
# --------------------------------------------------------------------------- #
@app.orchestration_trigger(context_name="context")
def feedback_orchestrator(context: df.DurableOrchestrationContext):  # noqa: ANN201 - generator
    """Waits, sends the feedback request, waits for a reply, then closes."""
    data = context.get_input()
    delays = data["delays"]
    delay = (
        delays["discharge_hours"] if data.get("visit_type") == "discharge" else delays["opd_hours"]
    )
    checked_out = datetime.fromisoformat(data["checked_out_at"])
    fire_at = max(checked_out + timedelta(hours=delay), context.current_utc_datetime)
    yield context.create_timer(fire_at)

    retry = df.RetryOptions(first_retry_interval_in_milliseconds=60_000, max_number_of_attempts=5)
    sent = yield context.call_activity_with_retry("send_feedback_request", retry, data)
    if not sent:
        return {"status": "not_sent"}

    yield context.create_timer(
        context.current_utc_datetime + timedelta(hours=delays["reply_timeout_hours"])
    )
    status = yield context.call_activity_with_retry("get_feedback_status", retry, data)
    if status in ("requested", "scored"):
        # No (complete) reply: the backend job expires it and opens a ticket
        # for a detractor score left without a comment.
        yield context.call_activity_with_retry("close_stale_feedback", retry, data)
        return {"status": "no_reply"}
    return {"status": status}


# --------------------------------------------------------------------------- #
# Activities (thin HTTP calls to the backend internal API)
# --------------------------------------------------------------------------- #
@app.activity_trigger(input_name="data")
async def send_feedback_request(data: dict) -> bool:
    """Asks the backend to send the feedback template for the visit."""
    result = await _backend(
        "POST", f"/internal/feedback/{data['hospital_id']}/{data['appointment_id']}/request"
    )
    return bool(result.get("sent"))


@app.activity_trigger(input_name="data")
async def get_feedback_status(data: dict) -> str:
    """Returns the feedback status for the visit."""
    result = await _backend(
        "GET", f"/internal/feedback/{data['hospital_id']}/{data['appointment_id']}/status"
    )
    return str(result.get("status"))


@app.activity_trigger(input_name="data")
async def close_stale_feedback(data: dict) -> dict:
    """Runs the backend feedback job for the hospital (expires stale requests)."""
    return await _backend(
        "POST", "/internal/jobs/feedback", {"hospital_ids": [data["hospital_id"]]}
    )
