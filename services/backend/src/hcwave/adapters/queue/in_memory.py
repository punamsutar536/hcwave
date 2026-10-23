"""In-process queue for tests and single-process local development."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections import defaultdict
from collections.abc import Mapping
from typing import Any

from hcwave.adapters.base import AdapterContext, AdapterSettings
from hcwave.adapters.queue.base import Handler, MessageQueue

_log = logging.getLogger(__name__)


class InMemorySettings(AdapterSettings):
    """Settings for the in-memory queue."""

    max_attempts: int = 3


class InMemoryQueue(MessageQueue):
    """``asyncio.Queue`` per queue name. Not durable – never use in production."""

    settings_model = InMemorySettings
    name = "in_memory"

    def __init__(self, raw_settings: Mapping[str, Any], ctx: AdapterContext) -> None:
        super().__init__(raw_settings, ctx)
        self.queues: dict[str, asyncio.Queue[tuple[int, dict[str, Any]]]] = defaultdict(
            asyncio.Queue
        )
        self.dead: list[dict[str, Any]] = []

    async def publish(
        self, queue: str, body: Mapping[str, Any], message_id: str | None = None
    ) -> None:
        """Enqueues a copy of the message."""
        await self.queues[queue].put((1, dict(body)))

    async def consume(self, queue: str, handler: Handler, stop: asyncio.Event) -> None:
        """Processes messages until ``stop`` is set."""
        while not stop.is_set():
            with contextlib.suppress(TimeoutError):
                attempt, body = await asyncio.wait_for(self.queues[queue].get(), timeout=0.5)
                try:
                    await handler(body)
                except Exception:
                    _log.exception("in-memory handler failed (attempt %s)", attempt)
                    if attempt >= self.config.max_attempts:
                        self.dead.append(body)
                    else:
                        await self.queues[queue].put((attempt + 1, body))

    async def drain(self, queue: str, handler: Handler) -> int:
        """Processes everything currently queued (test helper).

        Returns:
            Number of messages processed.
        """
        processed = 0
        while not self.queues[queue].empty():
            _attempt, body = self.queues[queue].get_nowait()
            await handler(body)
            processed += 1
        return processed
