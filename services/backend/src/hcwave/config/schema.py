"""Typed configuration schema.

Every YAML section maps onto a Pydantic model so that typos and wrong types
fail fast at start-up instead of at 2 a.m. when a reminder job runs.

Pluggable infrastructure (messaging, queue, storage, ...) follows one pattern,
:class:`AdapterSection`: ``provider`` picks the implementation and
``providers.<name>`` holds that implementation's own settings, which the
adapter validates with its own model. Switching cloud or vendor is therefore a
one-line YAML change.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ConfigModel(BaseModel):
    """Base model for configuration: unknown keys are rejected."""

    model_config = ConfigDict(extra="forbid", frozen=True)


# --------------------------------------------------------------------------- #
# Generic building blocks
# --------------------------------------------------------------------------- #
class AdapterSection(ConfigModel):
    """A pluggable component: the chosen provider plus per-provider settings.

    Attributes:
        provider: Registered provider name (for example ``acs_whatsapp``) or a
            fully qualified ``package.module:ClassName`` for custom plugins.
        providers: Settings for each provider, keyed by provider name.
    """

    provider: str
    providers: dict[str, dict[str, Any]] = Field(default_factory=dict)

    def provider_settings(self, name: str | None = None) -> dict[str, Any]:
        """Returns the raw settings mapping for ``name`` (default: active provider)."""
        return dict(self.providers.get(name or self.provider) or {})


# --------------------------------------------------------------------------- #
# Runtime sections
# --------------------------------------------------------------------------- #
class AppSection(ConfigModel):
    """Application identity and global behaviour."""

    name: str = "hcwave"
    environment: str = "dev"
    public_base_url: str = "http://localhost:8000"
    log_level: str = "INFO"
    log_format: Literal["json", "text"] = "json"
    timezone: str = "Asia/Kolkata"
    # HMAC key for signed cookies and OTP hashing. Always supplied via env.
    secret_key: str = ""


class ServerSection(ConfigModel):
    """HTTP server settings for the public and internal listeners."""

    host: str = "0.0.0.0"  # noqa: S104 - container listens on all interfaces
    public_port: int = 8000
    internal_port: int = 8001
    cors_origins: list[str] = Field(default_factory=list)
    docs_enabled: bool = False
    dev_routes_enabled: bool = False
    forwarded_allow_ips: str = "*"


class DatabaseSection(ConfigModel):
    """PostgreSQL connection settings.

    ``auth_mode=azure_ad`` uses a Microsoft Entra token from the workload
    identity as the password, so no database password exists anywhere.
    """

    url: str
    auth_mode: Literal["password", "azure_ad"] = "password"
    azure_ad_scope: str = "https://ossrdbms-aad.database.windows.net/.default"
    pool_size: int = 10
    max_overflow: int = 5
    pool_recycle_seconds: int = 1800
    ssl_mode: Literal["disable", "prefer", "require", "verify-full"] = "require"
    echo: bool = False
    row_level_security: bool = True


class IdentitySection(ConfigModel):
    """How Azure SDK clients authenticate.

    ``default`` uses ``DefaultAzureCredential`` which picks up AKS workload
    identity, managed identity or a developer's ``az login`` automatically.
    """

    mode: Literal["default", "workload_identity", "managed_identity", "none"] = "default"
    client_id: str = ""
    tenant_id: str = ""


class QueueNames(ConfigModel):
    """Logical queue names mapped to physical queue/topic names."""

    inbound: str = "inbound-messages"
    delivery: str = "delivery-status"
    reports: str = "report-events"


class QueueSection(AdapterSection):
    """Message queue used between webhooks/Event Grid and the worker."""

    queues: QueueNames = QueueNames()


class MessagingSection(AdapterSection):
    """Patient messaging channel (WhatsApp today, anything tomorrow)."""

    # When the provider cannot send buttons/lists, render them as a numbered
    # text menu the patient answers with a number.
    interactive_fallback: Literal["text_menu", "error"] = "text_menu"
    max_buttons: int = 3
    max_list_rows: int = 10
    session_window_hours: int = 24


class LLMProfile(ConfigModel):
    """One logical model use (intent, reply, tagging, embeddings).

    Attributes:
        provider: Provider key under ``llm.providers``.
        model: Model or deployment name (Azure OpenAI deployment name).
        temperature: Sampling temperature; ``None`` keeps the model default
            (required for reasoning models such as GPT-5).
        max_tokens: Output token cap.
        timeout_seconds: Request timeout.
        max_retries: Client retries on transient errors.
        dimensions: Embedding size (embedding profiles only).
    """

    provider: str
    model: str
    temperature: float | None = None
    max_tokens: int | None = None
    timeout_seconds: float = 30.0
    max_retries: int = 2
    dimensions: int | None = None


class LLMSection(ConfigModel):
    """Language models and their providers."""

    profiles: dict[str, LLMProfile]
    providers: dict[str, dict[str, Any]] = Field(default_factory=dict)


class KnowledgeSection(AdapterSection):
    """Retrieval (RAG) over each hospital's FAQs and policies."""

    top_k: int = 4
    min_score: float = 0.0
    embedding_profile: str = "embedding"


