"""Built-in KPI tiles served by ``/staff/dashboard/summary`` (no BI licence)."""

from __future__ import annotations

from typing import Any

from hcwave.adapters.dashboard.base import DashboardProvider


class BuiltinDashboard(DashboardProvider):
    """Tells the UI to render its own KPI tiles."""

    name = "builtin"

    async def embed_config(self, hospital_id: str, user_name: str) -> dict[str, Any]:
        """Returns the built-in marker."""
        return {"type": "builtin", "summary_url": "/staff/dashboard/summary"}
