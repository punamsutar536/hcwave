"""Secure report delivery.

Report PDFs never go into WhatsApp chats (phones get shared, and this is
sensitive health data). Instead:

1. The LIS/HIS marks a report final (HIS sync, a watched folder or an event).
2. The PDF is copied into private, encrypted storage.
3. A template message carries a link that expires in 24–72 hours.
4. Before opening, the patient verifies with an OTP or date of birth.
5. The PDF is served through a short-lived signed URL.

Every step is written to ``report_access_logs``. AI never summarises or
interprets results in this phase – that is a clinical activity.
"""

from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from hcwave.adapters.his.base import HisReport
from hcwave.config.schema import HospitalConfig
from hcwave.core.clock import utcnow
from hcwave.core.container import Container
from hcwave.core.errors import PolicyViolationError
from hcwave.core.security import constant_time_equals, hmac_hex, new_link_token, new_otp, sha256_hex
from hcwave.db.models import (
    MessageStatus,
    OtpChallenge,
    Patient,
    Report,
    ReportAccessLog,
    ReportStatus,
)
from hcwave.domain.consent import may_send_proactive
from hcwave.domain.context import first_name
from hcwave.domain.conversations import get_or_create_conversation
from hcwave.domain.messenger import Messenger
from hcwave.domain.notifications import claim_notification
from hcwave.domain.patients import report_recipients, upsert_patient_from_his

_log = logging.getLogger(__name__)


