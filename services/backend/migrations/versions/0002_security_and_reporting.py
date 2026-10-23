"""Row-level security, pgvector embeddings and read-only reporting views.

* RLS: every tenant table only shows rows whose ``hospital_id`` equals the
  transaction setting ``app.hospital_id`` (set by ``Database.tenant_session``).
  ``FORCE`` applies the policy to the table owner as well.
* pgvector: adds ``knowledge_chunks.embedding vector(N)`` when the extension
  is available (allow-list ``VECTOR`` in ``azure.extensions`` on Azure).
* Reporting views (``security_invoker``) for Power BI / Grafana. The optional
  ``hcwave_reporting`` role reads across hospitals; dashboards filter by
  hospital (Power BI row-level security on ``hospital_id``).

Revision ID: 0002
Revises: 0001
"""

import os
from collections.abc import Sequence

from alembic import op

from hcwave.db.models import TENANT_TABLES

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EMBEDDING_DIMENSIONS = int(os.environ.get("HCWAVE_EMBEDDING_DIMENSIONS", "1536"))

VIEWS = {
    "v_daily_bookings": """
        SELECT a.hospital_id, (a.created_at AT TIME ZONE 'Asia/Kolkata')::date AS day,
               a.channel, d.name AS department, count(*) AS bookings
        FROM appointments a JOIN departments d ON d.id = a.department_id
        WHERE a.visit_type = 'opd'
        GROUP BY 1, 2, 3, 4""",
    "v_appointment_outcomes": """
        SELECT hospital_id, (start_at AT TIME ZONE 'Asia/Kolkata')::date AS day,
               count(*) AS total,
               count(*) FILTER (WHERE confirmed_at IS NOT NULL) AS confirmed,
               count(*) FILTER (WHERE status = 'cancelled') AS cancelled,
               count(*) FILTER (WHERE status = 'no_show') AS no_show,
               count(*) FILTER (WHERE status = 'completed') AS completed
        FROM appointments WHERE visit_type = 'opd'
        GROUP BY 1, 2""",
    "v_report_turnaround": """
        SELECT hospital_id, (ready_at AT TIME ZONE 'Asia/Kolkata')::date AS day,
               count(*) AS ready,
               count(notified_at) AS notified,
               count(first_opened_at) AS opened,
               avg(extract(epoch FROM notified_at - ready_at) / 60) AS avg_minutes_to_notify
        FROM reports GROUP BY 1, 2""",
    "v_nps_daily": """
        SELECT hospital_id, (responded_at AT TIME ZONE 'Asia/Kolkata')::date AS day,
               count(*) AS responses,
               count(*) FILTER (WHERE nps_score >= 9) AS promoters,
               count(*) FILTER (WHERE nps_score <= 6) AS detractors,
               round(100.0 * (count(*) FILTER (WHERE nps_score >= 9)
                     - count(*) FILTER (WHERE nps_score <= 6)) / nullif(count(*), 0), 1) AS nps
        FROM feedback WHERE nps_score IS NOT NULL GROUP BY 1, 2""",
    "v_conversation_volume": """
        SELECT hospital_id, (created_at AT TIME ZONE 'Asia/Kolkata')::date AS day,
               count(*) FILTER (WHERE direction = 'inbound') AS inbound,
               count(*) FILTER (WHERE direction = 'outbound' AND sender = 'bot') AS bot_replies,
               count(*) FILTER (WHERE direction = 'outbound' AND sender = 'staff') AS staff_replies
        FROM messages GROUP BY 1, 2""",
    "v_ticket_stats": """
        SELECT hospital_id, (created_at AT TIME ZONE 'Asia/Kolkata')::date AS day, category,
               count(*) AS opened,
               count(resolved_at) AS resolved,
               avg(extract(epoch FROM resolved_at - created_at) / 3600) AS avg_hours_to_resolve
        FROM tickets GROUP BY 1, 2, 3""",
}


def upgrade() -> None:
    for table in TENANT_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} "
            "USING (hospital_id = current_setting('app.hospital_id', true)) "
            "WITH CHECK (hospital_id = current_setting('app.hospital_id', true))"
        )

    op.execute(
        f"""
        DO $$
        BEGIN
          IF EXISTS (SELECT 1 FROM pg_available_extensions WHERE name = 'vector') THEN
            CREATE EXTENSION IF NOT EXISTS vector;
            ALTER TABLE knowledge_chunks ADD COLUMN IF NOT EXISTS embedding vector({EMBEDDING_DIMENSIONS});
            CREATE INDEX IF NOT EXISTS ix_knowledge_chunks_embedding
              ON knowledge_chunks USING hnsw (embedding vector_cosine_ops);
          END IF;
        END $$;
        """
    )

    for name, query in VIEWS.items():
        op.execute(f"CREATE OR REPLACE VIEW {name} WITH (security_invoker = true) AS {query}")

    # Optional cross-hospital read-only role for BI tools (needs CREATEROLE).
    tables = ", ".join(TENANT_TABLES)
    views = ", ".join(VIEWS)
    op.execute(
        f"""
        DO $$
        BEGIN
          IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'hcwave_reporting') THEN
            CREATE ROLE hcwave_reporting NOLOGIN;
          END IF;
          GRANT SELECT ON {views} TO hcwave_reporting;
          GRANT SELECT ON {tables}, hospitals TO hcwave_reporting;
        EXCEPTION WHEN insufficient_privilege THEN
          RAISE NOTICE 'skipping hcwave_reporting role (insufficient privilege)';
        END $$;
        """
    )
    for table in TENANT_TABLES:
        op.execute(
            f"""
            DO $$
            BEGIN
              IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'hcwave_reporting') THEN
                CREATE POLICY reporting_read ON {table} FOR SELECT TO hcwave_reporting USING (true);
              END IF;
            END $$;
            """
        )


def downgrade() -> None:
    for name in VIEWS:
        op.execute(f"DROP VIEW IF EXISTS {name}")
    for table in TENANT_TABLES:
        op.execute(f"DROP POLICY IF EXISTS reporting_read ON {table}")
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
    op.execute("DROP INDEX IF EXISTS ix_knowledge_chunks_embedding")
    op.execute("ALTER TABLE knowledge_chunks DROP COLUMN IF EXISTS embedding")
