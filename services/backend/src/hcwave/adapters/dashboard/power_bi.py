"""Power BI Embedded ("app owns data") with row-level security per hospital.

The workload identity must be allowed to use Power BI APIs (tenant setting)
and be a member of the workspace. The dataset defines an RLS role (default
``Hospital``) filtering on ``USERNAME()`` = hospital ID.
"""

from __future__ import annotations

from typing import Any

import httpx

from hcwave.adapters.base import AdapterSettings
from hcwave.adapters.dashboard.base import DashboardProvider

_SCOPE = "https://analysis.windows.net/powerbi/api/.default"
_API = "https://api.powerbi.com/v1.0/myorg"


class PowerBISettings(AdapterSettings):
    """Settings for Power BI Embedded."""

    workspace_id: str
    report_id: str
    rls_role: str = "Hospital"
    token_lifetime_minutes: int = 60


class PowerBIDashboard(DashboardProvider):
    """Generates embed tokens scoped to the caller's hospital."""

    settings_model = PowerBISettings
    name = "power_bi"

    async def embed_config(self, hospital_id: str, user_name: str) -> dict[str, Any]:
        """Looks up the report and generates an RLS-scoped embed token."""
        token = await self.ctx.credentials.get_token(_SCOPE)
        headers = {"Authorization": f"Bearer {token}"}
        base = f"{_API}/groups/{self.config.workspace_id}/reports/{self.config.report_id}"
        async with httpx.AsyncClient(timeout=15, headers=headers) as client:
            report = (await client.get(base)).raise_for_status().json()
            embed = (
                (
                    await client.post(
                        f"{base}/GenerateToken",
                        json={
                            "accessLevel": "View",
                            "lifetimeInMinutes": self.config.token_lifetime_minutes,
                            "identities": [
                                {
                                    "username": hospital_id,
                                    "roles": [self.config.rls_role],
                                    "datasets": [report["datasetId"]],
                                }
                            ],
                        },
                    )
                )
                .raise_for_status()
                .json()
            )
        return {
            "type": "powerbi",
            "report_id": self.config.report_id,
            "embed_url": report["embedUrl"],
            "access_token": embed["token"],
            "expiration": embed["expiration"],
        }
