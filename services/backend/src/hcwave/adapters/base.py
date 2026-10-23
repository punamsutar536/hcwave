"""Common adapter plumbing.

Every adapter receives its own raw settings mapping (``providers.<name>`` in
YAML) plus an :class:`AdapterContext`, validates the mapping with its
``settings_model`` and exposes an async ``aclose``. Business code depends only
on the abstract base classes, never on a concrete cloud SDK.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict

from hcwave.config.schema import Settings
from hcwave.core.identity import CredentialFactory


class AdapterSettings(BaseModel):
    """Base for provider settings; unknown keys are rejected."""

    model_config = ConfigDict(extra="forbid")


class EmptySettings(AdapterSettings):
    """For providers that need no settings."""


@dataclass(frozen=True)
class AdapterContext:
    """Shared dependencies handed to every adapter.

    Attributes:
        settings: Root settings (read-only).
        credentials: Factory for Entra ID credentials.
    """

    settings: Settings
    credentials: CredentialFactory


class Adapter:
    """Base class for all pluggable adapters.

    Args:
        raw_settings: The provider's settings mapping from YAML.
        ctx: Shared adapter context.
    """

    settings_model: ClassVar[type[AdapterSettings]] = EmptySettings
    #: Short name recorded in logs and message rows.
    name: ClassVar[str] = "adapter"

    def __init__(self, raw_settings: Mapping[str, Any], ctx: AdapterContext) -> None:
        self.config: Any = self.settings_model.model_validate(dict(raw_settings))
        self.ctx = ctx

    async def aclose(self) -> None:
        """Releases network clients. Override when the adapter holds any."""
