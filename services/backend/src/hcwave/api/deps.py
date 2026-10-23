"""FastAPI dependencies: services, authentication and hospital scoping."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, status

from hcwave.api.auth import AuthenticationError
from hcwave.config.schema import HospitalConfig
from hcwave.domain.services import Services
from hcwave.domain.staff import StaffPrincipal


def get_services(request: Request) -> Services:
    """Returns the process-wide domain services."""
    return request.app.state.services


ServicesDep = Annotated[Services, Depends(get_services)]


async def current_staff(
    request: Request, authorization: Annotated[str | None, Header()] = None
) -> StaffPrincipal:
    """Authenticates the staff member making the request."""
    try:
        return await request.app.state.staff_auth.authenticate(authorization)
    except AuthenticationError as exc:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "invalid credentials", {"WWW-Authenticate": "Bearer"}
        ) from exc


StaffDep = Annotated[StaffPrincipal, Depends(current_staff)]


@dataclass(frozen=True)
class StaffScope:
    """The authenticated staff member and the hospital they are acting in."""

    principal: StaffPrincipal
    hospital: HospitalConfig


async def staff_scope(
    services: ServicesDep,
    principal: StaffDep,
    x_hospital_id: Annotated[str | None, Header()] = None,
) -> StaffScope:
    """Resolves the hospital for the request.

    Users pick a hospital with ``X-Hospital-Id`` (defaults to their only one).
    Admins with ``*`` in their hospital claim may act for any hospital.
    """
    allowed = principal.hospital_ids
    hospitals = services.container.settings.hospitals
    hospital_id = x_hospital_id or (next(iter(allowed)) if len(allowed) == 1 else None)
    if hospital_id is None or hospital_id not in hospitals:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "select a hospital with X-Hospital-Id")
    if hospital_id not in allowed and "*" not in allowed:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "no access to this hospital")
    return StaffScope(principal, hospitals[hospital_id])


ScopeDep = Annotated[StaffScope, Depends(staff_scope)]


def require_roles(*roles: str):  # noqa: ANN201 - FastAPI dependency factory
    """Dependency that requires any of ``roles`` (admin always passes)."""

    async def check(scope: ScopeDep) -> StaffScope:
        if not scope.principal.has_any(*roles):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "insufficient role")
        return scope

    return Depends(check)


async def internal_caller(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
    x_internal_token: Annotated[str | None, Header()] = None,
) -> str:
    """Authenticates Logic Apps / Functions / CronJob callers."""
    try:
        return await request.app.state.internal_auth.authenticate(authorization, x_internal_token)
    except AuthenticationError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid credentials") from exc


InternalDep = Annotated[str, Depends(internal_caller)]


def client_ip(request: Request) -> str | None:
    """Client IP as seen through the gateway (uvicorn applies X-Forwarded-For)."""
    return request.client.host if request.client else None
