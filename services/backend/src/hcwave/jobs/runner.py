"""Scheduled job implementations shared by every trigger.

The same functions run whether they are triggered by Azure Logic Apps (HTTP
to the internal API), a Kubernetes CronJob (``hcwave-jobs <name>``), Durable
Functions activities, or an operator on the command line.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from hcwave.config.schema import HospitalConfig
from hcwave.domain.conversations import auto_release_stale
from hcwave.domain.services import Services
from hcwave.knowledge.ingest import reindex

_log = logging.getLogger(__name__)

JOB_NAMES = (
    "reminders",
    "feedback",
    "tickets-escalate",
    "briefing",
    "his-doctors",
    "his-visits",
    "his-reports",
    "maintenance",
    "knowledge-reindex",
)


class JobRunner:
    """Runs named jobs across hospitals, isolating failures per hospital.

    Args:
        services: Domain services.
    """

    def __init__(self, services: Services) -> None:
        self._s = services
        self._settings = services.container.settings

    def _hospitals(self, hospital_ids: list[str] | None) -> list[HospitalConfig]:
        return [
            h for h in self._settings.hospitals.values() if not hospital_ids or h.id in hospital_ids
        ]

    async def run(
        self, name: str, hospital_ids: list[str] | None = None, **options: Any
    ) -> dict[str, Any]:
        """Runs a job for each selected hospital.

        Args:
            name: One of :data:`JOB_NAMES`.
            hospital_ids: Restrict to these hospitals (default: all).
            **options: Job options (e.g. ``rules`` for reminders).

        Returns:
            Per-hospital results; a failing hospital reports ``{"error": ...}``
            and does not stop the others.

        Raises:
            ValueError: For an unknown job name.
        """
        if name == "knowledge-reindex":
            return {"indexed": await reindex(self._s.container, hospital_ids)}
        job = self._jobs().get(name)
        if job is None:
            raise ValueError(f"unknown job '{name}'. Known: {', '.join(JOB_NAMES)}")
        results: dict[str, Any] = {}
        for hospital in self._hospitals(hospital_ids):
            try:
                results[hospital.id] = await job(hospital, options)
            except Exception as exc:  # noqa: BLE001 - one tenant must not block others
                _log.exception("job %s failed for %s", name, hospital.id)
                results[hospital.id] = {"error": type(exc).__name__}
        return results

    def _jobs(self) -> dict[str, Callable[[HospitalConfig, dict[str, Any]], Awaitable[Any]]]:
        return {
            "reminders": self._reminders,
            "feedback": self._feedback,
            "tickets-escalate": self._escalate,
            "briefing": lambda h, _o: self._s.briefing.send(h),
            "his-doctors": lambda h, _o: self._s.his_sync.sync_doctors(h),
            "his-visits": lambda h, _o: self._s.his_sync.sync_visits(h),
            "his-reports": lambda h, _o: self._s.his_sync.sync_reports(h),
            "maintenance": self._maintenance,
        }

    async def _reminders(self, hospital: HospitalConfig, options: dict[str, Any]) -> dict[str, int]:
        return await self._s.reminders.run(hospital, rule_ids=options.get("rules"))

    async def _feedback(self, hospital: HospitalConfig, options: dict[str, Any]) -> dict[str, int]:
        result = {"requested": 0, "expired": 0}
        # With Durable Functions owning the timing, the job only expires stale requests.
        if self._settings.scheduler.feedback_engine == "jobs":
            result["requested"] = await self._s.feedback.run_requests(hospital)
        async with self._s.container.db.tenant_session(hospital.id) as session:
            result["expired"] = await self._s.feedback.expire_stale(session, hospital)
        return result

    async def _escalate(self, hospital: HospitalConfig, options: dict[str, Any]) -> dict[str, int]:
        async with self._s.container.db.tenant_session(hospital.id) as session:
            return {"escalated": await self._s.tickets.escalate_overdue(session, hospital)}

    async def _maintenance(
        self, hospital: HospitalConfig, options: dict[str, Any]
    ) -> dict[str, int]:
        minutes = self._settings.conversation.handover_auto_release_minutes
        async with self._s.container.db.tenant_session(hospital.id) as session:
            return {"released": await auto_release_stale(session, hospital.id, minutes)}
