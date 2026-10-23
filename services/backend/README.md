# hcwave backend

Python 3.11+ service for the Hospital AI Wave 1 platform. One package, three
entry points:

| Command | Role |
|---|---|
| `hcwave-api` | FastAPI: public listener (webhooks, report portal, staff API) on :8000 and internal job API on :8001 |
| `hcwave-worker` | Consumes inbound WhatsApp events, delivery receipts and report events from the queue |
| `hcwave-jobs <job>` | Runs one scheduled job (reminders, feedback, briefing, his-*, maintenance) |
| `hcwave-knowledge` | Indexes hospital FAQ content into the knowledge store |

## Layout

```
src/hcwave/
  config/     YAML loader + typed schema (pydantic)
  core/       identity, logging (PII masking), telemetry, plugin registry, container
  db/         SQLAlchemy models, tenant-scoped sessions (row-level security)
  adapters/   messaging, queue, llm, knowledge, storage, email, sms, language,
              safety, his, dashboard – each with Azure + portable providers
  domain/     booking, reminders, reports, feedback/tickets, consent, dashboard,
              briefing, HIS sync – no cloud SDK imports
  agent/      LangGraph turn graph + deterministic WhatsApp flows
  api/        FastAPI apps and routes
  worker/     queue consumer
  jobs/       job runner + CLI
migrations/   Alembic (schema, RLS policies, pgvector, reporting views)
tests/        pytest suite (needs PostgreSQL; see conftest.py)
```

## Local development

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev,portable]"
export APP_ENV=dev DATABASE_URL=postgresql+asyncpg://hcwave:hcwave@localhost:5432/hcwave APP_SECRET_KEY=dev
alembic upgrade head
hcwave-knowledge          # index demo FAQ
hcwave-api                # http://localhost:8000/docs
```

Simulate a patient: `curl -XPOST localhost:8000/dev/simulate -H 'content-type: application/json' -d '{"text":"hi"}'`

## Tests and lint

```bash
TEST_DATABASE_URL=postgresql+asyncpg://postgres@localhost:5432/hcwave_test pytest
ruff check src tests migrations && ruff format --check src tests migrations
```

See `docs/` at the repository root for the full as-built architecture.
