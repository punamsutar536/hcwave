"""Keeps the ``hospitals`` table in sync with ``config/hospitals/*.yaml``."""

from __future__ import annotations

from sqlalchemy.dialects.postgresql import insert

from hcwave.config.schema import Settings
from hcwave.db.models import Hospital
from hcwave.db.session import Database


async def sync_hospitals(db: Database, settings: Settings) -> int:
    """Upserts every configured hospital. Returns the number synced."""
    async with db.session() as session:
        for hospital in settings.hospitals.values():
            statement = insert(Hospital).values(
                id=hospital.id,
                name=hospital.name,
                timezone=hospital.timezone,
                active=hospital.active,
            )
            await session.execute(
                statement.on_conflict_do_update(
                    index_elements=["id"],
                    set_={
                        "name": hospital.name,
                        "timezone": hospital.timezone,
                        "active": hospital.active,
                    },
                )
            )
    return len(settings.hospitals)
