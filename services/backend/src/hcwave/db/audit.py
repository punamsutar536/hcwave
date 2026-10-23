"""Audit trail helper used by every module that touches patient data."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from hcwave.db.models import AuditLog


async def record_audit(
    session: AsyncSession,
    hospital_id: str,
    action: str,
    *,
    actor_type: str = "system",
    actor_id: str | None = None,
    entity_type: str | None = None,
    entity_id: Any = None,
    **details: Any,
) -> None:
    """Appends an audit log row inside the caller's transaction.

    Args:
        session: Tenant-scoped session.
        hospital_id: Tenant.
        action: Verb, e.g. ``conversation.takeover``.
        actor_type: ``staff``, ``system`` or ``patient``.
        actor_id: Staff ID or other actor identifier.
        entity_type: Affected entity type.
        entity_id: Affected entity ID.
        **details: Extra JSON-serialisable context (no PHI beyond IDs).
    """
    session.add(
        AuditLog(
            hospital_id=hospital_id,
            actor_type=actor_type,
            actor_id=actor_id,
            action=action,
            entity_type=entity_type,
            entity_id=str(entity_id) if entity_id is not None else None,
            details={
                k: (str(v) if not isinstance(v, (int, float, bool)) else v)
                for k, v in details.items()
            },
        )
    )
