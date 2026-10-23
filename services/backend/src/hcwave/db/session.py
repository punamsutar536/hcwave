"""Database engine and tenant-scoped sessions.

``Database.tenant_session(hospital_id)`` opens a transaction and sets
``app.hospital_id`` for it, which the row-level security policies use to hide
every other hospital's rows. All business code goes through it.

With ``database.auth_mode: azure_ad`` the password for each new connection is
a fresh Microsoft Entra token for the pod's workload identity, so there is no
database password to store or rotate.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from hcwave.config.schema import DatabaseSection
from hcwave.core.identity import CredentialFactory

_log = logging.getLogger(__name__)


class Database:
    """Owns the async engine and hands out sessions.

    Args:
        section: The ``database`` configuration section.
        credentials: Credential factory used for ``azure_ad`` auth.
    """

    def __init__(self, section: DatabaseSection, credentials: CredentialFactory) -> None:
        self._section = section
        connect_args: dict[str, Any] = {}
        if section.ssl_mode != "disable":
            connect_args["ssl"] = section.ssl_mode
        self.engine: AsyncEngine = create_async_engine(
            section.url,
            echo=section.echo,
            pool_size=section.pool_size,
            max_overflow=section.max_overflow,
            pool_recycle=section.pool_recycle_seconds,
            pool_pre_ping=True,
            connect_args=connect_args,
        )
        if section.auth_mode == "azure_ad":
            self._install_token_auth(credentials)
        self._sessionmaker = async_sessionmaker(self.engine, expire_on_commit=False)

    def _install_token_auth(self, credentials: CredentialFactory) -> None:
        """Injects an Entra access token as the password on every new connection."""
        scope = self._section.azure_ad_scope

        @event.listens_for(self.engine.sync_engine, "do_connect")
        def _provide_token(
            dialect: Any, conn_rec: Any, cargs: Any, cparams: dict[str, Any]
        ) -> None:
            # azure-identity caches tokens and refreshes them before expiry.
            cparams["password"] = credentials.sync.get_token(scope).token

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        """Opens a transaction that is *not* tenant scoped.

        Only for platform-level tables such as ``hospitals``.
        """
        async with self._sessionmaker() as session, session.begin():
            yield session

    @asynccontextmanager
    async def tenant_session(self, hospital_id: str) -> AsyncIterator[AsyncSession]:
        """Opens a transaction scoped to one hospital.

        Args:
            hospital_id: Tenant whose rows the transaction may see.

        Yields:
            An ``AsyncSession`` inside a transaction that commits on success
            and rolls back on error.
        """
        async with self._sessionmaker() as session, session.begin():
            await session.execute(
                text("SELECT set_config('app.hospital_id', :hospital_id, true)"),
                {"hospital_id": hospital_id},
            )
            yield session

    async def ping(self) -> bool:
        """Returns True if the database answers a trivial query."""
        try:
            async with self.engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            return True
        except Exception:  # noqa: BLE001 - readiness probes must not raise
            _log.exception("database ping failed")
            return False

    async def dispose(self) -> None:
        """Closes all pooled connections."""
        await self.engine.dispose()
