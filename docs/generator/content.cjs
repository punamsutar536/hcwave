/**
 * Content of the as-built document, kept separate from layout code.
 *
 * Block types understood by build.cjs:
 *   h1/h2/h3 · p · bullets · steps · table · image · code · note · pagebreak
 */
"use strict";

const T = (headers, rows, widths) => ({ type: "table", headers, rows, widths });
const P = (text) => ({ type: "p", text });
const B = (items) => ({ type: "bullets", items });
const S = (items) => ({ type: "steps", items });
const H1 = (text) => ({ type: "h1", text });
const H2 = (text) => ({ type: "h2", text });
const H3 = (text) => ({ type: "h3", text });
const IMG = (name, caption) => ({ type: "image", name, caption });
const CODE = (text) => ({ type: "code", text });
const NOTE = (text) => ({ type: "note", text });

const sections = [
  // ------------------------------------------------------------------------ //
  H1("1. Executive summary"),
  P("This document records the as-built solution architecture of the Hospital AI – Wave 1 platform and explains how to run it on a laptop, on any Kubernetes cluster and on Microsoft Azure. It translates the Wave 1 build guide (five patient-engagement modules on one shared foundation) onto the Azure service stack selected for the programme: Azure Communication Services for WhatsApp, Event Grid and Service Bus for inbound events, AKS for compute, Logic Apps Standard and Durable Functions for workflows, Azure OpenAI in Microsoft Foundry for language understanding, Azure AI Search for retrieval, Azure AI Content Safety for guardrails and PostgreSQL Flexible Server as the system of record."),
  P("The five Wave 1 products are delivered as one platform that shares the same WhatsApp number, database and patient records:"),
  B([
    "WhatsApp patient assistant – booking, rescheduling and cancellation through interactive buttons and lists, doctor availability, FAQ answers from the hospital's own content in Malayalam, English and Hindi, emergency detection and human handover.",
    "Reminders – 24-hour (Confirm / Reschedule / Cancel), 2–3-hour preparation, missed-appointment and follow-up reminders, sent once per appointment even when jobs re-run.",
    "Report delivery – no PDFs in chat; an expiring link verified by OTP or date of birth opens the report through a 5-minute signed URL, with every access audited.",
    "Feedback and reputation – 0–10 score plus one open question, AI tagging of sentiment and category, automatic service-recovery tickets with WhatsApp and email alerts, SLA escalation and a Google review invitation for every patient (no review gating).",
    "Management dashboard – KPIs for access, appointments, reports and experience (Power BI Embedded, Azure Managed Grafana or built-in tiles) and a five-line daily briefing on WhatsApp and email.",
  ]),
  P("Design principles applied throughout:"),
  B([
    "Configurable: every behaviour, provider, timer, template and string lives in YAML; secrets come only from environment variables (a local .env file, or Azure Key Vault through the CSI driver).",
    "Secure and private by default: private endpoints, managed identities and Entra ID everywhere, no keys in code, WAF at the edge, row-level security between hospitals, PII-masked logs.",
    "Portable: domain logic depends on ports, not cloud SDKs. The messaging channel, queue, LLM, knowledge store, object storage, email, SMS, language detection, safety, HIS, dashboard and scheduler each switch with one YAML line; the Helm chart runs on AKS, EKS, GKE or on-premises.",
    "Infrastructure as code: one subscription-scope Bicep deployment creates a complete environment; the Helm chart deploys the application; GitHub Actions or Azure DevOps automate both.",
    "Readable code: Python follows the Google style guide (docstrings, naming, 100-column formatting enforced by ruff).",
  ]),
  T(
    ["Item", "As-built value"],
    [
      ["Repository", "tanajis/hcwave (branch claude/vigilant-dijkstra-y26hb4)"],
      ["Primary region", "Azure Central India (AI models: South India by default, configurable)"],
      ["Application runtime", "Python 3.12 (FastAPI, LangGraph, LangChain), React 18 staff app, Azure Functions (Python)"],
      ["Data store", "PostgreSQL 16 Flexible Server with row-level security and optional pgvector"],
      ["Deployment units", "3 container roles from one backend image (API, worker, jobs) + staff UI image; Logic Apps and Function App packages"],
      ["IaC", "Bicep (main.bicep + 29 modules, subscription scope) + Helm chart (Gateway API or Ingress, KEDA, network policies)"],
      ["Verification", "48 automated tests on PostgreSQL, lint-clean, Bicep and Helm validated, images built and run hardened (section 15)"],
    ],
    [2600, 6426],
  ),

  // ------------------------------------------------------------------------ //
  H1("2. Scope and requirement traceability"),
  P("The table maps each requirement from the build guide and the Azure technology brief to where it is implemented."),
  T(
    ["Requirement", "Implementation (as built)"],
    [
      ["One platform, shared WhatsApp number, database and patient records", "Single backend package; tenants in config/hospitals/*.yaml; patients, conversations and messages shared by all modules"],
      ["Opt-in recorded with time and source; STOP works instantly", "domain/consent.py – consent_events table, first-message or registration opt-in, STOP/START keywords handled before any other step"],
      ["24-hour session window; templates for anything the platform starts", "domain/messenger.py enforces the window; reminders, reports, OTPs, feedback and alerts use templates from config/messaging/templates.yaml"],
      ["Interactive messages first; LLM only for free text and FAQs", "agent/flows.py (buttons/lists for booking, manage, availability, feedback); agent/graph.py calls the LLM only for intent and FAQ"],
      ["Malayalam, English, Hindi", "config/locales/{ml,en,hi}.yaml, Unicode-script detection + Azure AI Translator, intent model returns language for romanised text"],
      ["Never give medical advice; emergency keywords; low confidence to a human", "Emergency node before any AI call (reply in the keyword's language), medical-question intent → fixed refusal, low confidence or ungrounded FAQ → handover queue"],
      ["Human handover / takeover screen (ACS has no inbox)", "Staff app Inbox + /staff/conversations API: take over, reply (window-aware), hand back to bot; emergencies sorted first"],
      ["Reminders 24 h / 2–3 h / missed / follow-up; cancellations free the slot", "domain/reminders.py rules in YAML; idempotent via notification_logs; cancel button frees capacity immediately"],
      ["Reports via verified, expiring link; audit; minors/family rule", "domain/reports.py + /r portal; OTP (WhatsApp auth template, SMS fallback) or DOB; 5-min user-delegation SAS; report_access_logs; recipients limited to registered contacts"],
      ["Feedback 2–4 h after OPD / 1 day after discharge; tickets; alerts; reviews without gating", "domain/feedback.py; Durable Functions or jobs for timing; tickets + WhatsApp/email alerts + SLA escalation; review invite to every patient"],
      ["Dashboard (access, appointments, reports, experience) and daily briefing", "domain/dashboard.py, SQL reporting views (migration 0002), Power BI/Grafana/built-in, domain/briefing.py"],
      ["HIS integration in order of preference", "adapters/his: rest_api, fhir, csv (Data Factory drops) – per-hospital override"],
      ["Security checklist (DPDP, India hosting, RBAC, audit, no training on data, DLT)", "Section 9 and the go-live checklist in section 13"],
    ],
    [3300, 5726],
  ),

  // ------------------------------------------------------------------------ //
  H1("3. Solution architecture"),
  P("Patients talk to the hospital on WhatsApp through Azure Communication Services. Inbound messages and delivery receipts flow through Event Grid into Service Bus queues and are processed by the worker, which runs the LangGraph assistant. Staff use the React staff app through Front Door and Application Gateway for Containers (both with WAF). Scheduled work is triggered by Logic Apps Standard (or Kubernetes CronJobs on other clouds) and Durable Functions; all of it calls the same Python job code on a private listener."),
  IMG("01-solution-architecture", "Figure 1 – As-built solution architecture on Azure"),
  H2("3.1 Technology mapping"),
  T(
    ["Area", "Azure service (as built)", "Where in the repository", "Switch / alternative"],
    [
      ["WhatsApp channel", "ACS Advanced Messaging for WhatsApp (templates, text, media, interactive buttons and lists)", "adapters/messaging/acs_whatsapp.py", "messaging.provider: meta_cloud | console | module:Class"],
      ["Inbound events", "Event Grid system topic → Service Bus Premium queues", "infra/bicep/modules/acs.bicep, servicebus.bicep; worker/", "queue.provider: redis | in_memory"],
      ["Compute", "AKS (Azure CNI Overlay, Cilium, workload identity)", "deploy/helm/hcwave", "Any Kubernetes; Container Apps possible"],
      ["Workflow engine", "Logic Apps Standard (recurrence workflows)", "workflows/logic-apps", "scheduler.engine: k8s_cronjob"],
      ["Multi-step waits", "Durable Functions (Python)", "services/functions", "scheduler.feedback_engine: jobs"],
      ["LLM", "Azure OpenAI in Foundry – gpt-5-mini (intent, tagging), gpt-5 (replies), text-embedding-3-large", "adapters/llm/providers.py", "anthropic_foundry (Claude), openai_compatible"],
      ["Knowledge (RAG)", "Azure AI Search – hybrid vector + keyword, semantic ranker", "adapters/knowledge/azure_ai_search.py", "pgvector | keyword"],
      ["AI guardrails", "Azure AI Content Safety + Prompt Shields", "adapters/safety/azure_content_safety.py", "safety.provider: none (dev only)"],
      ["Language", "Azure AI Translator (detect) + script heuristic", "adapters/language/", "heuristic"],
      ["Database", "PostgreSQL 16 Flexible Server (Entra auth, private, HA in prod)", "db/, migrations/", "Any managed PostgreSQL"],
      ["Report files", "Blob Storage – private, shared keys off, user-delegation SAS", "adapters/storage/azure_blob.py", "s3 (AWS/MinIO) | local"],
      ["Patient OTP", "WhatsApp authentication template + ACS SMS fallback", "domain/reports.py, adapters/sms/", "sms.provider: msg91 (DLT)"],
      ["Email alerts", "ACS Email (Azure-managed or custom domain)", "adapters/email/acs_email.py", "smtp"],
      ["Dashboard", "Power BI Embedded (RLS per hospital) / Managed Grafana", "adapters/dashboard/", "builtin tiles"],
      ["Staff login", "Microsoft Entra ID (app roles, hospital claim)", "api/auth.py, staff-ui/src/auth.ts", "auth.provider: oidc"],
      ["Secrets and identity", "Key Vault (RBAC) + managed identities / Workload ID", "keyvault.bicep, identity.bicep, Helm secrets.yaml", "secrets.provider: kubernetes | existing"],
      ["Front door and security", "App Gateway for Containers + WAF; Front Door Premium + WAF", "agc.bicep, frontdoor.bicep, Helm routing.yaml", "ingress.mode: ingress (NGINX)"],
      ["AI gateway (optional)", "API Management – token limits, metrics per hospital", "apim.bicep", "enableApim"],
      ["Networking", "VNet, private endpoints, private DNS", "network.bicep, private-dns.bicep", "—"],
      ["Monitoring and LLM tracing", "Azure Monitor, Application Insights, Log Analytics; GenAI spans for Foundry tracing", "core/telemetry.py, monitoring.bicep", "telemetry.exporter: otlp"],
      ["Registry, CI/CD", "ACR; GitHub Actions or Azure DevOps", ".github/workflows, azure-pipelines.yml", "Any OCI registry"],
      ["IaC", "Bicep", "infra/bicep", "—"],
      ["Backup", "Azure Backup vault (AKS, blobs) + Postgres automated backups", "backup.bicep, postgres.bicep", "—"],
      ["Security and compliance", "Defender for Cloud, Azure Policy, Purview", "security.bicep, optional-services.bicep", "enableDefender / enablePolicy / enablePurview"],
      ["HIS integration", "Data Factory (CSV/DB pulls); Health Data Services FHIR later", "adapters/his/, optional-services.bicep", "his.provider: rest_api | fhir | csv | none"],
      ["DNS", "Azure DNS for branded links", "dns.bicep", "Any DNS"],
    ],
    [1500, 2700, 2500, 2326],
  ),
  H2("3.2 Runtime components"),
  T(
    ["Component", "Process / location", "Responsibility"],
    [
      ["API (public)", "hcwave-api, port 8000, behind AGC/Front Door", "Provider webhooks (Meta, Event Grid), report portal, staff API, health probes"],
      ["API (internal)", "same process, port 8001, internal load balancer only", "Job triggers for Logic Apps, Durable Functions activities, HIS consent events"],
      ["Worker", "hcwave-worker, scaled by KEDA on queue length", "Inbound messages (LangGraph assistant), delivery receipts, report-file events"],
      ["Jobs", "hcwave-jobs <name> (CronJob) or via internal API", "reminders, feedback, tickets-escalate, briefing, his-doctors, his-visits, his-reports, maintenance, knowledge-reindex"],
      ["Staff app", "nginx (unprivileged) serving React build", "WhatsApp takeover inbox, complaints, dashboard, front desk (appointments, consent capture)"],
      ["Logic Apps Standard", "WS1 plan, VNet integrated", "Eight recurrence workflows calling the internal job API with a managed identity"],
      ["Durable Functions", "Elastic Premium, private endpoint + Entra auth", "Feedback orchestration per visit: wait → send → wait for reply → close"],
      ["Migrations / indexing", "Helm hook jobs", "Alembic upgrade before each release; FAQ re-index after each release"],
    ],
    [1800, 3000, 4226],
  ),
  H2("3.3 Repository structure"),
  CODE(`hcwave/
├── config/                  YAML: app, environments, hospitals, templates, locales, prompts, FAQ
├── services/
│   ├── backend/             Python package "hcwave" (API, worker, jobs, agent)
│   │   ├── src/hcwave/      config, core, db, adapters, domain, agent, api, worker, jobs
│   │   ├── migrations/      Alembic: schema, row-level security, pgvector, views
│   │   └── tests/           pytest suite against PostgreSQL
│   ├── staff-ui/            React + Vite staff app (MSAL), nginx image
│   └── functions/           Azure Durable Functions (feedback orchestration)
├── workflows/logic-apps/    Logic Apps Standard workflow definitions
├── infra/bicep/             main.bicep, modules/, parameters/*.bicepparam
├── deploy/helm/hcwave/      Helm chart and values overlays
├── deploy/local/            Postgres/pgvector, Redis, MinIO for local Kubernetes
├── scripts/                 deploy-infra, entra-apps, addons, db-bootstrap, deploy-app ...
├── docs/                    this document, diagrams and their generator
├── docker-compose.yml       laptop stack (offline)
├── .env.example             every environment variable, documented
└── Makefile, .github/workflows/, azure-pipelines.yml`),

  // ------------------------------------------------------------------------ //
  H1("4. Key flows"),
  H2("4.1 Inbound WhatsApp message"),
  IMG("03-inbound-message-flow", "Figure 2 – Inbound message processing"),
  B([
    "Routing: the receiving channel ID (ACS channel registration ID or Meta phone number ID) identifies the hospital; every database statement runs in a tenant-scoped transaction.",
    "Ordering and idempotency: the conversation row is locked (SELECT … FOR UPDATE) so a patient's messages are handled one at a time across worker replicas; duplicate deliveries are skipped by provider message ID.",
    "Delivery receipts update message status forward-only (sent → delivered → read; failed overrides).",
    "While staff own a conversation the bot is silent, except that STOP and emergency keywords are still honoured.",
  ]),
  H2("4.2 Booking, rescheduling and cancellation"),
  P("Department → doctor → date → slot → patient (self, family member or new) → name and date of birth for new patients → confirm. Slots come from HIS weekly schedules (slot length and capacity) minus leave days and existing bookings; booking re-checks availability under a row lock on the doctor so the last place in a slot can never be double-booked. Patients can answer lists with the option number or title, which also makes the text-menu fallback work on channels without interactive messages. Reminder and manage buttons carry the appointment ID and are accepted only from a phone registered to that patient."),
  H2("4.3 Reminders"),
  T(
    ["Rule (config id)", "Trigger", "Template", "Notes"],
    [
      ["day_before", "24 h before (2 h window)", "hcw_appointment_reminder", "Confirm / Reschedule / Cancel quick replies; cancel frees the slot"],
      ["prep", "3 h before (1 h window)", "hcw_appointment_prep", "What to bring, fasting, arrive early"],
      ["missed", "2 h after a no-show (8 h window)", "hcw_missed_appointment", "Rebook button"],
      ["follow_up", "Day before the doctor's follow-up date", "hcw_follow_up_due", "Skipped if a newer booking with the doctor exists"],
    ],
    [1700, 2300, 2300, 2726],
  ),
  P("Rules, offsets, windows and templates are YAML (reminders.rules). The window lets delayed runs still send without ever sending late reminders indefinitely; notification_logs guarantees one send per rule and appointment. Track confirmation and no-show rates before and after launch – the first ROI number for the pilot."),
  H2("4.4 Report delivery"),
  IMG("05-report-delivery", "Figure 3 – Secure report delivery"),
  B([
    "Link token: 256-bit random, only its SHA-256 hash is stored; link lifetime 48 h (reports.link_ttl_hours, policy 24–72 h).",
    "Verification: OTP (6 digits, 10 minutes, HMAC-hashed, max 5 attempts, 3 requests per 10 minutes) or date of birth; 5 failed verifications lock the link for 30 minutes.",
    "Session: a signed, HttpOnly, SameSite=Strict cookie scoped to the link path for 10 minutes; CSRF token on every form.",
    "Download: 5-minute read-only user-delegation SAS (storage shared keys are disabled); stores without signed URLs stream through the API.",
    "Audit: notified, link_opened, otp_sent_*, verify_*, locked and downloaded events in report_access_logs. AI never summarises or interprets results.",
  ]),
  H2("4.5 Feedback and service recovery"),
  P("A completed OPD visit (or discharge) starts the feedback workflow: Durable Functions wait for the configured delay (3 h OPD, 24 h discharge), ask the backend to send the feedback template, wait for the reply timeout and then close the request. Without Durable Functions the feedback job polls for due visits every 15 minutes. The patient replies with 0–10, then one comment (or 'skip'); the tagger model returns sentiment and categories (waiting time, billing, staff behaviour, cleanliness, doctor communication, other). A score at or below the detractor threshold (6) or a negative comment opens a ticket due within the SLA (4 h), alerts patient relations on WhatsApp and email, and escalates to the unit head if unresolved after 8 h. Every patient then receives the Google review invitation – Google prohibits review gating, so complaints are handled in parallel."),
  H2("4.6 Daily briefing and dashboard"),
  P("At 08:00 IST the briefing workflow computes yesterday's figures for each hospital and sends five lines to the unit heads on WhatsApp (template) and email: bookings (WhatsApp share), no-show rate, reports sent/opened, NPS with open complaints, and the share of conversations handled by the assistant. The same metrics drive the dashboard (section 8.3)."),
  H2("4.7 HIS integration"),
  T(
    ["Option (preference order)", "Connector", "How it works"],
    [
      ["HIS vendor API", "rest_api", "Endpoints and field mappings in YAML (dotted JSON paths); optional push of WhatsApp bookings back to the HIS"],
      ["FHIR (Azure Health Data Services)", "fhir", "PractitionerRole/Practitioner → doctors, Encounter → visits, DiagnosticReport (final, PDF) → reports; Entra ID auth"],
      ["Scheduled exports", "csv", "Data Factory (or SFTP/script) writes doctors.csv, schedules.csv, leaves.csv, visits.csv, reports.csv and PDFs to his-imports/<hospital>/; column names remappable"],
    ],
    [2600, 1400, 5026],
  ),
  P("Pulls are incremental (sync_states watermarks with a 24-hour overlap) and idempotent (external IDs). A new PDF dropped in the imports container also triggers an immediate report sync through Event Grid. For the first pilot a daily export is enough – integration should not block launch."),

  // ------------------------------------------------------------------------ //
  H1("5. Conversational AI design"),
  IMG("04-assistant-graph", "Figure 4 – Assistant turn graph (LangGraph)"),
  H2("5.1 Model profiles"),
  T(
    ["Profile", "Default deployment", "Used for", "Output"],
    [
      ["intent", "gpt-5-mini", "Intent, language of romanised text, entities", "IntentResult (structured output)"],
      ["reply", "gpt-5", "Grounded FAQ answers from retrieved passages", "FaqAnswer {answer, confident, source_ids}"],
      ["tagger", "gpt-5-mini", "Feedback sentiment and categories", "FeedbackTags"],
      ["embedding", "text-embedding-3-large (1536 dims)", "Knowledge indexing and queries", "vectors"],
    ],
    [1300, 2400, 3100, 2226],
  ),
  P("Profiles name a provider and model, so moving intent detection to Claude Haiku in Foundry, or to a self-hosted model on another cloud, is a YAML change. Temperature is left unset by default (reasoning models such as GPT-5 only accept the default). Through APIM the same client points at the gateway URL with a subscription key, and APIM authenticates to Azure OpenAI with its managed identity."),
  H2("5.2 Retrieval (RAG)"),
  P("Each hospital's approved FAQ and policy content (config/knowledge/<hospital>/*.yaml) is indexed by hcwave-knowledge (also run automatically after every Helm release). Azure AI Search runs hybrid keyword + vector queries with the semantic ranker, filtered by hospital_id; pgvector and PostgreSQL full-text are portable alternatives. Only passages above knowledge.min_score reach the model, and the model must mark its answer as confident – otherwise the conversation goes to staff."),
  H2("5.3 Guardrails"),
  B([
    "Scope: the bot is strictly limited to hospital tasks (Meta restricts general-purpose AI chatbots on the Business API); out-of-scope questions get a fixed reply.",
    "Medical safety: prompts forbid medical advice, diagnosis, medication guidance and result interpretation; the intent model routes medical questions to a fixed refusal with a booking offer.",
    "Emergencies: keyword lists per language (including Malayalam and Hindi terms and romanised forms) are checked before any AI call; the reply gives 108 and casualty directions in the matched language and queues the chat for staff.",
    "Content Safety: harm categories at severity ≥ 4 and Prompt Shields jailbreak detection block the message; self-harm signals trigger a crisis helpline reply (Tele-MANAS 14416) and handover. If the service is unavailable the default is fail-closed (handover).",
    "Privacy: prompts and completions are not stored in traces unless telemetry.capture_llm_content is enabled; APIM diagnostics log no bodies; enterprise API terms mean no training on patient data.",
  ]),
  H2("5.4 Languages"),
  P("Native-script Malayalam and Devanagari are detected from Unicode ranges; Latin-script text is checked by Azure AI Translator and refined by the intent model (romanised Malayalam and Hindi). All bot strings live in config/locales; the Malayalam and Hindi files must be reviewed by native speakers before go-live, as must every WhatsApp template."),

  // ------------------------------------------------------------------------ //
  H1("6. Data architecture"),
  T(
    ["Table", "Purpose"],
    [
      ["hospitals", "Tenants (synced from config at start-up)"],
      ["departments, doctors, doctor_schedules, schedule_exceptions", "Reference data from the HIS; weekly sessions with slot length and capacity; leave days"],
      ["patients, patient_contacts", "Patient identity (MRN, DOB, consent flags) and the phones allowed to act for them (minors/family rule)"],
      ["consent_events", "Immutable opt-in/opt-out evidence (source, channel, evidence text, timestamp)"],
      ["appointments", "Bookings and visits (status, channel, follow-up date, checkout, confirm/cancel timestamps)"],
      ["conversations, messages", "One conversation per phone per hospital (status, flow state, consent, 24-hour window); every inbound/outbound message with status for audit"],
      ["reports, otp_challenges, report_access_logs", "Report metadata and link token hash, OTP hashes, access audit"],
      ["feedback, tickets", "NPS, comment, tags; service-recovery tickets with SLA and escalation"],
      ["staff_users, audit_logs", "Just-in-time provisioned staff; who did what and when"],
      ["notification_logs, sync_states", "Idempotency of proactive messages; HIS sync watermarks"],
      ["knowledge_chunks", "FAQ chunks for pgvector/keyword providers (embedding column added when pgvector exists)"],
    ],
    [3300, 5726],
  ),
  H2("6.1 Multi-tenancy and row-level security"),
  P("Every tenant table carries hospital_id and has a FORCE ROW LEVEL SECURITY policy that only exposes rows whose hospital_id equals the transaction setting app.hospital_id. The application sets it at the start of every unit of work (Database.tenant_session), so even a faulty query cannot read another hospital's data. An automated test connects as a non-superuser role and proves isolation. The optional hcwave_reporting role reads across hospitals for BI; Power BI then applies row-level security on hospital_id."),
  H2("6.2 Reporting views"),
  P("Migration 0002 creates security-invoker views for dashboards: v_daily_bookings, v_appointment_outcomes, v_report_turnaround, v_nps_daily, v_conversation_volume and v_ticket_stats."),
  H2("6.3 Retention and backup"),
  B([
    "PostgreSQL: automated backups with 35-day point-in-time restore; geo-redundant backups and zone-redundant HA in production.",
    "Reports: versioning, 30-day soft delete, cool tier after 30 days, deletion after the configured retention (default 1,825 days – align with the hospital's record policy); HIS imports deleted after 90 days.",
    "AKS: daily backups through Azure Backup (cluster extension installed by install-cluster-addons.sh --with-backup).",
    "Logs: 90 days in Log Analytics by default (monitoring.bicep retentionInDays).",
  ]),

  // ------------------------------------------------------------------------ //
  H1("7. Configuration model"),
  P("Configuration is layered YAML, validated at start-up by Pydantic models (unknown keys fail fast):"),
  S([
    "config/app.yaml – base defaults for every environment.",
    "config/environments/<APP_ENV>.yaml – dev (offline laptop), test, staging or prod.",
    "$HCWAVE_CONFIG_OVERLAY_DIR/*.yaml – deployment overlay rendered by Helm from values.appConfig and values.hospitals (no image rebuild to change behaviour).",
    "config/hospitals/*.yaml, config/messaging/templates.yaml, config/locales/*.yaml, config/prompts/*.yaml – tenants, WhatsApp templates, bot strings and prompts.",
  ]),
  P("Values may reference environment variables as ${VAR} or ${VAR:-default}. Secrets therefore never appear in YAML. Locally they come from .env (template: .env.example, every variable documented); in AKS from Key Vault through the Secrets Store CSI driver, synced into a Kubernetes Secret and injected as environment variables. Most Azure services need no secret at all because pods use workload identity."),
  H2("7.1 The adapter pattern"),
  CODE(`messaging:
  provider: acs_whatsapp          # or meta_cloud | console | my_pkg.telegram:TelegramProvider
  providers:
    acs_whatsapp:
      endpoint: \${ACS_ENDPOINT}
      access_key: \${ACS_ACCESS_KEY:-}     # empty = Entra ID (recommended)
      api_version: "2025-01-15-preview"   # interactive buttons and lists
    meta_cloud:
      access_token: \${META_ACCESS_TOKEN:-}`),
  IMG("06-ports-and-adapters", "Figure 5 – Ports and adapters"),
  H2("7.2 Common configuration tasks"),
  T(
    ["Task", "What to change"],
    [
      ["Onboard a hospital", "Copy config/hospitals/demo-hospital.yaml (id, channel_ids, languages, emergency keywords and message, contacts, review link, FAQ files) or add it under hospitals: in Helm values; run the knowledge-reindex job"],
      ["Change reminder timing or add a rule", "reminders.rules (offset_minutes, window_minutes, template); add the template to templates.yaml"],
      ["Rename an approved template", "templates.<logical>.name and languages map – code is unchanged"],
      ["Add a language", "config/locales/<code>.yaml, add the code to language.supported and the hospital's languages, add template language codes and emergency keywords"],
      ["Swap the LLM", "llm.profiles.<profile>.provider/model (e.g. anthropic_foundry with claude-haiku-5-5) – or LLM_*_PROVIDER/LLM_*_MODEL env vars"],
      ["Feedback timings and thresholds", "feedback.* (delays, window, timeout, detractor_threshold, SLA, escalation)"],
      ["Report link policy", "reports.link_ttl_hours, verification_methods, otp.*, lockout"],
      ["Disable a module for a hospital", "hospitals.<id>.features.{assistant,booking,reminders,reports,feedback,dashboard,briefing}"],
    ],
    [2800, 6226],
  ),
  H2("7.3 Adding a new messaging channel"),
  S([
    "Create a class extending adapters.messaging.base.MessagingProvider with a settings_model (Pydantic) for its settings.",
    "Implement send(channel_id, to, message) – translate OutboundMessage kinds (text, buttons, list, template, media) to the channel's API; use render_text_menu() if it has no interactive messages.",
    "Implement parse_events(payload) to return InboundEvent objects (message with reply_id for button/list replies, or delivery status); implement verify_webhook() and webhook_challenge() if it pushes over HTTP.",
    "Register it in core/registry.py (or reference it as module:Class) and set messaging.provider plus its providers.<name> settings.",
    "Point the channel's webhook at POST /webhooks/<provider-name> (events are verified and queued), map its channel IDs in each hospital's channel_ids, and map template names in templates.yaml.",
  ]),

  // ------------------------------------------------------------------------ //
  H1("8. Interfaces"),
  H2("8.1 Public API (port 8000, behind WAF)"),
  T(
    ["Endpoint", "Auth", "Purpose"],
    [
      ["GET /healthz, /readyz", "none", "Liveness; readiness checks the database"],
      ["GET|POST /webhooks/{provider}", "provider signature", "Webhook handshake and delivery (e.g. Meta X-Hub-Signature-256); payload queued"],
      ["POST /webhooks/eventgrid?key=…", "shared key", "Event Grid webhook delivery (alternative to Service Bus delivery)"],
      ["GET /r/{hospital}/{token}", "link token", "Report portal; POST …/otp, POST …/verify, GET …/view"],
      ["GET /staff/me", "Entra ID", "Signed-in user, roles, hospitals"],
      ["GET /staff/conversations?state=waiting|mine|all", "FrontOffice, PatientRelations", "Takeover queue (emergencies first)"],
      ["GET …/{id}/messages · POST …/takeover · …/reply · …/release", "FrontOffice, PatientRelations", "Conversation history and takeover actions (reply rejected outside 24 h)"],
      ["GET /staff/tickets · PATCH /staff/tickets/{id}", "PatientRelations", "Service-recovery tickets"],
      ["GET /staff/appointments?day= · POST /staff/consent", "FrontOffice", "Front desk list; consent captured at registration"],
      ["GET /staff/dashboard/summary?days= · /embed", "UnitHead, PatientRelations", "KPI tiles; Power BI/Grafana embed configuration"],
      ["POST /dev/simulate", "dev profile only", "Inject a patient message and see the replies (never enabled in staging/prod)"],
    ],
    [3500, 2000, 3526],
  ),
  P("Staff calls send X-Hospital-Id when a user belongs to more than one hospital; admins with '*' in the hospital claim can act for any hospital."),
  H2("8.2 Internal API (port 8001, private only)"),
  T(
    ["Endpoint", "Caller", "Purpose"],
    [
      ["POST /internal/jobs/{job}", "Logic Apps, CronJobs, operators", "reminders, feedback, tickets-escalate, briefing, his-doctors, his-visits, his-reports, maintenance, knowledge-reindex; body {hospital_ids?, rules?}"],
      ["POST /internal/feedback/{hospital}/{appointment}/request", "Durable Functions activity", "Send the feedback template for one visit"],
      ["GET /internal/feedback/{hospital}/{appointment}/status", "Durable Functions activity", "Has the patient replied?"],
      ["POST /internal/consent", "HIS integration", "Consent captured in the HIS at registration"],
    ],
    [3600, 2200, 3226],
  ),
  P("Authentication: Entra ID tokens for the internal API audience issued to allow-listed client IDs (the Logic App and Function App identities), or a shared secret (X-Internal-Token) on clouds without Entra ID."),
  H2("8.3 Dashboard metrics"),
  T(
    ["Area", "Metrics"],
    [
      ["Access", "Bookings total and via WhatsApp, conversations, inbound messages, bot-handled share, average response time"],
      ["Appointments", "Total, confirmation rate, cancellations, no-show rate, completed"],
      ["Reports", "Ready, notified, opened, open rate, average minutes from ready to notified"],
      ["Experience", "Responses, NPS, detractors, open tickets, average ticket closure hours, top complaint categories"],
    ],
    [2000, 7026],
  ),

  // ------------------------------------------------------------------------ //
  H1("9. Security and compliance architecture"),
  IMG("02-network-security", "Figure 6 – Network and identity"),
  H2("9.1 Controls"),
  T(
    ["Domain", "Controls as built"],
    [
      ["Network", "Single public entry (Front Door Premium WAF → AGC WAF); OWASP 2.1 + bot rules, rate limits on /webhooks and /r, India geo-filter; every PaaS service with public access disabled and a private endpoint; PostgreSQL VNet-integrated; Logic Apps/Functions VNet-integrated; Cilium network policies (default deny); internal job API on a separate port and internal load balancer"],
      ["Identity", "Entra ID SSO for staff with app roles; AKS Entra RBAC with local accounts disabled; workload identity for pods; user-assigned identities for Logic Apps and Functions; database access with Entra tokens (password auth disabled); storage shared keys disabled; Cognitive Services, Search, Service Bus local auth disabled"],
      ["Secrets", "Key Vault (RBAC, purge protection, private); only the HMAC key and optional third-party secrets; CSI driver with rotation; nothing in images or Git (.gitignore, .env.example)"],
      ["Data protection", "TLS everywhere (TLS 1.2+); encryption at rest with infrastructure encryption on storage; reports never in chat; signed expiring links; OTP and link tokens stored as hashes; PII-masked logs (phone numbers)"],
      ["Application", "Pydantic validation; CSRF and SameSite cookies on the portal; strict security headers and CSP; non-root, read-only-filesystem containers with all capabilities dropped and seccomp; idempotent jobs; row-level security"],
      ["AI safety", "Content Safety + Prompt Shields before the LLM; scoped prompts; no medical advice; grounded answers only; human handover; no prompt logging by default; regional model deployments"],
      ["Governance", "Defender for Cloud plans (containers, databases, storage, Key Vault, ARM, AI); Azure Policy (India-only locations, AKS pod security baseline, Microsoft cloud security benchmark); Purview for data classification; audit logs for staff actions, consent and report access"],
    ],
    [1700, 7326],
  ),
  H2("9.2 DPDP Act and NABH alignment"),
  T(
    ["Obligation", "How the platform supports it"],
    [
      ["Consent – explicit, recorded, withdrawable", "consent_events with source and evidence; STOP opts out instantly; proactive messages require opt-in; staff and HIS consent capture"],
      ["Purpose limitation and minimisation", "Bot scoped to hospital tasks; first names only in templates; no PDFs in chat; AI never interprets results"],
      ["Security safeguards", "Section 9.1; India-region hosting; encryption; private networking; RBAC"],
      ["Accountability and audit", "audit_logs, report_access_logs, messages, Log Analytics retention; Policy compliance reports"],
      ["Processor role", "Data processing agreement with each hospital (organisational control); tenant isolation by RLS"],
      ["Breach response", "Defender alerts, Azure Monitor alerts to the operations action group; runbook in section 11"],
      ["Data residency", "All stateful services in Central India; ACS data location India; India-only location policy"],
    ],
    [3000, 6026],
  ),

  // ------------------------------------------------------------------------ //
  H1("10. Infrastructure as code"),
  H2("10.1 Bicep"),
  P("infra/bicep/main.bicep deploys at subscription scope: it creates the resource group rg-<prefix>-<env> and every module below, then applies Defender plans and policy assignments. Parameters per environment live in infra/bicep/parameters/*.bicepparam and read tenant-specific IDs from environment variables (nothing tenant-specific is committed)."),
  T(
    ["Module", "Creates"],
    [
      ["monitoring", "Log Analytics, Application Insights, action group, application-error alert"],
      ["network, private-dns", "VNet with seven subnets and NSGs; 13 private DNS zones linked to the VNet"],
      ["identity", "User-assigned identities: workload, Logic App, Functions, ALB controller"],
      ["keyvault, acr", "Key Vault (RBAC, purge protection, PE) with APP-SECRET-KEY; ACR Premium with PE and AcrPull for AKS"],
      ["aks, subnet-role", "AKS (workload identity, KV CSI, Policy, Defender, Container Insights, KEDA, auto-upgrade) + federated credentials; Network Contributor for the internal LB"],
      ["agc, frontdoor", "Application Gateway for Containers (association, frontend, WAF security policy) and optional Front Door Premium + WAF"],
      ["postgres", "Flexible Server 16, Entra auth, private access, extensions allow-list (VECTOR), HA/geo-backup switches, diagnostics"],
      ["storage, runtime-storage", "Reports storage (shared keys off, lifecycle, Event Grid → report-events); runtime storage for Logic Apps/Functions"],
      ["servicebus, role-assignment", "Premium namespace, three queues with duplicate detection and dead-lettering, RBAC"],
      ["acs", "Communication Services (India), Email + domain, Event Grid subscriptions to Service Bus with managed identity"],
      ["ai-foundry, ai-foundry-role", "Foundry (AIServices) account, model deployments, project for tracing, keyless and private"],
      ["cognitive, search", "Content Safety, Translator; AI Search (semantic ranker, keys disabled)"],
      ["apim", "Optional AI gateway with llm-token-limit and token metrics per hospital"],
      ["logicapp, functions", "Logic Apps Standard (WS1) and Function App (EP1, Easy Auth, PE) with app settings"],
      ["backup, dns, optional-services", "Backup vault and policies; Azure DNS records; Grafana, Power BI Embedded, Purview, Data Factory (managed VNet), FHIR"],
      ["security, security-rg-policies", "Defender for Cloud plans; Azure Policy assignments"],
    ],
    [2500, 6526],
  ),
  H2("10.2 Helm chart"),
  T(
    ["Template", "Purpose"],
    [
      ["serviceaccount, secrets", "Workload identity service account; Key Vault SecretProviderClass (or plain Secret for local clusters)"],
      ["configmap", "Deployment overlay of the app configuration and hospitals"],
      ["api, worker, staff-ui", "Deployments and Services with probes, resources, zone spreading, hardened security contexts; internal LB Service for port 8001"],
      ["jobs", "Migration (post-install/pre-upgrade) and knowledge index hooks; CronJobs when cronJobs.enabled"],
      ["autoscaling", "HPA for the API; KEDA ScaledObject (Service Bus, workload identity) for the worker; PodDisruptionBudgets"],
      ["networkpolicy", "Default deny + explicit allows (public API, internal API from workflow subnets, staff UI)"],
      ["routing", "Gateway API (AGC) with HTTPS, HTTP→HTTPS redirect, routes per host and AGC WAF policy attachment – or a classic Ingress"],
    ],
    [2500, 6526],
  ),
  P("Overlays: values.yaml (portable defaults), values-azure.yaml (AKS), values-local.yaml (kind/minikube with Postgres, Redis and MinIO from deploy/local) and the generated values-<env>.generated.yaml written by scripts/render-values.sh from Bicep outputs."),

  // ------------------------------------------------------------------------ //
  H1("11. Deployment and execution instructions"),
  H2("11.1 Prerequisites"),
  T(
    ["Need", "Details"],
    [
      ["Tools", "Azure CLI ≥ 2.60 with Bicep, kubectl, kubelogin, Helm 3.16, jq, zip, psql, Docker (local), Node 20 (staff UI), Python 3.12 (backend)"],
      ["Azure", "Subscription Owner (or Contributor + User Access Administrator) for the first deployment; quota for AKS VMs and the chosen OpenAI models in the AI region"],
      ["Entra ID", "Permission to create app registrations; an admin group for AKS and PostgreSQL (HCWAVE_ADMIN_GROUP_ID)"],
      ["WhatsApp", "Meta Business Manager with business verification; a phone number for each hospital; approved utility/authentication templates"],
      ["SMS (India)", "DLT registration of sender ID and OTP template (for ACS SMS or MSG91)"],
      ["Domain", "A domain for branded links (reports., staff., api.) and TLS certificates (cert-manager with Let's Encrypt or certificates from Key Vault)"],
    ],
    [1800, 7226],
  ),
  H2("11.2 Run on a laptop (offline, about 5 minutes)"),
  S([
    "cp .env.example .env (defaults are offline: console WhatsApp, offline LLM, local storage).",
    "docker compose up --build – starts PostgreSQL + pgvector, Redis, migrations + FAQ indexing, API (8000/8001), worker and the staff UI (5173).",
    "Chat as a patient: curl -XPOST localhost:8000/dev/simulate -H 'content-type: application/json' -d '{\"text\":\"hi\"}' – then reply with reply_id values from the returned choices (e.g. menu:book).",
    "Open http://localhost:5173 for the staff app (sign-in disabled in dev) and http://localhost:8000/docs for the API.",
    "Point any provider at Azure by setting its variables in .env (for example MESSAGING_PROVIDER=acs_whatsapp, ACS_ENDPOINT, LLM_INTENT_PROVIDER=azure_openai, AZURE_OPENAI_ENDPOINT) and running az login.",
  ]),
  CODE(`make up          # docker compose up --build -d
make simulate    # send "hi" as a patient
make test        # backend tests (TEST_DATABASE_URL)
make lint        # ruff (Google docstrings) for backend and functions`),
  H2("11.3 Run on any Kubernetes cluster (kind, minikube, EKS, GKE)"),
  CODE(`docker build -f services/backend/Dockerfile -t hcwave/backend:local .
docker build -t hcwave/staff-ui:local services/staff-ui
kind load docker-image hcwave/backend:local hcwave/staff-ui:local   # kind only
kubectl create namespace hcwave
kubectl -n hcwave apply -f deploy/local/dependencies.yaml            # Postgres, Redis, MinIO
helm upgrade --install hcwave deploy/helm/hcwave -n hcwave -f deploy/helm/hcwave/values-local.yaml`),
  P("values-local.yaml uses Redis Streams for the queue, MinIO through the S3 adapter for reports and CronJobs for scheduling – the same configuration pattern used to port the platform to another cloud."),
  H2("11.4 Deploy to Azure (step by step)"),
  S([
    "Sign in and select the subscription: az login && az account set -s <subscription-id>.",
    "Export the environment-specific inputs: HCWAVE_ADMIN_GROUP_ID, HCWAVE_ADMIN_GROUP_NAME, HCWAVE_ALERT_EMAIL, optionally HCWAVE_AI_LOCATION (a region where gpt-5-mini, gpt-5 and the embedding model are available to you) and HCWAVE_DNS_ZONE.",
    "Preview and deploy the infrastructure: make infra-whatif ENV=dev then make infra ENV=dev (scripts/deploy-infra.sh; 30–60 minutes the first time). Outputs are written to deploy/generated/dev.env.",
    "Create the Entra app registrations: make entra ENV=dev UI_URL=https://staff.<domain>. Append the printed values to deploy/generated/dev.env; assign users to the app roles; configure the hospital_ids claim.",
    "Connect WhatsApp in ACS: Azure portal → Communication Services → Channels → WhatsApp (Meta embedded sign-up), one number per hospital. Put each channel registration ID in the hospital's channel_ids (DEMO_HOSPITAL_CHANNEL_IDS in deploy/generated/<env>.env for the demo tenant).",
    "Submit the templates in Appendix A in WhatsApp Manager (utility/authentication) in every language; keep names identical to templates.yaml.",
    "Install cluster add-ons: make addons ENV=dev (ALB controller for Application Gateway for Containers, cert-manager; add --with-backup for AKS Backup).",
    "Create the database principal for the workload identity: make db-bootstrap ENV=dev (run from a machine with VNet access, or through az aks command invoke).",
    "Store optional third-party secrets: e.g. MSG91_AUTH_KEY=… scripts/kv-secrets.sh dev, then list them under secrets.azureKeyVault.objects.",
    "Issue TLS certificates for the gateway (cert-manager Certificate referencing the Gateway, or sync a Key Vault certificate into the hcwave-tls Secret) and create DNS records (dns.bicep or your DNS provider).",
    "Build and deploy the application: make deploy ENV=dev (images built in ACR, values rendered, Helm release with migrations and FAQ indexing hooks).",
    "Deploy workflows: make workflows ENV=dev (Logic Apps workflows and the Durable Functions app).",
    "Smoke test: scripts/smoke-test.sh https://api.<domain>; send 'hi' from a test phone; check the worker logs and Application Insights; trigger a job from the Logic App run history.",
    "Dashboard: either keep the built-in tiles, or set DASHBOARD_PROVIDER=power_bi with POWERBI_WORKSPACE_ID/POWERBI_REPORT_ID (allow the workload identity in the Power BI tenant settings and add it to the workspace), or grafana with GRAFANA_URL.",
  ]),
  H2("11.5 CI/CD"),
  B([
    "GitHub Actions: ci.yml (ruff + pytest on PostgreSQL/pgvector, Functions lint, staff UI build, Bicep build, Helm lint + kubeconform, image builds + Trivy) on every push; deploy.yml (manual, per environment) with OpenID Connect – configure AZURE_CLIENT_ID, AZURE_TENANT_ID, AZURE_SUBSCRIPTION_ID, HCWAVE_ADMIN_GROUP_ID and the Entra app IDs as environment variables of each GitHub environment.",
    "Azure DevOps: azure-pipelines.yml with a variable group per environment and a workload-identity service connection; Boards replace Jira/Linear for tracking.",
    "Private environments: with a private AKS API and private ACR, run deployments from self-hosted agents in the VNet or use az aks command invoke / ACR tasks.",
  ]),

  // ------------------------------------------------------------------------ //
  H1("12. Operations"),
  H2("12.1 Monitoring and tracing"),
  B([
    "Application Insights: requests, dependencies and exceptions from the API, worker and functions (OpenTelemetry via the Azure Monitor distro); LLM calls carry GenAI semantic-convention spans (model, operation, token usage) for Microsoft Foundry tracing and evaluations.",
    "Log Analytics: JSON container logs with masked phone numbers, AKS audit logs, Key Vault, PostgreSQL, Service Bus, AI Search and Foundry diagnostics.",
    "Alerts: application errors (scheduled query), plus recommended metric alerts on Service Bus dead-lettered messages, Logic Apps failed runs, PostgreSQL CPU/storage and AKS node pressure – all to the operations action group.",
    "Business health: confirmation and no-show rates, report open rate, NPS and ticket closure time on the dashboard; daily briefing to unit heads.",
  ]),
  H2("12.2 Scaling"),
  P("The API scales with an HPA on CPU (2–6 replicas by default), the worker with KEDA on the inbound queue backlog (1–10), the user node pool with the cluster autoscaler, and Logic Apps/Functions elastically. Per-conversation row locks keep message order with many workers. PostgreSQL scales vertically (SKU) and with read replicas for BI if needed."),
  H2("12.3 Runbook"),
  T(
    ["Symptom", "Checks and actions"],
    [
      ["Patients get no reply", "Worker logs and readiness; Service Bus inbound queue length and dead-letter queue; Event Grid subscription delivery failures; hospital channel_ids match the ACS channel ID; ACS Contributor role for the workload identity"],
      ["Reminders/reports not sent", "Logic App run history (a tenant error fails the run); call POST /internal/jobs/<job> manually; consent status of the conversation; notification_logs for an existing claim; template approval status"],
      ["Report link fails", "Link expiry/lockout in reports; Storage Blob Delegator role; private DNS for blob; report_access_logs for the failing step"],
      ["LLM errors or slowness", "Application Insights dependency failures (429 = quota): raise TPM capacity or enable APIM quotas; check the deployment names in llm.profiles; the assistant hands over automatically"],
      ["Database connection errors", "Entra token for the workload identity (pgaadauth principal exists – db-bootstrap); private DNS zone link; server status"],
      ["Staff cannot sign in or see data", "App role assignment; hospital_ids claim; X-Hospital-Id header; staff_users row"],
      ["Rotate APP_SECRET_KEY", "Set a new Key Vault secret version; pods pick it up via CSI rotation (restart to apply); open portal sessions and pending OTPs become invalid"],
      ["Suspected breach", "Defender alerts; isolate with network policy or scale to zero; preserve Log Analytics data; notify per the DPA and the DPDP breach procedure"],
    ],
    [2400, 6626],
  ),
  H2("12.4 Backup, restore and disaster recovery"),
  B([
    "Database: point-in-time restore to a new server (az postgres flexible-server restore), run db-bootstrap if needed, update DATABASE_URL (Helm values) and redeploy. Geo-restore to South India in a regional outage (production geo-redundant backups).",
    "Reports: restore deleted or overwritten blobs from versions/soft delete or the operational backup.",
    "Cluster: restore from AKS Backup, or simply redeploy – the cluster is stateless and fully described by Bicep and Helm.",
    "Region loss: deploy the Bicep template to the paired region, restore the database from geo-backup, re-point DNS/Front Door. Suggested targets for the pilot: RPO ≤ 15 minutes, RTO ≤ 4 hours.",
  ]),
  H2("12.5 Cost drivers"),
  P("Use the Azure Pricing Calculator with the chosen SKUs. The main drivers are AKS nodes, Service Bus Premium (needed for private endpoints), AI Search tier, Front Door Premium, APIM (optional), PostgreSQL SKU/HA, Azure OpenAI token usage and WhatsApp conversation charges. dev.bicepparam already disables Front Door, APIM, Backup and Defender and uses smaller SKUs; Service Bus Standard (public endpoint with Entra auth) and AI Search basic further reduce non-production cost."),

  // ------------------------------------------------------------------------ //
  H1("13. Go-live checklist"),
  T(
    ["#", "Check", "Owner"],
    [
      ["1", "Data processing agreement signed with the hospital (platform is the DPDP data processor)", "Business"],
      ["2", "India-region hosting confirmed (location policy compliant), encryption at rest and in transit", "Platform"],
      ["3", "Staff roles assigned in Entra ID; hospital_ids claim verified; audit logs reviewed", "Hospital IT"],
      ["4", "Consent capture at registration live; STOP tested end to end", "Implementation"],
      ["5", "Enterprise AI terms (no training on data); content capture in traces disabled", "Platform"],
      ["6", "DLT registration for SMS fallback (sender ID and OTP template)", "Implementation"],
      ["7", "All templates approved in every language; Malayalam and Hindi strings reviewed by native speakers", "Implementation"],
      ["8", "Emergency keywords and casualty message validated by the hospital", "Hospital"],
      ["9", "FAQ content approved by the hospital and indexed", "Hospital"],
      ["10", "Doctor schedules imported; test bookings, reminders, report link and feedback verified with staff", "Implementation"],
      ["11", "Alerts routed to an on-call rota; backups verified with a test restore", "Platform"],
      ["12", "Defender recommendations and Policy compliance reviewed; WAF in Prevention mode", "Platform"],
    ],
    [500, 6526, 2000],
  ),

  // ------------------------------------------------------------------------ //
  H1("14. Items to verify for your tenant"),
  P("These depend on Azure service availability and approvals at deployment time; the platform is built to switch without code changes."),
  T(
    ["Item", "Why", "Fallback built in"],
    [
      ["ACS interactive messages (buttons/lists) and the Advanced Messaging API version", "Interactive support is newer than text/templates", "supports_interactive: false renders numbered text menus that the flows understand"],
      ["gpt-5-mini / gpt-5 / embedding availability and quota in South or Central India", "Data residency requirement", "Change deployment names/regions in openAiDeployments and llm.profiles"],
      ["Claude in Foundry", "Needs an Enterprise/MCA-E subscription; regions currently outside India", "anthropic_foundry provider ready when allowed"],
      ["ACS SMS to Indian numbers under DLT", "Regulatory", "sms.provider: msg91 (the one non-Azure piece)"],
      ["Application Gateway for Containers WAF in the region", "Feature availability", "Front Door Premium WAF, or ingress.mode: ingress"],
      ["Power BI service principal / workload identity access", "Tenant setting", "Grafana or built-in tiles"],
      ["Meta business verification and template approval lead time", "Approvals can need rewording", "Submit in week 1"],
    ],
    [3000, 2800, 3226],
  ),

  // ------------------------------------------------------------------------ //
  H1("15. Verification performed (as-built evidence)"),
  T(
    ["Check", "Result"],
    [
      ["Backend test suite (pytest) against PostgreSQL 16 + pgvector", "48 passed – config, security, ACS/Meta adapters, booking flow end to end, consent/STOP, emergencies (Malayalam), FAQ RAG, handover, reminders (idempotency, opt-out, button ownership), reports (DOB, OTP, lockout, opted-out), feedback/tickets/escalation, staff and internal APIs, row-level security isolation"],
      ["Lint", "ruff check + ruff format clean (Google docstring convention) for backend and functions"],
      ["Migrations", "Alembic upgrade → downgrade → upgrade on PostgreSQL 16 (40 RLS policies, pgvector HNSW index, views)"],
      ["Bicep", "main.bicep and dev/prod .bicepparam build with Bicep CLI 0.48.1 – no errors or linter warnings"],
      ["Helm", "helm lint for default, local and Azure overlays; 70 rendered objects valid in kubeconform strict mode, including Gateway API, ALB WAF policy, KEDA and SecretProviderClass CRDs"],
      ["Container images", "Backend and staff UI images built; run as non-root with read-only root filesystem; migrations, FAQ indexing, assistant replies, menu and internal job API verified in the container"],
      ["Staff UI", "TypeScript strict build (Vite) with code-split dashboard"],
      ["Durable Functions", "Function app loads with 5 functions (starter, orchestrator, 3 activities)"],
    ],
    [3000, 6026],
  ),
  NOTE("Not executed in this build: a live deployment to an Azure subscription (requires tenant credentials, Meta approval and model quota). Run section 11.4 in a dev subscription first."),
];

