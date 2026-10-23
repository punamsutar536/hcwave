"""CSV connector: reads HIS exports dropped into object storage.

Azure Data Factory (or SFTP, or a hospital script) writes these files to the
``imports`` container under ``<hospital_id>/``:

* ``doctors.csv``   external_id, name, department_code, department_name,
  qualification, languages (``en|ml``), consultation_fee
* ``schedules.csv`` doctor_external_id, weekday (0=Mon), start_time, end_time,
  slot_minutes, capacity_per_slot
* ``leaves.csv``    doctor_external_id, date
* ``visits.csv``    external_id, mrn, patient_name, phone, date_of_birth,
  doctor_external_id, start_at, status, checked_out_at, follow_up_date,
  updated_at
* ``reports.csv``   external_id, mrn, patient_name, phone, date_of_birth,
  title, report_type, file_name, finalized_at

Report PDFs live under ``<hospital_id>/reports/<file_name>``. Column names
can be remapped per file in YAML (``columns``) to match the HIS export.
"""

from __future__ import annotations

import csv
import io
from datetime import date, datetime, time
from typing import Any
from zoneinfo import ZoneInfo

from hcwave.adapters.base import AdapterSettings
from hcwave.adapters.his.base import (
    HisConnector,
    HisDoctor,
    HisPatient,
    HisReport,
    HisSchedule,
    HisVisit,
)
from hcwave.config.schema import HospitalConfig


class CsvSettings(AdapterSettings):
    """Settings for the CSV connector.

    Attributes:
        container_key: Key in ``storage.containers`` holding the imports.
        columns: Per-file mapping of platform column -> export column.
        date_format: Format of date columns.
        datetime_format: Format of naive datetime columns (hospital local time).
    """

    container_key: str = "imports"
    columns: dict[str, dict[str, str]] = {}
    date_format: str = "%Y-%m-%d"
    datetime_format: str = "%Y-%m-%d %H:%M"


class CsvHisConnector(HisConnector):
    """HIS connector over CSV exports."""

    settings_model = CsvSettings
    name = "csv"

    def _container(self) -> str:
        return self.ctx.settings.storage.containers[self.config.container_key]

    async def _rows(self, hospital: HospitalConfig, file_name: str) -> list[dict[str, str]]:
        try:
            raw = await self.storage.get(self._container(), f"{hospital.id}/{file_name}")
        except FileNotFoundError:
            return []
        mapping = self.config.columns.get(file_name.removesuffix(".csv"), {})
        reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
        rows = []
        for row in reader:
            # Rename export columns to platform names.
            rows.append(
                {key: row.get(mapping.get(key, key), "").strip() for key in _all_keys(row, mapping)}
            )
        return rows

    def _date(self, value: str) -> date | None:
        return datetime.strptime(value, self.config.date_format).date() if value else None

    def _datetime(self, value: str, tz: str) -> datetime | None:
        if not value:
            return None
        parsed = datetime.strptime(value, self.config.datetime_format)
        return parsed.replace(tzinfo=ZoneInfo(tz))

    def _patient(self, row: dict[str, str]) -> HisPatient:
        return HisPatient(
            mrn=row["mrn"],
            full_name=row.get("patient_name", ""),
            phone=row.get("phone", ""),
            date_of_birth=self._date(row.get("date_of_birth", "")),
            whatsapp_consent=_bool(row.get("whatsapp_consent")),
        )

    async def fetch_doctors(self, hospital: HospitalConfig) -> list[HisDoctor]:
        """Joins doctors, schedules and leaves."""
        schedules: dict[str, list[HisSchedule]] = {}
        for row in await self._rows(hospital, "schedules.csv"):
            schedules.setdefault(row["doctor_external_id"], []).append(
                HisSchedule(
                    weekday=int(row["weekday"]),
                    start_time=time.fromisoformat(row["start_time"]),
                    end_time=time.fromisoformat(row["end_time"]),
                    slot_minutes=int(row.get("slot_minutes") or 15),
                    capacity_per_slot=int(row.get("capacity_per_slot") or 1),
                )
            )
        leaves: dict[str, list[date]] = {}
        for row in await self._rows(hospital, "leaves.csv"):
            parsed = self._date(row["date"])
            if parsed:
                leaves.setdefault(row["doctor_external_id"], []).append(parsed)
        doctors = []
        for row in await self._rows(hospital, "doctors.csv"):
            ext = row["external_id"]
            doctors.append(
                HisDoctor(
                    external_id=ext,
                    name=row["name"],
                    department_code=row["department_code"],
                    department_name=row.get("department_name") or row["department_code"],
                    qualification=row.get("qualification", ""),
                    languages=tuple(filter(None, row.get("languages", "").split("|"))),
                    consultation_fee=int(row["consultation_fee"])
                    if row.get("consultation_fee")
                    else None,
                    schedules=tuple(schedules.get(ext, [])),
                    leave_dates=tuple(leaves.get(ext, [])),
                )
            )
        return doctors

    async def fetch_visits(self, hospital: HospitalConfig, since: datetime) -> list[HisVisit]:
        """Returns visits whose ``updated_at`` (or start) is after ``since``."""
        visits = []
        for row in await self._rows(hospital, "visits.csv"):
            start = self._datetime(row["start_at"], hospital.timezone)
            updated = self._datetime(row.get("updated_at", ""), hospital.timezone) or start
            if start is None or (updated and updated < since):
                continue
            visits.append(
                HisVisit(
                    external_id=row["external_id"],
                    patient=self._patient(row),
                    doctor_external_id=row["doctor_external_id"],
                    start_at=start,
                    status=row.get("status", "completed"),
                    checked_out_at=self._datetime(row.get("checked_out_at", ""), hospital.timezone),
                    follow_up_date=self._date(row.get("follow_up_date", "")),
                )
            )
        return visits

    async def fetch_reports(self, hospital: HospitalConfig, since: datetime) -> list[HisReport]:
        """Returns reports finalised after ``since``."""
        reports = []
        for row in await self._rows(hospital, "reports.csv"):
            finalized = self._datetime(row["finalized_at"], hospital.timezone)
            if finalized is None or finalized < since:
                continue
            reports.append(
                HisReport(
                    external_id=row["external_id"],
                    patient=self._patient(row),
                    title=row.get("title") or "Report",
                    report_type=row.get("report_type") or "lab",
                    file_ref=f"{hospital.id}/reports/{row['file_name']}",
                    finalized_at=finalized,
                )
            )
        return reports

    async def fetch_report_file(self, hospital: HospitalConfig, report: HisReport) -> bytes:
        """Reads the PDF from the imports container."""
        return await self.storage.get(self._container(), report.file_ref)


def _all_keys(row: dict[str, Any], mapping: dict[str, str]) -> set[str]:
    reverse = {v: k for k, v in mapping.items()}
    return {reverse.get(key, key) for key in row if key is not None}


def _bool(value: str | None) -> bool | None:
    if value is None or value == "":
        return None
    return value.strip().lower() in {"1", "true", "yes", "y"}