class LanguageSection(AdapterSection):
    """Language detection and optional translation."""

    supported: list[str] = Field(default_factory=lambda: ["en", "ml", "hi"])
    default: str = "en"


class SafetySection(AdapterSection):
    """Content safety and prompt-injection screening."""

    # Azure AI Content Safety severities run 0..7; block at or above this.
    block_severity: int = 4
    prompt_shields_enabled: bool = True
    fail_open: bool = False


class StorageSection(AdapterSection):
    """Object storage for report PDFs and HIS file drops."""

    containers: dict[str, str] = Field(
        default_factory=lambda: {"reports": "reports", "imports": "his-imports"}
    )


class EmailSection(AdapterSection):
    """Outbound email for complaint alerts and briefing copies."""

    sender: str = ""


class SmsSection(AdapterSection):
    """Outbound SMS, used as the OTP fallback."""


class DashboardSection(AdapterSection):
    """Management dashboard embedding (Power BI, Grafana or built-in)."""


class HisSection(AdapterSection):
    """Hospital Information System connector."""


class AuthSection(ConfigModel):
    """Staff sign-in (OIDC bearer tokens from Microsoft Entra ID).

    Attributes:
        provider: ``entra_id`` (Microsoft Entra), ``oidc`` (any OIDC issuer)
            or ``disabled`` (local development only).
        tenant_id: Entra tenant used to derive issuer and JWKS URLs.
        audience: Expected ``aud`` claim (the API app registration).
        issuer: Overrides the derived issuer (generic OIDC).
        jwks_url: Overrides the derived JWKS URL (generic OIDC).
        role_claim: Claim holding app roles.
        hospital_claim: Claim holding the staff member's hospital IDs.
        role_map: Platform role -> app role value in the token.
        dev_user: Identity injected when ``provider=disabled``.
    """

    provider: Literal["entra_id", "oidc", "disabled"] = "entra_id"
    tenant_id: str = ""
    audience: str = ""
    issuer: str = ""
    jwks_url: str = ""
    role_claim: str = "roles"
    hospital_claim: str = "hospital_ids"
    role_map: dict[str, str] = Field(
        default_factory=lambda: {
            "front_office": "FrontOffice",
            "patient_relations": "PatientRelations",
            "unit_head": "UnitHead",
            "admin": "Admin",
        }
    )
    dev_user: dict[str, Any] = Field(default_factory=dict)


class InternalAuthSection(ConfigModel):
    """Authentication for the internal job API (Logic Apps, Functions, CronJobs).

    ``entra_id`` validates managed-identity tokens; ``allowed_client_ids``
    restricts callers to known identities. ``shared_secret`` suits other clouds.
    """

    mode: Literal["entra_id", "shared_secret", "disabled"] = "entra_id"
    tenant_id: str = ""
    audience: str = ""
    allowed_client_ids: list[str] = Field(default_factory=list)
    shared_secret: str = ""

    @field_validator("allowed_client_ids", mode="before")
    @classmethod
    def _split_csv(cls, value: Any) -> Any:
        """Accepts a comma-separated string (handy for env interpolation)."""
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value


class GuardrailsSection(ConfigModel):
    """Assistant behaviour limits."""

    intent_confidence_threshold: float = 0.6
    max_input_chars: int = 1000


class ConversationSection(ConfigModel):
    """Keywords and timers for conversations."""

    stop_keywords: list[str] = Field(default_factory=lambda: ["stop", "unsubscribe"])
    start_keywords: list[str] = Field(default_factory=lambda: ["start", "subscribe"])
    menu_keywords: list[str] = Field(default_factory=lambda: ["menu", "hi", "hello"])
    human_keywords: list[str] = Field(default_factory=lambda: ["agent", "human"])
    handover_auto_release_minutes: int = 240
    # The build guide allows recording consent through the patient's first
    # message. Set false if the hospital requires explicit opt-in only.
    first_message_is_opt_in: bool = True
    max_invalid_flow_inputs: int = 2
    default_country_code: str = "91"


