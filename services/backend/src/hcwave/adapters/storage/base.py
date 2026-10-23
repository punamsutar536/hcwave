"""Object storage contract for report PDFs and HIS file drops.

Reports are never attached to chats. Patients reach them through
``temporary_url`` – a short-lived signed URL – only after verification.
"""

from __future__ import annotations

import abc

from hcwave.adapters.base import Adapter


class ObjectStorage(Adapter, abc.ABC):
    """Abstract object storage."""

    @abc.abstractmethod
    async def put(self, container: str, path: str, data: bytes, content_type: str) -> None:
        """Stores an object, overwriting any existing one."""

    @abc.abstractmethod
    async def get(self, container: str, path: str) -> bytes:
        """Reads an object.

        Raises:
            FileNotFoundError: If the object does not exist.
        """

    @abc.abstractmethod
    async def list(self, container: str, prefix: str = "") -> list[str]:
        """Lists object paths under ``prefix``."""

    @abc.abstractmethod
    async def delete(self, container: str, path: str) -> None:
        """Deletes an object if it exists."""

    async def temporary_url(
        self, container: str, path: str, ttl_minutes: int, download_name: str
    ) -> str | None:
        """Returns a short-lived signed read URL, or None to stream via the API."""
        return None
