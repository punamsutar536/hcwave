"""Management metrics (also exposed as SQL views for Power BI / Grafana).

Areas from the build guide: access, appointments, reports and experience.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from hcwave.core.clock import utcnow


def _ratio(numerator: float | None, denominator: float | None) -> float | None:
    if not denominator:
        return None
    return round((numerator or 0) / denominator, 3)


async def summary(
    session: AsyncSession, hospital_id: str, start: datetime, end: datetime | None = None
) -> dict[str, Any]:
    """Computes the dashboard KPIs for a period.

    Args:
        session: Tenant-scoped session.
        hospital_id: Tenant.
        start: Period start (UTC).
        end: Period end (UTC); defaults to now.

    Returns:
        A JSON-serialisable mapping grouped by dashboard area.
    """
    end = end or utcnow()
    params = {"hid": hospital_id, "start": start, "end": end}

    async def one(sql: str) -> Any:
        return (await session.execute(text(sql), params)).mappings().one()

    access = await one(
        """
        SELECT
          (SELECT count(*) FROM appointments WHERE hospital_id = :hid AND created_at >= :start
             AND created_at < :end AND visit_type = 'opd') AS bookings_total,
          (SELECT count(*) FROM appointments WHERE hospital_id = :hid AND created_at >= :start
             AND created_at < :end AND channel = 'whatsapp') AS bookings_whatsapp,
          (SELECT count(DISTINCT conversation_id) FROM messages WHERE hospital_id = :hid
             AND direction = 'inbound' AND created_at >= :start AND created_at < :end) AS conversations,
          (SELECT count(DISTINCT conversation_id) FROM messages WHERE hospital_id = :hid
             AND sender = 'staff' AND created_at >= :start AND created_at < :end) AS human_conversations,
          (SELECT count(*) FROM messages WHERE hospital_id = :hid AND direction = 'inbound'
             AND created_at >= :start AND created_at < :end) AS inbound_messages,
          (SELECT avg(extract(epoch FROM r.replied_at - m.created_at))
             FROM messages m
             CROSS JOIN LATERAL (
               SELECT min(o.created_at) AS replied_at FROM messages o
               WHERE o.conversation_id = m.conversation_id AND o.direction = 'outbound'
                 AND o.created_at >= m.created_at) r
             WHERE m.hospital_id = :hid AND m.direction = 'inbound'
               AND m.created_at >= :start AND m.created_at < :end) AS avg_response_seconds
        """
    )
    appointments = await one(
        """
        SELECT count(*) AS total,
               count(*) FILTER (WHERE confirmed_at IS NOT NULL) AS confirmed,
               count(*) FILTER (WHERE status = 'cancelled') AS cancelled,
               count(*) FILTER (WHERE status = 'no_show') AS no_show,
               count(*) FILTER (WHERE status = 'completed') AS completed
        FROM appointments
        WHERE hospital_id = :hid AND visit_type = 'opd' AND start_at >= :start AND start_at < :end
        """
    )
    reports = await one(
        """
        SELECT count(*) AS ready, count(notified_at) AS notified, count(first_opened_at) AS opened,
               avg(extract(epoch FROM notified_at - ready_at) / 60) AS avg_minutes_to_notify
        FROM reports WHERE hospital_id = :hid AND ready_at >= :start AND ready_at < :end
        """
    )
    experience = await one(
        """
        SELECT count(nps_score) AS responses,
               count(*) FILTER (WHERE nps_score >= 9) AS promoters,
               count(*) FILTER (WHERE nps_score <= 6) AS detractors,
               (SELECT count(*) FROM tickets WHERE hospital_id = :hid
                  AND status IN ('open', 'in_progress', 'escalated')) AS open_tickets,
               (SELECT avg(extract(epoch FROM resolved_at - created_at) / 3600) FROM tickets
                  WHERE hospital_id = :hid AND resolved_at >= :start AND resolved_at < :end) AS avg_ticket_hours
        FROM feedback WHERE hospital_id = :hid AND responded_at >= :start AND responded_at < :end
        """
    )
    categories = (
        (
            await session.execute(
                text(
                    "SELECT category, count(*) AS n FROM tickets WHERE hospital_id = :hid "
                    "AND created_at >= :start AND created_at < :end GROUP BY category ORDER BY n DESC LIMIT 5"
                ),
                params,
            )
        )
        .mappings()
        .all()
    )

    responses = experience["responses"] or 0
    nps = (
        round(
            100 * ((experience["promoters"] or 0) - (experience["detractors"] or 0)) / responses, 1
        )
        if responses
        else None
    )
    conversations = access["conversations"] or 0
    return {
        "period": {"start": start.isoformat(), "end": end.isoformat()},
        "access": {
            "bookings_total": access["bookings_total"],
            "bookings_whatsapp": access["bookings_whatsapp"],
            "conversations": conversations,
            "inbound_messages": access["inbound_messages"],
            "bot_handled_share": _ratio(
                conversations - (access["human_conversations"] or 0), conversations
            ),
            "avg_response_seconds": round(float(access["avg_response_seconds"]), 1)
            if access["avg_response_seconds"] is not None
            else None,
        },
        "appointments": {
            **dict(appointments),
            "confirmation_rate": _ratio(appointments["confirmed"], appointments["total"]),
            "no_show_rate": _ratio(appointments["no_show"], appointments["total"]),
        },
        "reports": {
            "ready": reports["ready"],
            "notified": reports["notified"],
            "opened": reports["opened"],
            "open_rate": _ratio(reports["opened"], reports["notified"]),
            "avg_minutes_to_notify": round(float(reports["avg_minutes_to_notify"]), 1)
            if reports["avg_minutes_to_notify"] is not None
            else None,
        },
        "experience": {
            "responses": responses,
            "nps": nps,
            "detractors": experience["detractors"],
            "open_tickets": experience["open_tickets"],
            "avg_ticket_hours": round(float(experience["avg_ticket_hours"]), 1)
            if experience["avg_ticket_hours"] is not None
            else None,
            "top_complaint_categories": [dict(row) for row in categories],
        },
    }


async def summary_for_days(session: AsyncSession, hospital_id: str, days: int) -> dict[str, Any]:
    """Convenience wrapper: the last ``days`` days."""
    return await summary(session, hospital_id, utcnow() - timedelta(days=days))
