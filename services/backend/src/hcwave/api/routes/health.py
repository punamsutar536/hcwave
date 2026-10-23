"""Liveness and readiness probes."""

from __future__ import annotations

from fastapi import APIRouter, Response

from hcwave.api.deps import ServicesDep

router = APIRouter(tags=["health"])


@router.get("/healthz", include_in_schema=False)
async def healthz() -> dict[str, str]:
    """Liveness: the process is up."""
    return {"status": "ok"}


@router.get("/readyz", include_in_schema=False)
async def readyz(services: ServicesDep, response: Response) -> dict[str, str]:
    """Readiness: the database is reachable."""
    if await services.container.db.ping():
        return {"status": "ready"}
    response.status_code = 503
    return {"status": "database unavailable"}
