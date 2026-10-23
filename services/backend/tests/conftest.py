"""Test fixtures.

Tests run against a real PostgreSQL (the schema uses RLS, JSONB and
``ON CONFLICT``). Point ``TEST_DATABASE_URL`` at a disposable database; it is
dropped and re-created by the migrations at the start of the session.
"""

from __future__ import annotations

import os
import tempfile
import uuid
from datetime import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
TEST_DB = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+asyncpg://postgres@127.0.0.1:5433/hcwave_test"
)
os.environ.update(
    {
        "APP_ENV": "test",
        "HCWAVE_CONFIG_DIR": str(REPO_ROOT / "config"),
        "HCWAVE_ENV_FILE": "/nonexistent/.env",
        "DATABASE_URL": TEST_DB,
        "APP_SECRET_KEY": "test-secret-key",
        "LOCAL_STORAGE_ROOT": tempfile.mkdtemp(prefix="hcwave-blobs-"),
        "HCWAVE_EMBEDDING_DIMENSIONS": "64",
    }
)

import asyncpg  # noqa: E402
import httpx  # noqa: E402
import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from sqlalchemy import text  # noqa: E402

from hcwave.api.main import create_apps  # noqa: E402
from hcwave.config import get_settings  # noqa: E402
from hcwave.core.container import Container  # noqa: E402
from hcwave.db.models import TENANT_TABLES, Department, Doctor, DoctorSchedule  # noqa: E402
from hcwave.domain.tenants import sync_hospitals  # noqa: E402

HOSPITAL = "demo-hospital"
PHONE = "+919812345678"


def _admin_dsn() -> str:
    return TEST_DB.replace("postgresql+asyncpg://", "postgresql://").rsplit("/", 1)[0] + "/postgres"


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def container():
    name = TEST_DB.rsplit("/", 1)[1]
    admin = await asyncpg.connect(_admin_dsn())
    await admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
    await admin.execute(f'CREATE DATABASE "{name}"')
    await admin.close()
    cfg = Config(str(REPO_ROOT / "services" / "backend" / "alembic.ini"))
    # Alembic's env.py uses asyncio.run, so run it outside the test loop.
    import asyncio

    await asyncio.to_thread(command.upgrade, cfg, "head")
    get_settings.cache_clear()
    built = Container(get_settings())
    await sync_hospitals(built.db, built.settings)
    yield built
    await built.aclose()


@pytest_asyncio.fixture(loop_scope="session")
async def clean(container):
    """Empties tenant tables and seeds one department, doctor and schedule."""
    tables = ", ".join(TENANT_TABLES)
    async with container.db.session() as session:
        await session.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
    container.messaging.sent.clear()
    container.email.sent.clear()
    container.sms.sent.clear()
    async with container.db.tenant_session(HOSPITAL) as session:
        department = Department(
            id=uuid.uuid4(),
            hospital_id=HOSPITAL,
            code="cardio",
            name="Cardiology",
            names={},
            active=True,
        )
        doctor = Doctor(
            id=uuid.uuid4(),
            hospital_id=HOSPITAL,
            department_id=department.id,
            external_id="D1",
            name="Dr. Anil Kumar",
            qualification="MD, DM Cardiology",
            languages=["en", "ml"],
            active=True,
        )
        session.add_all([department, doctor])
        await session.flush()
        for weekday in range(7):
            session.add(
                DoctorSchedule(
                    hospital_id=HOSPITAL,
                    doctor_id=doctor.id,
                    weekday=weekday,
                    start_time=time(0, 0),
                    end_time=time(23, 45),
                    slot_minutes=15,
                    capacity_per_slot=1,
                )
            )
    return {"department_id": department.id, "doctor_id": doctor.id}


@pytest_asyncio.fixture(loop_scope="session")
async def apps(container):
    public, internal = create_apps(container, lifespan_owner=False)
    return public, internal


@pytest_asyncio.fixture(loop_scope="session")
async def client(apps):
    transport = httpx.ASGITransport(app=apps[0])
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        yield http


@pytest_asyncio.fixture(loop_scope="session")
async def internal_client(apps):
    transport = httpx.ASGITransport(app=apps[1])
    async with httpx.AsyncClient(transport=transport, base_url="http://internal") as http:
        yield http


@pytest.fixture
def services(apps):
    return apps[0].state.services


async def say(
    client: httpx.AsyncClient, text: str = "", reply_id: str | None = None, phone: str = PHONE
) -> list[dict]:
    """Sends a simulated WhatsApp message and returns the bot replies."""
    response = await client.post(
        "/dev/simulate", json={"from_phone": phone, "text": text, "reply_id": reply_id}
    )
    assert response.status_code == 200, response.text
    return response.json()["replies"]
