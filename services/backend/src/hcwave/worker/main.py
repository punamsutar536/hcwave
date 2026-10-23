"""Queue worker process.

Consumes the inbound, delivery and report queues concurrently and exposes
``/healthz`` on port 8080 for Kubernetes probes. Scales horizontally (KEDA on
Service Bus queue length); per-conversation row locks keep each patient's
messages in order.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import signal
import time

import uvicorn
from fastapi import FastAPI, Response

from hcwave.agent.runner import Assistant
from hcwave.config import get_settings
from hcwave.core.container import Container
from hcwave.core.logging import configure_logging
from hcwave.core.telemetry import configure_telemetry
from hcwave.domain.services import Services
from hcwave.domain.tenants import sync_hospitals
from hcwave.worker.handlers import EventHandlers

_log = logging.getLogger(__name__)
_HEARTBEAT_TIMEOUT_SECONDS = 120


class Heartbeat:
    """Tracks consumer liveness for the health probe."""

    def __init__(self) -> None:
        self.last = time.monotonic()

    def beat(self) -> None:
        """Records activity."""
        self.last = time.monotonic()

    @property
    def healthy(self) -> bool:
        """True if a consumer loop ran recently."""
        return time.monotonic() - self.last < _HEARTBEAT_TIMEOUT_SECONDS


async def run_consumers(
    services: Services, handlers: EventHandlers, stop: asyncio.Event, heartbeat: Heartbeat
) -> None:
    """Runs one consumer loop per queue until ``stop`` is set."""
    container = services.container
    queues = container.settings.queue.queues

    def wrap(handler):  # noqa: ANN001, ANN202 - small local adapter
        async def wrapped(payload: dict) -> None:
            heartbeat.beat()
            await handler(payload)

        return wrapped

    async def keep_alive() -> None:
        while not stop.is_set():
            heartbeat.beat()
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=30)

    async def supervised(queue: str, handler) -> None:  # noqa: ANN001
        # Restart a crashed consumer loop with back-off instead of dying.
        delay = 1.0
        while not stop.is_set():
            try:
                await container.queue.consume(queue, wrap(handler), stop)
            except Exception:
                _log.exception("consumer for %s crashed; restarting in %.0fs", queue, delay)
                await asyncio.sleep(delay)
                delay = min(delay * 2, 60)

    await asyncio.gather(
        keep_alive(),
        supervised(queues.inbound, handlers.handle_channel_event),
        supervised(queues.delivery, handlers.handle_channel_event),
        supervised(queues.reports, handlers.handle_report_event),
    )


def health_app(heartbeat: Heartbeat) -> FastAPI:
    """Tiny app for liveness/readiness probes."""
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @app.get("/healthz")
    async def healthz() -> Response:
        return Response(status_code=200 if heartbeat.healthy else 503)

    return app


async def amain() -> None:
    """Async entry point."""
    settings = get_settings()
    configure_logging(settings.app.log_level, settings.app.log_format)
    configure_telemetry(settings.telemetry)
    container = Container(settings)
    await sync_hospitals(container.db, settings)
    services = Services.build(container)
    handlers = EventHandlers(services, Assistant(services))

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)

    heartbeat = Heartbeat()
    # Probe listener inside the pod network; NetworkPolicy limits who reaches it.
    probe = uvicorn.Config(health_app(heartbeat), host="0.0.0.0", port=8080, log_level="warning")  # noqa: S104
    server = uvicorn.Server(probe)
    server_task = asyncio.create_task(server.serve())
    _log.info("worker started")
    try:
        await run_consumers(services, handlers, stop, heartbeat)
    finally:
        server.should_exit = True
        await server_task
        await container.aclose()
        _log.info("worker stopped")


def main() -> None:
    """Console entry point (``hcwave-worker``)."""
    asyncio.run(amain())


if __name__ == "__main__":
    main()
