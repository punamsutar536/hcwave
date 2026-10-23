"""Bearer-token authentication.

* Staff: Microsoft Entra ID (or any OIDC issuer) access tokens. App roles in
  the token map to platform roles; a hospital claim scopes the user to their
  hospital(s).
* Internal jobs: Entra tokens issued to the managed identities of Logic Apps
  and Azure Functions (restricted to an allow-list of client IDs), or a shared
  secret on clouds without Entra ID.
"""

from __future__ import annotations

import asyncio
import functools
import logging
from typing import Any

import jwt
from jwt import PyJWKClient

from hcwave.config.schema import AuthSection, InternalAuthSection
from hcwave.core.security import constant_time_equals
from hcwave.domain.staff import StaffPrincipal

_log = logging.getLogger(__name__)


class AuthenticationError(Exception):
    """The request carries no valid credentials."""


@functools.lru_cache(maxsize=8)
def _jwks_client(url: str) -> PyJWKClient:
    # Keys are cached in-process and refreshed on unknown key IDs.
    return PyJWKClient(url, cache_keys=True, lifespan=3600)


def _entra_issuers(tenant_id: str) -> list[str]:
    # v2.0 tokens (apps) and v1.0 tokens (managed identities by default).
    return [
        f"https://login.microsoftonline.com/{tenant_id}/v2.0",
        f"https://sts.windows.net/{tenant_id}/",
    ]


def _entra_jwks(tenant_id: str) -> str:
    return f"https://login.microsoftonline.com/{tenant_id}/discovery/v2.0/keys"


async def _decode(token: str, jwks_url: str, audience: str, issuers: list[str]) -> dict[str, Any]:
    """Validates signature, expiry, audience and issuer; returns the claims."""
    try:
        key = await asyncio.to_thread(
            lambda: _jwks_client(jwks_url).get_signing_key_from_jwt(token).key
        )
        audiences = [audience] + (
            [audience.removeprefix("api://")] if audience.startswith("api://") else []
        )
        return jwt.decode(
            token,
            key,
            algorithms=["RS256"],
            audience=audiences,
            issuer=issuers,
            options={"require": ["exp", "iat", "aud", "iss"]},
        )
    except jwt.PyJWTError as exc:
        raise AuthenticationError(str(exc)) from exc


class StaffAuthenticator:
    """Validates staff tokens and builds a :class:`StaffPrincipal`.

    Args:
        section: The ``auth`` configuration section.
    """

    def __init__(self, section: AuthSection) -> None:
        self._cfg = section
        self._reverse_roles = {value: key for key, value in section.role_map.items()}

    async def authenticate(self, authorization: str | None) -> StaffPrincipal:
        """Returns the principal for an ``Authorization`` header value.

        Raises:
            AuthenticationError: If the token is missing or invalid.
        """
        if self._cfg.provider == "disabled":
            return self._principal(self._cfg.dev_user)
        if not authorization or not authorization.lower().startswith("bearer "):
            raise AuthenticationError("missing bearer token")
        token = authorization.split(" ", 1)[1]
        if self._cfg.provider == "entra_id":
            issuers, jwks = _entra_issuers(self._cfg.tenant_id), _entra_jwks(self._cfg.tenant_id)
        else:
            issuers, jwks = [self._cfg.issuer], self._cfg.jwks_url
        claims = await _decode(token, jwks, self._cfg.audience, issuers)
        return self._principal(claims)

    def _principal(self, claims: dict[str, Any]) -> StaffPrincipal:
        raw_roles = claims.get(self._cfg.role_claim) or claims.get("roles") or []
        roles = frozenset(self._reverse_roles.get(r, r.lower()) for r in raw_roles)
        hospitals = claims.get(self._cfg.hospital_claim) or claims.get("hospital_ids") or []
        if isinstance(hospitals, str):
            hospitals = [h.strip() for h in hospitals.split(",") if h.strip()]
        return StaffPrincipal(
            oid=str(claims.get("oid") or claims.get("sub") or ""),
            name=str(claims.get("name", "")),
            email=str(
                claims.get("preferred_username") or claims.get("email") or claims.get("upn") or ""
            ),
            roles=roles,
            hospital_ids=frozenset(hospitals),
        )


class InternalAuthenticator:
    """Authenticates callers of the internal job API.

    Args:
        section: The ``internal_auth`` configuration section.
    """

    def __init__(self, section: InternalAuthSection) -> None:
        self._cfg = section

    async def authenticate(self, authorization: str | None, internal_token: str | None) -> str:
        """Returns the caller identity.

        Raises:
            AuthenticationError: If credentials are missing or not allowed.
        """
        if self._cfg.mode == "disabled":
            return "anonymous"
        if self._cfg.mode == "shared_secret":
            supplied = internal_token or (authorization or "").removeprefix("Bearer ").strip()
            if (
                self._cfg.shared_secret
                and supplied
                and constant_time_equals(supplied, self._cfg.shared_secret)
            ):
                return "shared-secret"
            raise AuthenticationError("invalid internal token")
        if not authorization or not authorization.lower().startswith("bearer "):
            raise AuthenticationError("missing bearer token")
        claims = await _decode(
            authorization.split(" ", 1)[1],
            _entra_jwks(self._cfg.tenant_id),
            self._cfg.audience,
            _entra_issuers(self._cfg.tenant_id),
        )
        caller = str(claims.get("azp") or claims.get("appid") or "")
        if self._cfg.allowed_client_ids and caller not in self._cfg.allowed_client_ids:
            raise AuthenticationError("caller not allowed")
        return caller
