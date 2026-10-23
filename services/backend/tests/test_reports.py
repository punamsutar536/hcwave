import re

from sqlalchemy import select

from hcwave.db.models import Report, ReportAccessLog, ReportStatus
from hcwave.domain.conversations import get_or_create_conversation

from .conftest import HOSPITAL, PHONE

PDF = b"%PDF-1.4 test report"


async def _drop_his_report(container):
    imports = container.settings.storage.containers["imports"]
    csv = (
        "external_id,mrn,patient_name,phone,date_of_birth,title,report_type,file_name,finalized_at,whatsapp_consent\n"
        f"LAB-1,MRN-1,Lakshmi Pillai,{PHONE},1990-02-14,Complete Blood Count,lab,lab-1.pdf,2099-01-01 10:00,yes\n"
    )
    await container.storage.put(imports, f"{HOSPITAL}/reports.csv", csv.encode(), "text/csv")
    await container.storage.put(imports, f"{HOSPITAL}/reports/lab-1.pdf", PDF, "application/pdf")


async def _notified_token(container, services):
    await _drop_his_report(container)
    result = await services.his_sync.sync_reports(container.hospital(HOSPITAL))
    assert result == {"ingested": 1, "notified": 1}
    _to, message = container.messaging.sent[-1]
    assert message.template_name == "hcw_report_ready"
    suffix = message.template_buttons[0].value
    hospital_id, token = suffix.split("/")
    assert hospital_id == HOSPITAL
    return token


async def test_report_notification_has_no_pdf_in_chat(container, services, clean):
    await _notified_token(container, services)
    sent_kinds = {m.kind.value for _to, m in container.messaging.sent}
    assert "media" not in sent_kinds
    async with container.db.tenant_session(HOSPITAL) as session:
        report = await session.scalar(select(Report))
        assert report.status == ReportStatus.NOTIFIED and report.link_token_hash


async def test_dob_verification_then_view(container, services, client, clean):
    token = await _notified_token(container, services)
    page = await client.get(f"/r/{HOSPITAL}/{token}")
    assert page.status_code == 200 and "Complete Blood Count" in page.text
    csrf = re.search(r'name="csrf" value="([^"]+)"', page.text).group(1)

    bad = await client.post(
        f"/r/{HOSPITAL}/{token}/verify", data={"csrf": csrf, "method": "dob", "dob": "1991-01-01"}
    )
    assert "didn" in bad.text
    ok = await client.post(
        f"/r/{HOSPITAL}/{token}/verify", data={"csrf": csrf, "method": "dob", "dob": "1990-02-14"}
    )
    assert ok.status_code == 200 and "View report" in ok.text
    view = await client.get(f"/r/{HOSPITAL}/{token}/view")  # session cookie kept by the client
    assert view.status_code == 200 and view.content == PDF

    async with container.db.tenant_session(HOSPITAL) as session:
        events = [e for e in await session.scalars(select(ReportAccessLog.event))]
        assert {"notified", "link_opened", "verify_failed", "verify_dob_ok", "downloaded"} <= set(
            events
        )


async def test_otp_verification(container, services, client, clean):
    token = await _notified_token(container, services)
    page = await client.get(f"/r/{HOSPITAL}/{token}")
    csrf = re.search(r'name="csrf" value="([^"]+)"', page.text).group(1)
    sent = await client.post(f"/r/{HOSPITAL}/{token}/otp", data={"csrf": csrf})
    assert "WhatsApp" in sent.text
    _to, otp_message = container.messaging.sent[-1]
    assert otp_message.category == "authentication"
    code = otp_message.template_params[0].value
    ok = await client.post(
        f"/r/{HOSPITAL}/{token}/verify", data={"csrf": csrf, "method": "otp", "code": code}
    )
    assert "View report" in ok.text


async def test_view_without_verification_redirects(container, services, client, clean):
    token = await _notified_token(container, services)
    response = await client.get(f"/r/{HOSPITAL}/{token}/view")
    assert response.status_code == 303


async def test_lockout_after_failed_attempts(container, services, client, clean):
    token = await _notified_token(container, services)
    page = await client.get(f"/r/{HOSPITAL}/{token}")
    csrf = re.search(r'name="csrf" value="([^"]+)"', page.text).group(1)
    for _ in range(container.settings.reports.max_verification_attempts):
        await client.post(
            f"/r/{HOSPITAL}/{token}/verify",
            data={"csrf": csrf, "method": "dob", "dob": "2000-01-01"},
        )
    locked = await client.get(f"/r/{HOSPITAL}/{token}")
    assert locked.status_code == 423


async def test_invalid_token(client, clean):
    response = await client.get(f"/r/{HOSPITAL}/not-a-token")
    assert response.status_code == 404


async def test_opted_out_patient_gets_no_report_link(container, services, clean):
    async with container.db.tenant_session(HOSPITAL) as session:
        conversation = await get_or_create_conversation(session, HOSPITAL, PHONE)
        conversation.consent_status = "opted_out"
    await _drop_his_report(container)
    result = await services.his_sync.sync_reports(container.hospital(HOSPITAL))
    assert result == {"ingested": 1, "notified": 0}
