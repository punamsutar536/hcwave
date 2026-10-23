"""Azure Service Bus queue adapter.

Authenticates with the workload identity (``Azure Service Bus Data Sender`` /
``Data Receiver`` roles) – local SAS auth is disabled on the namespace.
Event Grid delivers ACS events straight into these queues.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Mapping
from typing import Any

from hcwave.adapters.base import AdapterContext, AdapterSettings
from hcwave.adapters.queue.base import Handler, MessageQueue

_log = logging.getLogger(__name__)


class ServiceBusSettings(AdapterSettings):
    """Settings for Service Bus.

    Attributes:
        fully_qualified_namespace: ``<name>.servicebus.windows.net``.
        connection_string: Optional; leave empty for Entra ID (recommended).
        max_batch: Messages fetched per receive call.
        max_wait_seconds: Long-poll duration.
        max_concurrency: Messages processed in parallel per queue.
    """

    fully_qualified_namespace: str = ""
    connection_string: str = ""
    max_batch: int = 16
    max_wait_seconds: float = 5.0
    max_concurrency: int = 8


class ServiceBusQueue(MessageQueue):
    """Message queue backed by Azure Service Bus."""

    settings_model = ServiceBusSettings
    name = "azure_service_bus"

    def __init__(self, raw_settings: Mapping[str, Any], ctx: AdapterContext) -> None:
        super().__init__(raw_settings, ctx)
        self._client: Any = None

    def _get_client(self) -> Any:
        if self._client is None:
            from azure.servicebus.aio import ServiceBusClient

            if self.config.connection_string:
                self._client = ServiceBusClient.from_connection_string(
                    self.config.connection_string
                )
            else:
                self._client = ServiceBusClient(
                    self.config.fully_qualified_namespace, self.ctx.credentials.aio
                )
        return self._client

    async def publish(
        self, queue: str, body: Mapping[str, Any], message_id: str | None = None
    ) -> None:
        """Sends one message; ``message_id`` enables duplicate detection."""
        from azure.servicebus import ServiceBusMessage

        message = ServiceBusMessage(
            json.dumps(body, default=str),
            content_type="application/json",
            message_id=message_id,
        )
        async with self._get_client().get_queue_sender(queue) as sender:
            await sender.send_messages(message)

    async def consume(self, queue: str, handler: Handler, stop: asyncio.Event) -> None:
        """Receives in batches and processes with bounded concurrency."""
        semaphore = asyncio.Semaphore(self.config.max_concurrency)
        async with self._get_client().get_queue_receiver(queue) as receiver:
            while not stop.is_set():
                batch = await receiver.receive_messages(
                    max_message_count=self.config.max_batch,
                    max_wait_time=self.config.max_wait_seconds,
                )
                await asyncio.gather(
                    *(self._process(receiver, m, handler, semaphore) for m in batch)
                )

    @staticmethod
    async def _process(
        receiver: Any, message: Any, handler: Handler, semaphore: asyncio.Semaphore
    ) -> None:
        async with semaphore:
            try:
                body = json.loads(b"".join(message.body))
                await handler(body)
            except json.JSONDecodeError:
                _log.error("dead-lettering malformed message %s", message.message_id)
                await receiver.dead_letter_message(message, reason="malformed-json")
            except Exception:
                _log.exception("handler failed; message %s will be retried", message.message_id)
                await receiver.abandon_message(message)
            else:
                await receiver.complete_message(message)

    async def aclose(self) -> None:
        """Closes the Service Bus client."""
        if self._client is not None:
            await self._client.close()
