"""FastAPI application factories.

Two ASGI apps share one process and one container:

* **public** (port 8000, behind Application Gateway for Containers / Front
  Door WAF): webhooks, the report portal, the staff API.
* **internal** (port 8001, private Service only): job triggers for Logic
  Apps, Durable Functions and CronJobs.

Keeping job endpoints on a separate listener means the public gateway can
never route to them, even if a route is misconfigured.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from hcwave import __version__
from hcwave.agent.runner import Assistant
from hcwave.api.auth import InternalAuthenticator, StaffAuthenticator
from hcwave.api.routes import dev, health, internal, reports_portal, staff, webhooks
from hcwave.core.container import Container
from hcwave.core.telemetry import instrument_fastapi
from hcwave.domain.services import Services
from hcwave.worker.handlers import EventHandlers

_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Content-Security-Policy": "default-src 'self'; frame-ancestors 'none'; form-action 'self'; base-uri 'none'",
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
}


def _attach_state(app: FastAPI, services: Services, handlers: EventHandlers) -> None:
    settings = services.container.settings
    app.state.services = services
    app.state.handlers = handlers
    app.state.staff_auth = StaffAuthenticator(settings.auth)
    app.state.internal_auth = InternalAuthenticator(settings.internal_auth)


def _security_headers(app: FastAPI) -> None:
    @app.middleware("http")
    async def add_headers(request: Request, call_next) -> Response:  # noqa: ANN001
        response = await call_next(request)
        for name, value in _SECURITY_HEADERS.items():
            response.headers.setdefault(name, value)
        return response


def create_apps(container: Container, *, lifespan_owner: bool = True) -> tuple[FastAPI, FastAPI]:
    """Builds the public and internal apps around one container.

    Args:
        container: The process container.
        lifespan_owner: Close the container when the public app shuts down.

    Returns:
        ``(public_app, internal_app)``.
    """
    settings = container.settings
    services = Services.build(container)
    handlers = EventHandlers(services, Assistant(services))

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        yield
        if lifespan_owner:
            await container.aclose()

    docs = settings.server.docs_enabled
    public = FastAPI(
        title="hcwave public API",
        version=__version__,
        lifespan=lifespan,
        docs_url="/docs" if docs else None,
        redoc_url=None,
        openapi_url="/openapi.json" if docs else None,
    )
    _attach_state(public, services, handlers)
    _security_headers(public)
    if settings.server.cors_origins:
        public.add_middleware(
            CORSMiddleware,
            allow_origins=settings.server.cors_origins,
            allow_methods=["GET", "POST", "PATCH"],
            allow_headers=["Authorization", "Content-Type", "X-Hospital-Id"],
        )
    public.include_router(health.router)
    public.include_router(webhooks.router)
    public.include_router(reports_portal.router)
    public.include_router(staff.router)
    if settings.server.dev_routes_enabled:
        public.include_router(dev.router)
    public.mount(
        "/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static"
    )
    instrument_fastapi(public)

    internal_app = FastAPI(
        title="hcwave internal API",
        version=__version__,
        docs_url="/docs" if docs else None,
        redoc_url=None,
        openapi_url="/openapi.json" if docs else None,
    )
    _attach_state(internal_app, services, handlers)
    internal_app.include_router(health.router)
    internal_app.include_router(internal.router)
    instrument_fastapi(internal_app)
    return public, internal_app