class BookingSection(ConfigModel):
    """Booking flow settings."""

    days_ahead: int = 7
    max_slots_shown: int = 10
    collect_date_of_birth: bool = True
    min_lead_minutes: int = 60


class OtpSettings(ConfigModel):
    """One-time password settings for report access."""

    length: int = 6
    ttl_minutes: int = 10
    max_attempts: int = 5
    channels: list[Literal["whatsapp", "sms"]] = Field(default_factory=lambda: ["whatsapp", "sms"])


class ReportsSection(ConfigModel):
    """Secure report delivery settings."""

    link_base_url: str = ""
    link_ttl_hours: int = 48
    download_url_ttl_minutes: int = 5
    portal_session_minutes: int = 10
    verification_methods: list[Literal["otp", "dob"]] = Field(
        default_factory=lambda: ["otp", "dob"]
    )
    max_verification_attempts: int = 5
    lockout_minutes: int = 30
    otp: OtpSettings = OtpSettings()


class ReminderRule(ConfigModel):
    """One reminder rule evaluated by the reminders job.

    Attributes:
        id: Stable rule identifier (also used for idempotency).
        kind: ``before_appointment``, ``missed_appointment`` or
            ``follow_up_due``.
        offset_minutes: Minutes relative to the anchor time (negative =
            before). Anchor is the appointment start, or the follow-up date.
        window_minutes: How far past the due time a reminder may still go out
            (covers job delays without sending late reminders forever).
        template: Logical template name from ``templates.yaml``.
        enabled: Turns the rule on or off.
    """

    id: str
    kind: Literal["before_appointment", "missed_appointment", "follow_up_due"]
    offset_minutes: int
    window_minutes: int = 60
    template: str
    enabled: bool = True


class RemindersSection(ConfigModel):
    """Reminder rules."""

    rules: list[ReminderRule] = Field(default_factory=list)


class FeedbackSection(ConfigModel):
    """Feedback and service recovery settings."""

    opd_delay_hours: float = 3
    discharge_delay_hours: float = 24
    request_window_hours: float = 12
    reply_timeout_hours: float = 24
    detractor_threshold: int = 6
    categories: list[str] = Field(
        default_factory=lambda: [
            "waiting_time",
            "billing",
            "staff_behaviour",
            "cleanliness",
            "doctor_communication",
            "other",
        ]
    )
    ticket_sla_hours: float = 4
    escalate_after_hours: float = 8
    send_review_invite: bool = True


class BriefingSection(ConfigModel):
    """Daily management briefing."""

    enabled: bool = True
    send_whatsapp: bool = True
    send_email: bool = True


class SchedulerSection(ConfigModel):
    """Which engine triggers scheduled jobs.

    The job logic always lives in Python; the engine only decides *who* calls
    it: Logic Apps (Azure), Kubernetes CronJobs (any cloud) or Durable
    Functions (multi-step feedback waits).
    """

    engine: Literal["logic_apps", "k8s_cronjob", "none"] = "logic_apps"
    feedback_engine: Literal["durable_functions", "jobs"] = "jobs"
    durable_start_url: str = ""
    durable_audience: str = ""


class TelemetrySection(ConfigModel):
    """Logs, metrics and traces (including LLM tracing)."""

    enabled: bool = True
    exporter: Literal["azure_monitor", "otlp", "console", "none"] = "azure_monitor"
    connection_string: str = ""
    otlp_endpoint: str = ""
    service_name: str = "hcwave"
    # Prompt/response text can contain patient data. Keep off unless the
    # tracing store is approved for PHI.
    capture_llm_content: bool = False


# --------------------------------------------------------------------------- #
# Tenant (hospital) configuration
# --------------------------------------------------------------------------- #
class EmergencyConfig(ConfigModel):
    """Emergency keyword detection and reply."""

    phone: str
    message: dict[str, str]
    keywords: dict[str, list[str]]


class HospitalContacts(ConfigModel):
    """Who receives alerts and briefings at the hospital."""

    patient_relations_emails: list[str] = Field(default_factory=list)
    patient_relations_phones: list[str] = Field(default_factory=list)
    unit_head_emails: list[str] = Field(default_factory=list)
    unit_head_phones: list[str] = Field(default_factory=list)
    front_office_phone: str = ""


