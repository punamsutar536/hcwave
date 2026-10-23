"""Client for starting Durable Functions orchestrations.

When ``scheduler.feedback_engine`` is ``durable_functions``, a completed visit
starts a "wait N hours → send feedback → wait for reply → escalate" workflow
in Azure Functions instead of relying on the polling job.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from hcwave.core.container import Container

_log = logging.getLogger(__name__)


class DurableClient:
    """Starts orchestrations through the Function App's HTTP starter.

    The Function App is protected by Entra ID (App Service authentication);
    the backend calls it with its workload identity token.
    """

    def __init__(self, container: Container) -> None:
        self._c = container
        self._cfg = container.settings.scheduler

    @property
    def enabled(self) -> bool:
        """True when Durable Functions own the feedback workflow."""
        return self._cfg.feedback_engine == "durable_functions" and bool(
            self._cfg.durable_start_url
        )

    async def start_feedback(self, payload: dict[str, Any]) -> bool:
        """Starts the feedback orchestration for one visit (idempotent by instance ID)."""
        if not self.enabled:
            return False
        headers = {}
        if self._cfg.durable_audience:
            token = await self._c.credentials.get_token(f"{self._cfg.durable_audience}/.default")
            headers["Authorization"] = f"Bearer {token}"
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.post(
                    self._cfg.durable_start_url, json=payload, headers=headers
                )
            return response.status_code < 300
        except httpx.HTTPError:
            _log.exception("failed to start durable feedback orchestration")
            return False
