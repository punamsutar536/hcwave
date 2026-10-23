"""Cloud identity: one place that creates Azure credentials.

In AKS the pod's service account is federated with a user-assigned managed
identity (Microsoft Entra Workload ID), so ``DefaultAzureCredential`` gets
tokens with no secret anywhere. Locally it falls back to ``az login``.
Non-Azure deployments set ``identity.mode: none`` and use keys from env.
"""

from __future__ import annotations

import functools
from typing import Any

from hcwave.config.schema import IdentitySection
from hcwave.core.errors import ConfigurationError


class CredentialFactory:
    """Lazily creates and caches sync/async Azure credentials.

    Args:
        section: The ``identity`` configuration section.
    """

    def __init__(self, section: IdentitySection) -> None:
        self._section = section

    @property
    def enabled(self) -> bool:
        """True when token-based (Entra ID) authentication is configured."""
        return self._section.mode != "none"

    @functools.cached_property
    def sync(self) -> Any:
        """A synchronous ``TokenCredential``."""
        return self._build(asynchronous=False)

    @functools.cached_property
    def aio(self) -> Any:
        """An asynchronous ``AsyncTokenCredential``."""
        return self._build(asynchronous=True)

    def _build(self, asynchronous: bool) -> Any:
        if not self.enabled:
            raise ConfigurationError(
                "identity.mode is 'none' but a provider requested Entra ID auth; "
                "configure an API key for that provider instead"
            )
        if asynchronous:
            from azure.identity.aio import (
                DefaultAzureCredential,
                ManagedIdentityCredential,
                WorkloadIdentityCredential,
            )
        else:
            from azure.identity import (
                DefaultAzureCredential,
                ManagedIdentityCredential,
                WorkloadIdentityCredential,
            )
        client_id = self._section.client_id or None
        if self._section.mode == "workload_identity":
            return WorkloadIdentityCredential(client_id=client_id)
        if self._section.mode == "managed_identity":
            return ManagedIdentityCredential(client_id=client_id)
        return DefaultAzureCredential(managed_identity_client_id=client_id)

    def bearer_token_provider(self, scope: str) -> Any:
        """Returns a sync callable yielding bearer tokens (for OpenAI clients)."""
        from azure.identity import get_bearer_token_provider

        return get_bearer_token_provider(self.sync, scope)

    def async_bearer_token_provider(self, scope: str) -> Any:
        """Returns an async callable yielding bearer tokens."""
        from azure.identity.aio import get_bearer_token_provider

        return get_bearer_token_provider(self.aio, scope)

    async def get_token(self, scope: str) -> str:
        """Fetches an access token string for ``scope``."""
        token = await self.aio.get_token(scope)
        return token.token

    async def aclose(self) -> None:
        """Closes the async credential if it was created."""
        if "aio" in self.__dict__:
            await self.aio.close()
