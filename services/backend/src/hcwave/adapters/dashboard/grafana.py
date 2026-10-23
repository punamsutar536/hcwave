"""Azure Managed Grafana (or any Grafana) dashboard link."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from hcwave.adapters.base import AdapterSettings
from hcwave.adapters.dashboard.base import DashboardProvider


class GrafanaSettings(AdapterSettings):
    """Settings for Grafana. Staff sign in to Grafana with Entra ID."""

    base_url: str
    dashboard_uid: str
    hospital_variable: str = "hospital"


class GrafanaDashboard(DashboardProvider):
    """Returns a kiosk-mode dashboard URL filtered by hospital."""

    settings_model = GrafanaSettings
    name = "grafana"

    async def embed_config(self, hospital_id: str, user_name: str) -> dict[str, Any]:
        """Builds the dashboard URL."""
        url = (
            f"{self.config.base_url.rstrip('/')}/d/{self.config.dashboard_uid}"
            f"?var-{self.config.hospital_variable}={quote(hospital_id)}&kiosk"
        )
        return {"type": "grafana", "url": url}
