"""Management dashboard embedding contract.

The staff app asks for an embed configuration; the provider decides whether
that is a Power BI Embedded report, a Grafana dashboard or the built-in KPI
tiles. Every option is filtered to the caller's hospital.
"""

from __future__ import annotations

import abc
from typing import Any

from hcwave.adapters.base import Adapter


class DashboardProvider(Adapter, abc.ABC):
    """Abstract dashboard provider."""

    @abc.abstractmethod
    async def embed_config(self, hospital_id: str, user_name: str) -> dict[str, Any]:
        """Returns what the staff UI needs to render the dashboard."""
