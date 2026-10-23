"""Patient report portal (the expiring link sent on WhatsApp).

Flow: open link → choose OTP or date of birth → verify → view the PDF through
a 5-minute signed URL. A signed, HttpOnly, SameSite=Strict cookie holds the
verified state for a few minutes. Every step is audited.
"""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Form, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from hcwave.api.deps import ServicesDep, client_ip
from hcwave.core.errors import PolicyViolationError
from hcwave.core.security import constant_time_equals, hmac_hex, sign_payload, verify_payload

_log = logging.getLogger(__name__)
router = APIRouter(prefix="/r", tags=["reports"], include_in_schema=False)
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))
_COOKIE = "hcw_report"


def _csrf(secret: str, token: str) -> str:
    return hmac_hex(secret, f"csrf:{token}")[:32]


def _page(
    request: Request,
    services: ServicesDep,
    hospital_id: str,
    token: str,
    *,
    status_code: int = 200,
    **context: object,
) -> HTMLResponse:
    hospital = services.container.settings.hospitals.get(hospital_id)
    cfg = services.container.settings.reports
    response = templates.TemplateResponse(
        request,
        "report_portal.html",
        {
            "hospital": hospital.name if hospital else "",
            "action_base": f"/r/{hospital_id}/{token}",
            "csrf": _csrf(services.container.settings.app.secret_key, token),
            "methods": cfg.verification_methods,
            **context,
        },
        status_code=status_code,
    )
    response.headers["Cache-Control"] = "no-store"
    return response


@router.get("/{hospital_id}/{token}", response_class=HTMLResponse)
async def open_link(
    hospital_id: str, token: str, request: Request, services: ServicesDep
) -> HTMLResponse:
    """Landing page: shows the verification form, or why the link is unusable."""
    if hospital_id not in services.container.settings.hospitals:
        return _page(request, services, hospital_id, token, state="invalid", status_code=404)
    async with services.container.db.tenant_session(hospital_id) as session:
        report = await services.reports.find_by_token(session, hospital_id, token)
        if report is None:
            return _page(request, services, hospital_id, token, state="invalid", status_code=404)
        await services.reports.log(
            session, report, "link_opened", client_ip(request), request.headers.get("user-agent")
        )
        if services.reports.is_locked(report):
            return _page(request, services, hospital_id, token, state="locked", status_code=423)
        return _page(request, services, hospital_id, token, state="verify", title=report.title)


@router.post("/{hospital_id}/{token}/otp", response_class=HTMLResponse)
async def request_otp(
    hospital_id: str,
    token: str,
    request: Request,
    services: ServicesDep,
    csrf: Annotated[str, Form()],
) -> HTMLResponse:
    """Sends an OTP to the patient's registered number."""
    secret = services.container.settings.app.secret_key
    hospital = services.container.settings.hospitals.get(hospital_id)
    if hospital is None or not constant_time_equals(csrf, _csrf(secret, token)):
        return _page(request, services, hospital_id, token, state="invalid", status_code=400)
    async with services.container.db.tenant_session(hospital_id) as session:
        report = await services.reports.find_by_token(session, hospital_id, token)
        if report is None:
            return _page(request, services, hospital_id, token, state="invalid", status_code=404)
        try:
            channel = await services.reports.send_otp(
                session, hospital, report, client_ip(request), request.headers.get("user-agent")
            )
        except PolicyViolationError:
            return _page(
                request,
                services,
                hospital_id,
                token,
                state="verify",
                title=report.title,
                error="otp_unavailable",
            )
        return _page(
            request,
            services,
            hospital_id,
            token,
            state="verify",
            title=report.title,
            otp_sent=channel,
        )


@router.post("/{hospital_id}/{token}/verify", response_model=None)
async def verify(
    hospital_id: str,
    token: str,
    request: Request,
    services: ServicesDep,
    csrf: Annotated[str, Form()],
    method: Annotated[str, Form()],
    code: Annotated[str, Form()] = "",
    dob: Annotated[str, Form()] = "",
) -> Response:
    """Verifies OTP or date of birth, then issues the short session cookie."""
    secret = services.container.settings.app.secret_key
    if hospital_id not in services.container.settings.hospitals or not constant_time_equals(
        csrf, _csrf(secret, token)
    ):
        return _page(request, services, hospital_id, token, state="invalid", status_code=400)
    ip, ua = client_ip(request), request.headers.get("user-agent")
    async with services.container.db.tenant_session(hospital_id) as session:
        report = await services.reports.find_by_token(session, hospital_id, token)
        if report is None:
            return _page(request, services, hospital_id, token, state="invalid", status_code=404)
        if method == "otp":
            ok = await services.reports.verify_otp(session, report, code, ip, ua)
        else:
            try:
                parsed = date.fromisoformat(dob)
            except ValueError:
                parsed = None
            ok = parsed is not None and await services.reports.verify_dob(
                session, report, parsed, ip, ua
            )
        if not ok:
            state = "locked" if services.reports.is_locked(report) else "verify"
            return _page(
                request,
                services,
                hospital_id,
                token,
                state=state,
                title=report.title,
                error="verify_failed",
            )
        minutes = services.container.settings.reports.portal_session_minutes
        cookie = sign_payload(secret, {"rid": str(report.id), "hid": hospital_id}, minutes * 60)
    response = _page(request, services, hospital_id, token, state="verified", title=report.title)
    response.set_cookie(
        _COOKIE,
        cookie,
        max_age=minutes * 60,
        httponly=True,
        secure=request.url.scheme == "https",
        samesite="strict",
        path=f"/r/{hospital_id}/{token}",
    )
    return response


@router.get("/{hospital_id}/{token}/view", response_model=None)
async def view(hospital_id: str, token: str, request: Request, services: ServicesDep) -> Response:
    """Redirects to a short-lived signed URL (or streams the PDF)."""
    claims = verify_payload(
        services.container.settings.app.secret_key, request.cookies.get(_COOKIE, "")
    )
    if not claims or claims.get("hid") != hospital_id:
        return RedirectResponse(f"/r/{hospital_id}/{token}", status_code=303)
    async with services.container.db.tenant_session(hospital_id) as session:
        report = await services.reports.find_by_token(session, hospital_id, token)
        if report is None or str(report.id) != claims.get("rid"):
            return _page(request, services, hospital_id, token, state="invalid", status_code=404)
        url, data = await services.reports.open(
            session, report, client_ip(request), request.headers.get("user-agent")
        )
    if url:
        return RedirectResponse(url, status_code=303, headers={"Cache-Control": "no-store"})
    return Response(
        data,
        media_type="application/pdf",
        headers={
            "Cache-Control": "no-store",
            "Content-Disposition": 'inline; filename="report.pdf"',
        },
    )
