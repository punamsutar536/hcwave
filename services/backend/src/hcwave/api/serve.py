"""Process entry point: runs the public and internal listeners together.

With the ``in_memory`` queue (local development) the worker consumers run in
the same process, so one command gives a fully working stack.
"""

from __future__ import annotations

import asyncio
import logging
import signal

import uvicorn

from hcwave.config import get_settings
from hcwave.core.container import Container
from hcwave.core.logging import configure_logging
from hcwave.core.telemetry import configure_telemetry
from hcwave.domain.tenants import sync_hospitals

_log = logging.getLogger(__name__)


async def amain() -> None:
    """Starts both uvicorn servers (and the embedded worker if applicable)."""
    settings = get_settings()
    configure_logging(settings.app.log_level, settings.app.log_format)
    configure_telemetry(settings.telemetry)
    container = Container(settings)
    await sync_hospitals(container.db, settings)

    from hcwave.api.main import create_apps

    public, internal = create_apps(container)
    common = {
        "host": settings.server.host,
        "log_level": "warning",
        "proxy_headers": True,
        "forwarded_allow_ips": settings.server.forwarded_allow_ips,
        "server_header": False,
    }
    servers = [
        uvicorn.Server(uvicorn.Config(public, port=settings.server.public_port, **common)),
        uvicorn.Server(uvicorn.Config(internal, port=settings.server.internal_port, **common)),
    ]
    tasks = [asyncio.create_task(server.serve()) for server in servers]

    stop = asyncio.Event()
    if settings.queue.provider == "in_memory":
        from hcwave.worker.main import Heartbeat, run_consumers

        handlers = public.state.handlers
        tasks.append(
            asyncio.create_task(run_consumers(public.state.services, handlers, stop, Heartbeat()))
        )
        _log.info("embedded worker started (in-memory queue)")

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(
            sig, lambda: (stop.set(), [setattr(s, "should_exit", True) for s in servers])
        )
    _log.info(
        "api listening on :%s (public) and :%s (internal)",
        settings.server.public_port,
        settings.server.internal_port,
    )
    await asyncio.gather(*tasks)


def main() -> None:
    """Console entry point (``hcwave-api``)."""
    asyncio.run(amain())


if __name__ == "__main__":
    main()
