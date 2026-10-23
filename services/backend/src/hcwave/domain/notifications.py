"""Idempotency guard for proactive notifications."""

from __future__ import annotations

import uuid

from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from hcwave.db.models import NotificationLog


async def claim_notification(
    session: AsyncSession, hospital_id: str, kind: str, entity_id: uuid.UUID | str
) -> bool:
    """Atomically claims the right to send ``kind`` for ``entity_id`` once.

    Args:
        session: Tenant-scoped session.
        hospital_id: Tenant.
        kind: Notification kind, e.g. ``reminder:day_before``.
        entity_id: The appointment/report/feedback the notification is about.

    Returns:
        True if this caller claimed it; False if it was already sent.
    """
    statement = (
        insert(NotificationLog)
        .values(hospital_id=hospital_id, kind=kind, entity_id=str(entity_id))
        .on_conflict_do_nothing(index_elements=["hospital_id", "kind", "entity_id"])
        .returning(NotificationLog.id)
    )
    return (await session.execute(statement)).scalar_one_or_none() is not None


async def release_notification(
    session: AsyncSession, hospital_id: str, kind: str, entity_id: uuid.UUID | str
) -> None:
    """Releases a claim so a failed send can be retried by the next job run."""
    await session.execute(
        delete(NotificationLog).where(
            NotificationLog.hospital_id == hospital_id,
            NotificationLog.kind == kind,
            NotificationLog.entity_id == str(entity_id),
        )
    )