// ------------------------------------------------------------------------ //
// Appendices
// ------------------------------------------------------------------------ //
const appendices = [
  H1("Appendix A – WhatsApp templates for submission"),
  P("Suggested English body text; parameters must stay in the order listed in config/messaging/templates.yaml. Translate into Malayalam and Hindi with native review and submit each language under the same template name."),
  T(
    ["Template (category)", "Body", "Buttons"],
    [
      ["hcw_appointment_confirmation (utility)", "Hello {{1}}, your appointment with {{2}} on {{3}} at {{4}} is confirmed. Reply here if you need any help.", "—"],
      ["hcw_appointment_reminder (utility)", "Hello {{1}}, this is a reminder of your appointment with {{2}} on {{3}} at {{4}}. Please confirm, reschedule or cancel below.", "Quick replies: Confirm · Reschedule · Cancel"],
      ["hcw_appointment_prep (utility)", "Hello {{1}}, your appointment with {{2}} is today at {{3}}. Please bring previous reports and prescriptions, a photo ID and your insurance card, and follow any fasting instructions you were given.", "—"],
      ["hcw_missed_appointment (utility)", "Hello {{1}}, we missed you today for your appointment with {{2}}. Would you like to book a new time?", "Quick reply: Rebook"],
      ["hcw_follow_up_due (utility)", "Hello {{1}}, {{2}} advised a follow-up visit on {{3}}. Tap below to choose a convenient time.", "Quick reply: Book follow-up"],
      ["hcw_report_ready (utility)", "Hello {{1}}, your {{2}} report is ready. For your privacy, open it with the secure link below and verify with a one-time code or date of birth. The link expires in {{3}} hours.", "URL: https://reports.<domain>/r/{{1}}"],
      ["hcw_otp_code (authentication)", "{{1}} is your verification code. For your security, do not share this code.", "Copy code"],
      ["hcw_feedback_request (utility)", "Hello {{1}}, thank you for visiting {{2}}. How likely are you to recommend us to friends and family? Please reply with a number from 0 (not likely) to 10 (very likely).", "—"],
      ["hcw_staff_ticket_alert (utility)", "{{1}}: new patient complaint – {{2}}, score {{3}}. {{4}} Please respond in the staff app.", "—"],
      ["hcw_daily_briefing (utility)", "{{1}} daily briefing for {{2}}: bookings {{3}}; no-show rate {{4}}; reports {{5}}; NPS {{6}}; handled by assistant {{7}}.", "—"],
    ],
    [2600, 4626, 1800],
  ),
  H1("Appendix B – Key environment variables"),
  P("The complete, commented list is in .env.example. In AKS these are set by Helm (values-azure.yaml and the generated values) or come from Key Vault."),
  T(
    ["Variable", "Purpose"],
    [
      ["APP_ENV", "Config profile: dev | test | staging | prod"],
      ["APP_SECRET_KEY (secret)", "HMAC key for portal cookies and OTP hashing (Key Vault APP-SECRET-KEY)"],
      ["DATABASE_URL, DATABASE_AUTH_MODE", "postgresql+asyncpg://<identity>@<host>:5432/hcwave; azure_ad uses workload identity tokens"],
      ["AZURE_CLIENT_ID, AZURE_TENANT_ID, AZURE_IDENTITY_MODE", "Identity used by Azure SDKs (injected by the workload identity webhook)"],
      ["MESSAGING_PROVIDER, ACS_ENDPOINT, <HOSPITAL>_CHANNEL_IDS", "WhatsApp channel and the channel IDs that route to each hospital"],
      ["QUEUE_PROVIDER, SERVICEBUS_NAMESPACE", "Queue provider and Service Bus namespace"],
      ["LLM_<PROFILE>_PROVIDER / _MODEL, AZURE_OPENAI_ENDPOINT", "Model per profile (intent, reply, tagger, embedding) and endpoint (Foundry or APIM)"],
      ["KNOWLEDGE_PROVIDER, AZURE_SEARCH_ENDPOINT", "RAG store"],
      ["SAFETY_PROVIDER, AZURE_CONTENT_SAFETY_ENDPOINT; LANGUAGE_PROVIDER, AZURE_TRANSLATOR_ENDPOINT", "Guardrails and language detection"],
      ["STORAGE_PROVIDER, AZURE_STORAGE_ACCOUNT_URL", "Report storage"],
      ["EMAIL_PROVIDER, EMAIL_SENDER; SMS_PROVIDER, ACS_SMS_FROM / MSG91_*", "Alerts and OTP fallback"],
      ["AUTH_PROVIDER, STAFF_API_AUDIENCE", "Staff sign-in (entra_id in cloud environments)"],
      ["INTERNAL_AUTH_MODE, INTERNAL_API_AUDIENCE, INTERNAL_ALLOWED_CLIENT_IDS", "Internal job API authentication"],
      ["SCHEDULER_ENGINE, FEEDBACK_ENGINE, DURABLE_FEEDBACK_START_URL", "Who triggers jobs; Durable Functions starter"],
      ["DASHBOARD_PROVIDER, POWERBI_*, GRAFANA_URL", "Dashboard embedding"],
      ["HIS_PROVIDER, HIS_API_BASE_URL / FHIR_URL", "HIS connector"],
      ["TELEMETRY_EXPORTER, APPLICATIONINSIGHTS_CONNECTION_STRING", "Telemetry destination"],
    ],
    [3800, 5226],
  ),
  H1("Appendix C – Glossary"),
  T(
    ["Term", "Meaning"],
    [
      ["ACS", "Azure Communication Services – WhatsApp (Advanced Messaging), SMS and Email"],
      ["AGC", "Application Gateway for Containers – Azure's Gateway API load balancer for AKS"],
      ["DLT", "Distributed Ledger Technology registration required for commercial SMS in India"],
      ["DPDP", "India's Digital Personal Data Protection Act, 2023"],
      ["HIS / LIS", "Hospital / Laboratory Information System"],
      ["NABH", "National Accreditation Board for Hospitals & Healthcare Providers"],
      ["NPS", "Net Promoter Score (0–10 likelihood to recommend)"],
      ["RAG", "Retrieval-augmented generation – answering from retrieved hospital content"],
      ["RLS", "PostgreSQL row-level security"],
      ["Workload ID", "Microsoft Entra Workload ID – Kubernetes service accounts federated to managed identities"],
    ],
    [2000, 7026],
  ),
];

module.exports = { sections, appendices };
