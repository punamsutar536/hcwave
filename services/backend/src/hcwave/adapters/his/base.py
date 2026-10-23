"""Hospital Information System (HIS/LIS) connector contract.

Integration options, in order of preference (from the build guide): the HIS
vendor's API (``rest_api``), FHIR (``fhir``, e.g. Azure Health Data Services),
or scheduled file exports (``csv``, dropped into Blob Storage by Azure Data
Factory). Don't let integration block launch – a daily CSV is fine for a pilot.
"""

from __future__ import annotations

import abc
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, time
from typing import Any

from hcwave.adapters.base import Adapter, AdapterContext
from hcwave.adapters.storage.base import ObjectStorage
from hcwave.config.schema import HospitalConfig


@dataclass(frozen=True)
class HisSchedule:
    """A weekly OPD session."""

    weekday: int
    start_time: time
    end_time: time
    slot_minutes: int = 15
    capacity_per_slot: int = 1


@dataclass(frozen=True)
class HisDoctor:
    """A doctor with department and weekly schedule."""

    external_id: str
    name: str
    department_code: str
    department_name: str
    qualification: str = ""
    languages: tuple[str, ...] = ()
    consultation_fee: int | None = None
    schedules: tuple[HisSchedule, ...] = ()
    leave_dates: tuple[date, ...] = ()


@dataclass(frozen=True)
class HisPatient:
    """Minimal patient identity from the HIS."""

    mrn: str
    full_name: str
    phone: str
    date_of_birth: date | None = None
    gender: str | None = None
    whatsapp_consent: bool | None = None


@dataclass(frozen=True)
class HisVisit:
    """A completed, missed or discharged visit (drives feedback/follow-ups)."""

    external_id: str
    patient: HisPatient
    doctor_external_id: str
    start_at: datetime
    status: str  # completed | no_show | discharged
    checked_out_at: datetime | None = None
    follow_up_date: date | None = None


@dataclass(frozen=True)
class HisReport:
    """A report marked final in the LIS/RIS."""

    external_id: str
    patient: HisPatient
    title: str
    report_type: str
    file_ref: str
    finalized_at: datetime
    metadata: Mapping[str, Any] = field(default_factory=dict)


class HisConnector(Adapter, abc.ABC):
    """Abstract HIS connector.

    Args:
        raw_settings: Provider settings.
        ctx: Adapter context.
        storage: Object storage (file-based connectors read imports from it).
    """

    def __init__(
        self, raw_settings: Mapping[str, Any], ctx: AdapterContext, *, storage: ObjectStorage
    ) -> None:
        super().__init__(raw_settings, ctx)
        self.storage = storage

    @abc.abstractmethod
    async def fetch_doctors(self, hospital: HospitalConfig) -> list[HisDoctor]:
        """Returns all active doctors with schedules."""

    @abc.abstractmethod
    async def fetch_visits(self, hospital: HospitalConfig, since: datetime) -> list[HisVisit]:
        """Returns visits updated since ``since``."""

    @abc.abstractmethod
    async def fetch_reports(self, hospital: HospitalConfig, since: datetime) -> list[HisReport]:
        """Returns reports finalised since ``since``."""

    @abc.abstractmethod
    async def fetch_report_file(self, hospital: HospitalConfig, report: HisReport) -> bytes:
        """Downloads the PDF for a report."""

    async def push_appointment(
        self, hospital: HospitalConfig, appointment: Mapping[str, Any]
    ) -> str | None:
        """Pushes a booking to the HIS when it has a write API. Default: no-op."""
        return None


class NullHisConnector(HisConnector):
    """Connector for hospitals without integration yet (manual data entry)."""

    name = "none"

    async def fetch_doctors(self, hospital: HospitalConfig) -> list[HisDoctor]:
        """Returns nothing."""
        return []

    async def fetch_visits(self, hospital: HospitalConfig, since: datetime) -> list[HisVisit]:
        """Returns nothing."""
        return []

    async def fetch_reports(self, hospital: HospitalConfig, since: datetime) -> list[HisReport]:
        """Returns nothing."""
        return []

    async def fetch_report_file(self, hospital: HospitalConfig, report: HisReport) -> bytes:
        """Not supported."""
        raise FileNotFoundError(report.file_ref)
