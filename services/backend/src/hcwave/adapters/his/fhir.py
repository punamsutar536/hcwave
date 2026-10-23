"""FHIR R4 connector (Azure Health Data Services or any FHIR server).

Useful once hospitals or HIS vendors expose standard APIs. Maps
PractitionerRole + Schedule to doctors and DiagnosticReport (status=final) to
reports. Authenticates with the workload identity (``FHIR Data Reader``).
"""

from __future__ import annotations

import base64
from collections.abc import Mapping
from datetime import date, datetime
from typing import Any

import httpx

from hcwave.adapters.base import AdapterContext, AdapterSettings
from hcwave.adapters.his.base import HisConnector, HisDoctor, HisPatient, HisReport, HisVisit
from hcwave.config.schema import HospitalConfig


class FhirSettings(AdapterSettings):
    """Settings for the FHIR connector."""

    base_url: str
    auth: str = "entra_id"  # entra_id | none
    timeout_seconds: float = 20


class FhirHisConnector(HisConnector):
    """HIS connector over FHIR R4."""

    settings_model = FhirSettings
    name = "fhir"

    def __init__(self, raw_settings: Mapping[str, Any], ctx: AdapterContext, **kwargs: Any) -> None:
        super().__init__(raw_settings, ctx, **kwargs)
        self._http = httpx.AsyncClient(timeout=self.config.timeout_seconds)

    async def _search(self, resource: str, params: dict[str, str]) -> list[dict[str, Any]]:
        headers = {"Accept": "application/fhir+json"}
        if self.config.auth == "entra_id":
            token = await self.ctx.credentials.get_token(
                f"{self.config.base_url.rstrip('/')}/.default"
            )
            headers["Authorization"] = f"Bearer {token}"
        url: str | None = f"{self.config.base_url.rstrip('/')}/{resource}"
        entries: list[dict[str, Any]] = []
        while url:
            response = await self._http.get(
                url, params=params if not entries else None, headers=headers
            )
            response.raise_for_status()
            bundle = response.json()
            entries += [e["resource"] for e in bundle.get("entry", [])]
            url = next(
                (link["url"] for link in bundle.get("link", []) if link.get("relation") == "next"),
                None,
            )
        return entries

    @staticmethod
    def _patient(resource: Mapping[str, Any]) -> HisPatient:
        name = (resource.get("name") or [{}])[0]
        phone = next(
            (t["value"] for t in resource.get("telecom", []) if t.get("system") == "phone"), ""
        )
        dob = resource.get("birthDate")
        return HisPatient(
            mrn=resource.get("id", ""),
            full_name=name.get("text")
            or " ".join(name.get("given", []) + [name.get("family", "")]).strip(),
            phone=phone,
            date_of_birth=date.fromisoformat(dob) if dob else None,
            gender=resource.get("gender"),
        )

    async def fetch_doctors(self, hospital: HospitalConfig) -> list[HisDoctor]:
        """Maps active PractitionerRoles (with included Practitioner) to doctors."""
        resources = await self._search(
            "PractitionerRole", {"active": "true", "_include": "PractitionerRole:practitioner"}
        )
        practitioners = {r["id"]: r for r in resources if r["resourceType"] == "Practitioner"}
        doctors = []
        for role in (r for r in resources if r["resourceType"] == "PractitionerRole"):
            ref = role.get("practitioner", {}).get("reference", "").split("/")[-1]
            person = practitioners.get(ref, {})
            name = (person.get("name") or [{}])[0]
            specialty = ((role.get("specialty") or [{}])[0].get("coding") or [{}])[0]
            doctors.append(
                HisDoctor(
                    external_id=ref or role["id"],
                    name=name.get("text")
                    or " ".join(
                        name.get("prefix", []) + name.get("given", []) + [name.get("family", "")]
                    ).strip(),
                    department_code=specialty.get("code", "general"),
                    department_name=specialty.get("display", "General"),
                )
            )
        return doctors

    async def fetch_visits(self, hospital: HospitalConfig, since: datetime) -> list[HisVisit]:
        """Maps finished Encounters (with Patient) to visits."""
        resources = await self._search(
            "Encounter",
            {
                "status": "finished",
                "_lastUpdated": f"gt{since.isoformat()}",
                "_include": "Encounter:subject",
            },
        )
        patients = {r["id"]: self._patient(r) for r in resources if r["resourceType"] == "Patient"}
        visits = []
        for enc in (r for r in resources if r["resourceType"] == "Encounter"):
            patient = patients.get(enc.get("subject", {}).get("reference", "").split("/")[-1])
            period = enc.get("period", {})
            if not patient or not period.get("start"):
                continue
            participant = (
                (enc.get("participant") or [{}])[0].get("individual", {}).get("reference", "")
            )
            visits.append(
                HisVisit(
                    external_id=enc["id"],
                    patient=patient,
                    doctor_external_id=participant.split("/")[-1],
                    start_at=datetime.fromisoformat(period["start"]),
                    status="discharged"
                    if enc.get("class", {}).get("code") == "IMP"
                    else "completed",
                    checked_out_at=datetime.fromisoformat(period["end"])
                    if period.get("end")
                    else None,
                )
            )
        return visits

    async def fetch_reports(self, hospital: HospitalConfig, since: datetime) -> list[HisReport]:
        """Maps final DiagnosticReports (with Patient) to reports."""
        resources = await self._search(
            "DiagnosticReport",
            {
                "status": "final",
                "_lastUpdated": f"gt{since.isoformat()}",
                "_include": "DiagnosticReport:subject",
            },
        )
        patients = {r["id"]: self._patient(r) for r in resources if r["resourceType"] == "Patient"}
        reports = []
        for rep in (r for r in resources if r["resourceType"] == "DiagnosticReport"):
            patient = patients.get(rep.get("subject", {}).get("reference", "").split("/")[-1])
            form = next(
                (
                    f
                    for f in rep.get("presentedForm", [])
                    if f.get("contentType") == "application/pdf"
                ),
                None,
            )
            if not patient or not form:
                continue
            reports.append(
                HisReport(
                    external_id=rep["id"],
                    patient=patient,
                    title=rep.get("code", {}).get("text", "Report"),
                    report_type="radiology" if "RAD" in str(rep.get("category")) else "lab",
                    file_ref=form.get("url") or "inline",
                    finalized_at=datetime.fromisoformat(
                        rep.get("issued") or rep["meta"]["lastUpdated"]
                    ),
                    metadata={"inline": form.get("data")},
                )
            )
        return reports

    async def fetch_report_file(self, hospital: HospitalConfig, report: HisReport) -> bytes:
        """Returns inline attachment data or downloads the Binary URL."""
        if report.metadata.get("inline"):
            return base64.b64decode(report.metadata["inline"])
        headers = {}
        if self.config.auth == "entra_id":
            token = await self.ctx.credentials.get_token(
                f"{self.config.base_url.rstrip('/')}/.default"
            )
            headers["Authorization"] = f"Bearer {token}"
        response = await self._http.get(
            report.file_ref, headers={**headers, "Accept": "application/pdf"}
        )
        response.raise_for_status()
        return response.content

    async def aclose(self) -> None:
        """Closes the HTTP client."""
        await self._http.aclose()
