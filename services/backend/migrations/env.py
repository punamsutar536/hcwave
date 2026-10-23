"""Alembic environment.

Reuses hcwave's ``Database`` so migrations authenticate exactly like the app
(password or Microsoft Entra token). Run as the schema owner:

    APP_ENV=prod alembic upgrade head
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy.engine import Connection

from hcwave.config import get_settings
from hcwave.core.identity import CredentialFactory
from hcwave.db.models import Base
from hcwave.db.session import Database

if context.config.config_file_name is not None:
    fileConfig(context.config.config_file_name)

target_metadata = Base.metadata


def _run(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


async def _run_async() -> None:
    settings = get_settings()
    database = Database(settings.database, CredentialFactory(settings.identity))
    async with database.engine.connect() as connection:
        await connection.run_sync(_run)
    await database.dispose()


if context.is_offline_mode():
    context.configure(
        url=get_settings().database.url, target_metadata=target_metadata, literal_binds=True
    )
    with context.begin_transaction():
        context.run_migrations()
else:
    asyncio.run(_run_async())
