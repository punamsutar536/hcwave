"""Durable queue contract between ingestion (webhooks, Event Grid) and the worker.

Messages are JSON objects. ``consume`` delivers each message to a handler;
success completes it, an exception returns it to the queue for retry, and the
broker dead-letters it after its maximum delivery count – so nothing is lost
during traffic spikes or pod restarts.
"""

from __future__ import annotations

import abc
import asyncio
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from hcwave.adapters.base import Adapter

Handler = Callable[[dict[str, Any]], Awaitable[None]]


class MessageQueue(Adapter, abc.ABC):
    """Abstract message queue."""

    @abc.abstractmethod
    async def publish(
        self, queue: str, body: Mapping[str, Any], message_id: str | None = None
    ) -> None:
        """Publishes one JSON message.

        Args:
            queue: Physical queue name.
            body: JSON-serialisable payload.
            message_id: Optional ID used for broker-side duplicate detection.
        """

    @abc.abstractmethod
    async def consume(self, queue: str, handler: Handler, stop: asyncio.Event) -> None:
        """Delivers messages to ``handler`` until ``stop`` is set.

        Args:
            queue: Physical queue name.
            handler: Coroutine called once per message.
            stop: Event that ends the loop (set on SIGTERM).
        """
