"""Local filesystem storage for development. Files are streamed by the API."""

from __future__ import annotations

import asyncio
from pathlib import Path

from hcwave.adapters.base import AdapterSettings
from hcwave.adapters.storage.base import ObjectStorage


class LocalSettings(AdapterSettings):
    """Settings for local storage."""

    root: str = ".data/blobs"


class LocalStorage(ObjectStorage):
    """Stores objects under ``root/<container>/<path>``."""

    settings_model = LocalSettings
    name = "local"

    def _path(self, container: str, path: str) -> Path:
        root = Path(self.config.root).resolve()
        target = (root / container / path).resolve()
        if root not in target.parents:
            raise ValueError("path escapes storage root")
        return target

    async def put(self, container: str, path: str, data: bytes, content_type: str) -> None:
        """Writes the file."""
        target = self._path(container, path)
        target.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(target.write_bytes, data)

    async def get(self, container: str, path: str) -> bytes:
        """Reads the file."""
        target = self._path(container, path)
        if not target.is_file():
            raise FileNotFoundError(f"{container}/{path}")
        return await asyncio.to_thread(target.read_bytes)

    async def list(self, container: str, prefix: str = "") -> list[str]:
        """Lists files under the prefix."""
        base = self._path(container, ".")
        if not base.is_dir():
            return []
        return sorted(
            str(p.relative_to(base))
            for p in base.rglob("*")
            if p.is_file() and str(p.relative_to(base)).startswith(prefix)
        )

    async def delete(self, container: str, path: str) -> None:
        """Deletes the file if present."""
        self._path(container, path).unlink(missing_ok=True)
