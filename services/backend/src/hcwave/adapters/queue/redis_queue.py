"""Redis Streams queue adapter – the portable option for any cloud.

Works with Azure Cache for Redis, Amazon ElastiCache, Google Memorystore or a
plain Redis container. Uses consumer groups; failed messages are re-queued
with an attempt counter and moved to ``<queue>:dead`` after ``max_attempts``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import socket
from collections.abc import Mapping
from typing import Any

from hcwave.adapters.base import AdapterContext, AdapterSettings
from hcwave.adapters.queue.base import Handler, MessageQueue

_log = logging.getLogger(__name__)


class RedisSettings(AdapterSettings):
    """Settings for the Redis queue."""

    url: str = "redis://localhost:6379/0"
    group: str = "hcwave-workers"
    block_ms: int = 5000
    max_attempts: int = 5


class RedisQueue(MessageQueue):
    """Message queue backed by Redis Streams."""

    settings_model = RedisSettings
    name = "redis"

    def __init__(self, raw_settings: Mapping[str, Any], ctx: AdapterContext) -> None:
        super().__init__(raw_settings, ctx)
        import redis.asyncio as redis

        self._redis = redis.from_url(self.config.url, decode_responses=True)
        self._consumer = socket.gethostname()

    async def publish(
        self, queue: str, body: Mapping[str, Any], message_id: str | None = None
    ) -> None:
        """Appends the message to the stream."""
        await self._redis.xadd(queue, {"body": json.dumps(body, default=str), "attempt": "1"})

    async def consume(self, queue: str, handler: Handler, stop: asyncio.Event) -> None:
        """Reads with a consumer group until ``stop`` is set."""
        try:
            await self._redis.xgroup_create(queue, self.config.group, id="0", mkstream=True)
        except Exception as exc:  # noqa: BLE001 - group already exists
            if "BUSYGROUP" not in str(exc):
                raise
        while not stop.is_set():
            response = await self._redis.xreadgroup(
                self.config.group,
                self._consumer,
                {queue: ">"},
                count=16,
                block=self.config.block_ms,
            )
            for _stream, entries in response or []:
                for entry_id, fields in entries:
                    await self._process(queue, entry_id, fields, handler)

    async def _process(
        self, queue: str, entry_id: str, fields: dict[str, str], handler: Handler
    ) -> None:
        attempt = int(fields.get("attempt", "1"))
        try:
            await handler(json.loads(fields["body"]))
        except Exception:
            _log.exception("handler failed (attempt %s) for %s", attempt, entry_id)
            target = f"{queue}:dead" if attempt >= self.config.max_attempts else queue
            await self._redis.xadd(target, {"body": fields["body"], "attempt": str(attempt + 1)})
        await self._redis.xack(queue, self.config.group, entry_id)

    async def aclose(self) -> None:
        """Closes the Redis connection pool."""
        await self._redis.aclose()
