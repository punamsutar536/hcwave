"""Development-only routes (enabled by ``server.dev_routes_enabled``).

``POST /dev/simulate`` injects a patient message and returns the bot's
replies – handy for demos and end-to-end tests without WhatsApp.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel

from hcwave.api.deps import ServicesDep

router = APIRouter(prefix="/dev", tags=["dev"])


class SimulatedMessage(BaseModel):
    """A fake inbound WhatsApp message."""

    from_phone: str = "+919812345678"
    text: str = ""
    reply_id: str | None = None
    channel_id: str = "console"


@router.post("/simulate")
async def simulate(
    message: SimulatedMessage, request: Request, services: ServicesDep
) -> dict[str, Any]:
    """Processes a message synchronously and returns what the bot sent."""
    provider = services.container.messaging
    sent_before = len(getattr(provider, "sent", []))
    payload = {
        "from": message.from_phone,
        "text": message.text,
        "reply_id": message.reply_id,
        "channel_id": message.channel_id,
    }
    await request.app.state.handlers.handle_channel_event(payload)
    sent = getattr(provider, "sent", [])[sent_before:]
    return {
        "replies": [
            {
                "kind": m.kind.value,
                "text": m.text,
                "choices": [{"id": c.id, "title": c.title} for c in m.choices],
                "template": m.template_name or None,
            }
            for _to, m in sent
        ]
    }