class HospitalFeatures(ConfigModel):
    """Per-hospital module switches."""

    assistant: bool = True
    booking: bool = True
    reminders: bool = True
    reports: bool = True
    feedback: bool = True
    dashboard: bool = True
    briefing: bool = True


class HospitalConfig(ConfigModel):
    """One hospital (tenant).

    Attributes:
        id: Stable tenant identifier used as ``hospital_id`` in every table.
        name: Display name.
        timezone: IANA timezone for schedules and reminders.
        channel_ids: Messaging channel identifiers that belong to this
            hospital (ACS channel registration IDs, Meta phone number IDs...).
            Inbound messages are routed to the tenant by these IDs.
        languages: Supported language codes, first is preferred.
        default_language: Fallback language.
        emergency: Emergency keywords and reply.
        contacts: Alert and briefing recipients.
        features: Module switches.
        google_review_url: Review invite link (sent to every patient).
        address: Postal address used in FAQ answers.
        map_url: Directions link.
        knowledge_files: FAQ/policy files (relative to the config dir) to index.
        his: Per-hospital HIS connector overrides.
    """

    id: str
    name: str
    timezone: str = "Asia/Kolkata"
    active: bool = True
    channel_ids: list[str] = Field(default_factory=list)
    languages: list[str] = Field(default_factory=lambda: ["en"])
    default_language: str = "en"
    emergency: EmergencyConfig
    contacts: HospitalContacts = HospitalContacts()
    features: HospitalFeatures = HospitalFeatures()
    google_review_url: str = ""
    address: str = ""
    map_url: str = ""
    knowledge_files: list[str] = Field(default_factory=list)
    his: dict[str, Any] = Field(default_factory=dict)

    @field_validator("channel_ids", mode="before")
    @classmethod
    def _split_csv(cls, value: Any) -> Any:
        """Accepts a comma-separated string (handy for env interpolation)."""
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value


class TemplateButton(ConfigModel):
    """A button defined on an approved WhatsApp template."""

    sub_type: Literal["quick_reply", "url"]
    # quick_reply: payload pattern, e.g. "remind_confirm:{appointment_id}".
    # url: name of the parameter that fills the dynamic URL suffix.
    value: str


class TemplateDefinition(ConfigModel):
    """A pre-approved message template, independent of provider.

    Attributes:
        name: Template name registered with the channel (WhatsApp Manager).
        category: ``utility``, ``authentication`` or ``marketing``.
        languages: Platform language -> channel language code.
        body_params: Ordered parameter names filling ``{{1}}``, ``{{2}}``...
        buttons: Template buttons in order.
    """

    name: str
    category: Literal["utility", "authentication", "marketing"] = "utility"
    languages: dict[str, str] = Field(default_factory=lambda: {"en": "en"})
    body_params: list[str] = Field(default_factory=list)
    buttons: list[TemplateButton] = Field(default_factory=list)


class Settings(ConfigModel):
    """Root configuration object."""

    app: AppSection = AppSection()
    server: ServerSection = ServerSection()
    database: DatabaseSection
    identity: IdentitySection = IdentitySection()
    messaging: MessagingSection
    queue: QueueSection
    llm: LLMSection
    knowledge: KnowledgeSection
    language: LanguageSection
    safety: SafetySection
    storage: StorageSection
    email: EmailSection
    sms: SmsSection
    dashboard: DashboardSection
    his: HisSection
    auth: AuthSection = AuthSection()
    internal_auth: InternalAuthSection = InternalAuthSection()
    guardrails: GuardrailsSection = GuardrailsSection()
    conversation: ConversationSection = ConversationSection()
    booking: BookingSection = BookingSection()
    reports: ReportsSection = ReportsSection()
    reminders: RemindersSection = RemindersSection()
    feedback: FeedbackSection = FeedbackSection()
    briefing: BriefingSection = BriefingSection()
    scheduler: SchedulerSection = SchedulerSection()
    telemetry: TelemetrySection = TelemetrySection()

    # Loaded from separate files (hospitals/, messaging/, locales/, prompts/).
    hospitals: dict[str, HospitalConfig] = Field(default_factory=dict)
    templates: dict[str, TemplateDefinition] = Field(default_factory=dict)
    locales: dict[str, dict[str, str]] = Field(default_factory=dict)
    prompts: dict[str, dict[str, Any]] = Field(default_factory=dict)
