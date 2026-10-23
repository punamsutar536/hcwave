"""Inbound webhooks.

The default Azure path needs no public webhook: ACS → Event Grid → Service
Bus → worker. These endpoints exist for providers that push over HTTP (Meta
Cloud API, other channels) and for Event Grid webhook delivery. Every request
is verified, then queued – business logic never runs on the request path, so
spikes and restarts lose nothing.
"""

from __future__ import annotations

import hmac
import json
import logging
import os
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, Request, Response, status

from hcwave.adapters.messaging.base import WebhookVerificationError
from hcwave.api.deps import ServicesDep

_log = logging.getLogger(__name__)
router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.get("/{provider}", include_in_schema=False)
async def challenge(provider: str, request: Request, services: ServicesDep) -> Response:
    """Answers subscription handshakes (e.g. Meta ``hub.challenge``)."""
    messaging = services.container.messaging
    if provider != messaging.name:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    answer = messaging.webhook_challenge(dict(request.query_params))
    if answer is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN)
    return Response(answer, media_type="text/plain")


@router.post("/eventgrid", status_code=200)
async def event_grid(
    request: Request,
    services: ServicesDep,
    key: Annotated[str, Query(description="Shared key configured on the subscription")] = "",
) -> Any:
    """Event Grid webhook delivery (alternative to Service Bus delivery)."""
    expected = os.environ.get("EVENTGRID_WEBHOOK_KEY", "")
    if not expected or not hmac.compare_digest(key, expected):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED)
    events = await request.json()
    events = events if isinstance(events, list) else [events]
    for event in events:
        if event.get("eventType") == "Microsoft.EventGrid.SubscriptionValidationEvent":
            return {"validationResponse": event["data"]["validationCode"]}
    queues = services.container.settings.queue.queues
    for event in events:
        await services.container.queue.publish(queues.inbound, event, message_id=event.get("id"))
    return {"queued": len(events)}


@router.post("/{provider}", status_code=200)
async def receive(provider: str, request: Request, services: ServicesDep) -> dict[str, str]:
    """Verifies a provider webhook and queues it for the worker."""
    messaging = services.container.messaging
    if provider != messaging.name:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    body = await request.body()
    try:
        messaging.verify_webhook({k.lower(): v for k, v in request.headers.items()}, body)
    except WebhookVerificationError as exc:
        _log.warning("webhook rejected: %s", exc)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED) from exc
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid JSON") from exc
    await services.container.queue.publish(
        services.container.settings.queue.queues.inbound, payload
    )
    return {"status": "queued"}