class ReportService:
    """Report ingestion, notification, verification and download.

    Args:
        container: Dependency container.
        messenger: Policy-aware sender.
    """

    def __init__(self, container: Container, messenger: Messenger) -> None:
        self._c = container
        self._cfg = container.settings.reports
        self._messenger = messenger

    @property
    def _container_name(self) -> str:
        return self._c.settings.storage.containers["reports"]

    def link_url(self, hospital_id: str, token: str) -> str:
        """Public URL of the report portal page for a token."""
        base = (self._cfg.link_base_url or self._c.settings.app.public_base_url).rstrip("/")
        return f"{base}/r/{hospital_id}/{token}"

    # ------------------------------------------------------------------ #
    # Ingestion and notification
    # ------------------------------------------------------------------ #
    async def ingest(
        self, session: AsyncSession, hospital: HospitalConfig, source: HisReport, pdf: bytes
    ) -> Report | None:
        """Stores a finalised report. Returns None if it was already ingested."""
        existing = await session.scalar(
            select(Report.id).where(
                Report.hospital_id == hospital.id, Report.external_id == source.external_id
            )
        )
        if existing:
            return None
        patient = await upsert_patient_from_his(
            session, hospital.id, source.patient, self._c.settings.conversation.default_country_code
        )
        report_id = uuid.uuid4()
        blob_path = f"{hospital.id}/{patient.id}/{report_id}.pdf"
        await self._c.storage.put(self._container_name, blob_path, pdf, "application/pdf")
        report = Report(
            id=report_id,
            hospital_id=hospital.id,
            patient_id=patient.id,
            external_id=source.external_id,
            title=source.title[:200],
            report_type=source.report_type,
            blob_path=blob_path,
            status=ReportStatus.READY,
            ready_at=source.finalized_at,
            failed_verifications=0,
        )
        session.add(report)
        await session.flush()
        return report

    async def notify(self, session: AsyncSession, hospital: HospitalConfig, report: Report) -> int:
        """Sends the report-ready template to every registered recipient.

        Only phones registered against the patient (self, parent, guardian)
        receive the link – the rule for minors and family members.

        Returns:
            Number of recipients notified.
        """
        if not await claim_notification(session, hospital.id, "report_ready", report.id):
            return 0
        patient = await session.get(Patient, report.patient_id)
        assert patient is not None
        token = new_link_token()
        report.link_token_hash = sha256_hex(token)
        report.link_expires_at = utcnow() + timedelta(hours=self._cfg.link_ttl_hours)

        notified = 0
        for phone in await report_recipients(session, patient):
            conversation = await get_or_create_conversation(
                session, hospital.id, phone, language=patient.preferred_language
            )
            if not may_send_proactive(conversation, patient):
                continue
            message = self._messenger.template(
                hospital,
                "report_ready",
                conversation.language,
                {
                    "patient_name": first_name(patient.full_name),
                    "report_title": report.title,
                    "expiry_hours": str(self._cfg.link_ttl_hours),
                    "link_suffix": f"{hospital.id}/{token}",
                },
            )
            try:
                row = await self._messenger.send(
                    session, hospital, conversation, message, sender="system"
                )
            except PolicyViolationError:
                continue
            notified += row.status != MessageStatus.FAILED
        report.status = ReportStatus.NOTIFIED if notified else ReportStatus.FAILED
        report.notified_at = utcnow() if notified else None
        await self.log(session, report, "notified" if notified else "notify_failed")
        return notified

    # ------------------------------------------------------------------ #
    # Portal: link resolution, verification, download
    # ------------------------------------------------------------------ #
    async def find_by_token(
        self, session: AsyncSession, hospital_id: str, token: str
    ) -> Report | None:
        """Resolves an unexpired link token to its report."""
        report = await session.scalar(
            select(Report).where(
                Report.hospital_id == hospital_id, Report.link_token_hash == sha256_hex(token)
            )
        )
        if report is None or report.link_expires_at is None or report.link_expires_at < utcnow():
            return None
        return report

    @staticmethod
    def is_locked(report: Report) -> bool:
        """True while the link is locked after too many failed verifications."""
        return report.locked_until is not None and report.locked_until > utcnow()

    async def log(
        self,
        session: AsyncSession,
        report: Report,
        event: str,
        ip: str | None = None,
        user_agent: str | None = None,
    ) -> None:
        """Appends an access-audit row."""
        session.add(
            ReportAccessLog(
                hospital_id=report.hospital_id,
                report_id=report.id,
                event=event,
                ip_address=ip,
                user_agent=(user_agent or "")[:300] or None,
            )
        )

    async def _register_failure(
        self, session: AsyncSession, report: Report, ip: str | None, ua: str | None
    ) -> None:
        report.failed_verifications += 1
        await self.log(session, report, "verify_failed", ip, ua)
        if report.failed_verifications >= self._cfg.max_verification_attempts:
            report.locked_until = utcnow() + timedelta(minutes=self._cfg.lockout_minutes)
            report.failed_verifications = 0
            await self.log(session, report, "locked", ip, ua)

    def _otp_hash(self, report_id: uuid.UUID, code: str) -> str:
        return hmac_hex(self._c.settings.app.secret_key, f"{report_id}:{code}")

    async def send_otp(
        self,
        session: AsyncSession,
        hospital: HospitalConfig,
        report: Report,
        ip: str | None,
        ua: str | None,
    ) -> str:
        """Issues an OTP to the patient's registered number.

        WhatsApp (authentication template) is tried first; SMS is the fallback.

        Returns:
            The channel used (``whatsapp`` or ``sms``).

        Raises:
            PolicyViolationError: If locked, rate limited or undeliverable.
        """
        if self.is_locked(report):
            raise PolicyViolationError("link locked")
        recent = await session.scalar(
            select(func.count(OtpChallenge.id)).where(
                OtpChallenge.report_id == report.id,
                OtpChallenge.created_at > utcnow() - timedelta(minutes=10),
            )
        )
        if (recent or 0) >= 3:
            raise PolicyViolationError("too many OTP requests")
        patient = await session.get(Patient, report.patient_id)
        assert patient is not None
        otp_cfg = self._cfg.otp
        code = new_otp(otp_cfg.length)

        channel = ""
        if "whatsapp" in otp_cfg.channels:
            conversation = await get_or_create_conversation(
                session, hospital.id, patient.phone_e164
            )
            message = self._messenger.template(
                hospital, "otp_code", conversation.language, {"code": code}
            )
            try:
                row = await self._messenger.send(
                    session, hospital, conversation, message, sender="system"
                )
                channel = "whatsapp" if row.status != MessageStatus.FAILED else ""
            except PolicyViolationError:
                channel = ""
        if not channel and "sms" in otp_cfg.channels:
            text = (
                f"{code} is your OTP to view your {hospital.name} report. "
                f"Valid for {otp_cfg.ttl_minutes} minutes. Do not share it."
            )
            if await self._c.sms.send(patient.phone_e164, text, "otp", {"otp": code}):
                channel = "sms"
        if not channel:
            raise PolicyViolationError("could not deliver OTP")

        session.add(
            OtpChallenge(
                hospital_id=hospital.id,
                report_id=report.id,
                phone_e164=patient.phone_e164,
                code_hash=self._otp_hash(report.id, code),
                channel=channel,
                attempts=0,
                expires_at=utcnow() + timedelta(minutes=otp_cfg.ttl_minutes),
            )
        )
        await self.log(session, report, f"otp_sent_{channel}", ip, ua)
        return channel

    async def verify_otp(
        self, session: AsyncSession, report: Report, code: str, ip: str | None, ua: str | None
    ) -> bool:
        """Checks an OTP against the latest open challenge."""
        if self.is_locked(report) or "otp" not in self._cfg.verification_methods:
            return False
        challenge = await session.scalar(
            select(OtpChallenge)
            .where(
                OtpChallenge.report_id == report.id,
                OtpChallenge.consumed_at.is_(None),
                OtpChallenge.expires_at > utcnow(),
            )
            .order_by(OtpChallenge.created_at.desc())
            .limit(1)
            .with_for_update()
        )
        if challenge is None or challenge.attempts >= self._cfg.otp.max_attempts:
            await self._register_failure(session, report, ip, ua)
            return False
        challenge.attempts += 1
        if not constant_time_equals(self._otp_hash(report.id, code.strip()), challenge.code_hash):
            await self._register_failure(session, report, ip, ua)
            return False
        challenge.consumed_at = utcnow()
        report.failed_verifications = 0
        await self.log(session, report, "verify_otp_ok", ip, ua)
        return True

    async def verify_dob(
        self, session: AsyncSession, report: Report, dob: date, ip: str | None, ua: str | None
    ) -> bool:
        """Checks the patient's date of birth."""
        if self.is_locked(report) or "dob" not in self._cfg.verification_methods:
            return False
        patient = await session.get(Patient, report.patient_id)
        if patient is None or patient.date_of_birth is None or patient.date_of_birth != dob:
            await self._register_failure(session, report, ip, ua)
            return False
        report.failed_verifications = 0
        await self.log(session, report, "verify_dob_ok", ip, ua)
        return True

    async def open(
        self, session: AsyncSession, report: Report, ip: str | None, ua: str | None
    ) -> tuple[str | None, bytes | None]:
        """Returns a short-lived URL, or the bytes when the store cannot sign URLs."""
        name = f"{report.title[:60].replace('/', '-')}.pdf"
        url = await self._c.storage.temporary_url(
            self._container_name, report.blob_path, self._cfg.download_url_ttl_minutes, name
        )
        data = None if url else await self._c.storage.get(self._container_name, report.blob_path)
        if report.first_opened_at is None:
            report.first_opened_at = utcnow()
        report.status = ReportStatus.OPENED
        await self.log(session, report, "downloaded", ip, ua)
        return url, data

    async def notify_pending(self, hospital: HospitalConfig, since: datetime | None = None) -> int:
        """Notifies every READY report not yet notified (retry helper)."""
        total = 0
        async with self._c.db.tenant_session(hospital.id) as session:
            query = select(Report).where(
                Report.hospital_id == hospital.id, Report.status == ReportStatus.READY
            )
            if since:
                query = query.where(Report.ready_at >= since)
            for report in await session.scalars(query):
                total += await self.notify(session, hospital, report)
        return total
