import uuid
from datetime import timedelta

import asyncpg
from sqlalchemy import select

from hcwave.core.clock import utcnow
from hcwave.db.models import Conversation, ConversationStatus

from .conftest import HOSPITAL, PHONE, TEST_DB, say

HEADERS = {"X-Hospital-Id": HOSPITAL}


async def test_health(client):
    assert (await client.get("/healthz")).json() == {"status": "ok"}
    assert (await client.get("/readyz")).status_code == 200


async def test_security_headers(client):
    response = await client.get("/healthz")
    assert response.headers["x-frame-options"] == "DENY"
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]


async def test_takeover_reply_release(client, clean, container):
    await say(client, "I want to talk to a human")
    waiting = (await client.get("/staff/conversations", headers=HEADERS)).json()
    assert waiting and waiting[0]["status"] == "handover_pending"
    conversation_id = waiting[0]["id"]

    assert (
        await client.post(f"/staff/conversations/{conversation_id}/takeover", headers=HEADERS)
    ).json()["status"] == "human"
    sent = await client.post(
        f"/staff/conversations/{conversation_id}/reply",
        json={"text": "Hello, how can I help?"},
        headers=HEADERS,
    )
    assert sent.status_code == 200 and sent.json()["status"] == "sent"
    history = (
        await client.get(f"/staff/conversations/{conversation_id}/messages", headers=HEADERS)
    ).json()
    assert history[-1]["sender"] == "staff"
    assert (
        await client.post(f"/staff/conversations/{conversation_id}/release", headers=HEADERS)
    ).json()["status"] == "bot"


async def test_staff_reply_outside_window_is_rejected(client, clean, container):
    await say(client, "agent")
    async with container.db.tenant_session(HOSPITAL) as session:
        conversation = await session.scalar(select(Conversation))
        conversation.last_inbound_at = utcnow() - timedelta(hours=25)
        conversation_id = conversation.id
    response = await client.post(
        f"/staff/conversations/{conversation_id}/reply", json={"text": "late"}, headers=HEADERS
    )
    assert response.status_code == 409


async def test_tickets_dashboard_and_consent(client, clean, services, container):
    async with container.db.tenant_session(HOSPITAL) as session:
        await services.tickets.create(
            session, container.hospital(HOSPITAL), summary="Dirty washroom", category="cleanliness"
        )
    tickets = (await client.get("/staff/tickets", headers=HEADERS)).json()
    assert tickets[0]["category"] == "cleanliness"
    updated = await client.patch(
        f"/staff/tickets/{tickets[0]['id']}",
        json={"status": "resolved", "resolution_note": "Cleaned"},
        headers=HEADERS,
    )
    assert updated.json()["status"] == "resolved"

    summary = (await client.get("/staff/dashboard/summary?days=7", headers=HEADERS)).json()
    assert set(summary) == {"period", "access", "appointments", "reports", "experience"}
    assert (await client.get("/staff/dashboard/embed", headers=HEADERS)).json()["type"] == "builtin"

    consent = await client.post(
        "/staff/consent",
        json={"phone": "9847012345", "full_name": "New Patient", "note": "form"},
        headers=HEADERS,
    )
    assert consent.json()["status"] == "opted_in"


async def test_unknown_hospital_scope_rejected(client, clean):
    response = await client.get("/staff/conversations", headers={"X-Hospital-Id": "other"})
    assert response.status_code == 400


async def test_internal_api_requires_auth(internal_client, clean):
    assert (await internal_client.post("/internal/jobs/reminders")).status_code == 401
    response = await internal_client.post(
        "/internal/jobs/reminders",
        headers={"X-Internal-Token": "test-internal-token"},
        json={"rules": ["day_before"]},
    )
    assert response.status_code == 200 and response.json()["results"][HOSPITAL] == {"day_before": 0}
    assert (
        await internal_client.post(
            "/internal/jobs/nope", headers={"X-Internal-Token": "test-internal-token"}
        )
    ).status_code == 404


async def test_internal_routes_not_on_public_app(client):
    assert (
        await client.post(
            "/internal/jobs/reminders", headers={"X-Internal-Token": "test-internal-token"}
        )
    ).status_code == 404


async def test_row_level_security_isolates_hospitals(container, clean, client):
    """A non-superuser application role only sees the hospital set on the transaction."""
    await say(client, "hello")
    dsn = TEST_DB.replace("postgresql+asyncpg://", "postgresql://")
    admin = await asyncpg.connect(dsn)
    role = f"rls_{uuid.uuid4().hex[:8]}"
    await admin.execute(f"CREATE ROLE {role} LOGIN")
    await admin.execute(f"GRANT SELECT ON ALL TABLES IN SCHEMA public TO {role}")
    await admin.close()
    app_conn = await asyncpg.connect(dsn.replace("postgres@", f"{role}@"))
    try:
        async with app_conn.transaction():
            assert (
                await app_conn.fetchval("SELECT count(*) FROM conversations") == 0
            )  # no tenant set
            await app_conn.execute("SELECT set_config('app.hospital_id', 'other-hospital', true)")
            assert await app_conn.fetchval("SELECT count(*) FROM conversations") == 0
        async with app_conn.transaction():
            await app_conn.execute(f"SELECT set_config('app.hospital_id', '{HOSPITAL}', true)")
            assert await app_conn.fetchval("SELECT count(*) FROM conversations") == 1
    finally:
        await app_conn.close()
        admin = await asyncpg.connect(dsn)
        await admin.execute(f"REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {role}")
        await admin.execute(f"DROP ROLE {role}")
        await admin.close()


async def test_human_conversation_status_enum(container, clean, client):
    await say(client, "agent")
    async with container.db.tenant_session(HOSPITAL) as session:
        assert (
            await session.scalar(select(Conversation))
        ).status == ConversationStatus.HANDOVER_PENDING
        assert (await session.scalar(select(Conversation))).phone_e164 == PHONE
