"""Generic REST connector for HIS vendors that expose an API.

Endpoints and field names are configured in YAML, so a new HIS vendor is
usually a configuration task. Field mappings use dotted paths into the JSON
response (``patient.mobile``).
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime, time
from typing import Any

import httpx

from hcwave.adapters.base import AdapterContext, AdapterSettings
from hcwave.adapters.his.base import (
    HisConnector,
    HisDoctor,
    HisPatient,
    HisReport,
    HisSchedule,
    HisVisit,
)
from hcwave.config.schema import HospitalConfig


class RestApiSettings(AdapterSettings):
    """Settings for the REST connector.

    Attributes:
        base_url: Vendor API base URL (may contain ``{hospital_id}``).
        auth: ``bearer`` (static token), ``entra_id`` (managed identity token
            for ``token_scope``) or ``none``.
        token: Static bearer token (secret).
        token_scope: Entra scope when ``auth=entra_id``.
        endpoints: Logical name -> path (doctors, visits, reports,
            report_file, appointments). ``{since}``/``{id}`` placeholders allowed.
        fields: Logical name -> mapping of platform field -> dotted JSON path.
        items_path: Dotted path to the list inside list responses.
    """

    base_url: str
    auth: str = "bearer"
    token: str = ""
    token_scope: str = ""
    endpoints: dict[str, str] = {
        "doctors": "/doctors",
        "visits": "/visits?since={since}",
        "reports": "/reports?status=final&since={since}",
        "report_file": "/reports/{id}/pdf",
        "appointments": "/appointments",
    }
    fields: dict[str, dict[str, str]] = {}
    items_path: str = "items"
    timeout_seconds: float = 20


def _get(obj: Any, path: str, default: Any = None) -> Any:
    for part in path.split("."):
        if not isinstance(obj, Mapping) or part not in obj:
            return default
        obj = obj[part]
    return obj


class RestApiHisConnector(HisConnector):
    """HIS connector over a vendor REST API."""

    settings_model = RestApiSettings
    name = "rest_api"

    def __init__(self, raw_settings: Mapping[str, Any], ctx: AdapterContext, **kwargs: Any) -> None:
        super().__init__(raw_settings, ctx, **kwargs)
        self._http = httpx.AsyncClient(timeout=self.config.timeout_seconds)

    async def _headers(self) -> dict[str, str]:
        if self.config.auth == "bearer" and self.config.token:
            return {"Authorization": f"Bearer {self.config.token}"}
        if self.config.auth == "entra_id":
            return {
                "Authorization": f"Bearer {await self.ctx.credentials.get_token(self.config.token_scope)}"
            }
        return {}

    async def _request(
        self, method: str, hospital: HospitalConfig, endpoint: str, **params: Any
    ) -> httpx.Response:
        url = (self.config.base_url + self.config.endpoints[endpoint]).format(
            hospital_id=hospital.id, **params
        )
        response = await self._http.request(
            method, url, headers=await self._headers(), json=params.get("json")
        )
        response.raise_for_status()
        return response

    async def _items(
        self, hospital: HospitalConfig, endpoint: str, **params: Any
    ) -> list[Mapping[str, Any]]:
        data = (await self._request("GET", hospital, endpoint, **params)).json()
        return data if isinstance(data, list) else _get(data, self.config.items_path, [])

    def _field(self, kind: str, item: Mapping[str, Any], name: str, default: Any = None) -> Any:
        return _get(item, self.config.fields.get(kind, {}).get(name, name), default)

    def _patient(self, kind: str, item: Mapping[str, Any]) -> HisPatient:
        dob = self._field(kind, item, "date_of_birth")
        return HisPatient(
            mrn=str(self._field(kind, item, "mrn")),
            full_name=self._field(kind, item, "patient_name", ""),
            phone=self._field(kind, item, "phone", ""),
            date_of_birth=date.fromisoformat(dob) if dob else None,
        )

    async def fetch_doctors(self, hospital: HospitalConfig) -> list[HisDoctor]:
        """GETs the doctors endpoint."""
        doctors = []
        for item in await self._items(hospital, "doctors"):
            schedules = tuple(
                HisSchedule(
                    weekday=int(s["weekday"]),
                    start_time=time.fromisoformat(s["start_time"]),
                    end_time=time.fromisoformat(s["end_time"]),
                    slot_minutes=int(s.get("slot_minutes", 15)),
                    capacity_per_slot=int(s.get("capacity_per_slot", 1)),
                )
                for s in self._field("doctors", item, "schedules", []) or []
            )
            doctors.append(
                HisDoctor(
                    external_id=str(self._field("doctors", item, "external_id")),
                    name=self._field("doctors", item, "name", ""),
                    department_code=str(self._field("doctors", item, "department_code", "")),
                    department_name=self._field("doctors", item, "department_name", ""),
                    qualification=self._field("doctors", item, "qualification", "") or "",
                    schedules=schedules,
                )
            )
        return doctors

    async def fetch_visits(self, hospital: HospitalConfig, since: datetime) -> list[HisVisit]:
        """GETs visits updated since ``since``."""
        visits = []
        for item in await self._items(hospital, "visits", since=since.isoformat()):
            checked_out = self._field("visits", item, "checked_out_at")
            follow_up = self._field("visits", item, "follow_up_date")
            visits.append(
                HisVisit(
                    external_id=str(self._field("visits", item, "external_id")),
                    patient=self._patient("visits", item),
                    doctor_external_id=str(self._field("visits", item, "doctor_external_id")),
                    start_at=datetime.fromisoformat(self._field("visits", item, "start_at")),
                    status=self._field("visits", item, "status", "completed"),
                    checked_out_at=datetime.fromisoformat(checked_out) if checked_out else None,
                    follow_up_date=date.fromisoformat(follow_up) if follow_up else None,
                )
            )
        return visits

    async def fetch_reports(self, hospital: HospitalConfig, since: datetime) -> list[HisReport]:
        """GETs reports finalised since ``since``."""
        return [
            HisReport(
                external_id=str(self._field("reports", item, "external_id")),
                patient=self._patient("reports", item),
                title=self._field("reports", item, "title", "Report"),
                report_type=self._field("reports", item, "report_type", "lab"),
                file_ref=str(self._field("reports", item, "external_id")),
                finalized_at=datetime.fromisoformat(self._field("reports", item, "finalized_at")),
            )
            for item in await self._items(hospital, "reports", since=since.isoformat())
        ]

    async def fetch_report_file(self, hospital: HospitalConfig, report: HisReport) -> bytes:
        """GETs the PDF bytes."""
        return (await self._request("GET", hospital, "report_file", id=report.file_ref)).content

    async def push_appointment(
        self, hospital: HospitalConfig, appointment: Mapping[str, Any]
    ) -> str | None:
        """POSTs the booking and returns the HIS appointment ID if provided."""
        if "appointments" not in self.config.endpoints:
            return None
        data = (
            await self._request("POST", hospital, "appointments", json=dict(appointment))
        ).json()
        return str(_get(data, "id")) if _get(data, "id") else None

    async def aclose(self) -> None:
        """Closes the HTTP client."""
        await self._http.aclose()
