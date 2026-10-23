"""Plugin registry mapping provider names to implementation classes.

Implementations are referenced by ``module:Class`` strings, so a cloud SDK is
imported only when its provider is selected in YAML. That keeps the image
portable: an AWS deployment never imports ``azure.*`` and vice versa.

To add a provider (for example Telegram as a messaging channel) either
register it here or point ``messaging.provider`` at
``"my_package.telegram:TelegramProvider"`` directly.
"""

from __future__ import annotations

import importlib
from typing import Any

# kind -> provider name -> "module:Class"
REGISTRY: dict[str, dict[str, str]] = {
    "messaging": {
        "acs_whatsapp": "hcwave.adapters.messaging.acs_whatsapp:AcsWhatsAppProvider",
        "meta_cloud": "hcwave.adapters.messaging.meta_cloud:MetaCloudProvider",
        "console": "hcwave.adapters.messaging.console:ConsoleProvider",
    },
    "queue": {
        "azure_service_bus": "hcwave.adapters.queue.azure_service_bus:ServiceBusQueue",
        "redis": "hcwave.adapters.queue.redis_queue:RedisQueue",
        "in_memory": "hcwave.adapters.queue.in_memory:InMemoryQueue",
    },
    "llm": {
        "azure_openai": "hcwave.adapters.llm.providers:AzureOpenAIProvider",
        "anthropic_foundry": "hcwave.adapters.llm.providers:AnthropicFoundryProvider",
        "openai_compatible": "hcwave.adapters.llm.providers:OpenAICompatibleProvider",
        "fake": "hcwave.adapters.llm.fake:FakeProvider",
    },
    "knowledge": {
        "azure_ai_search": "hcwave.adapters.knowledge.azure_ai_search:AzureAISearchStore",
        "pgvector": "hcwave.adapters.knowledge.pgvector_store:PgVectorStore",
        "keyword": "hcwave.adapters.knowledge.keyword:KeywordStore",
    },
    "storage": {
        "azure_blob": "hcwave.adapters.storage.azure_blob:AzureBlobStorage",
        "s3": "hcwave.adapters.storage.s3:S3Storage",
        "local": "hcwave.adapters.storage.local:LocalStorage",
    },
    "email": {
        "acs_email": "hcwave.adapters.email.acs_email:AcsEmailSender",
        "smtp": "hcwave.adapters.email.smtp:SmtpEmailSender",
        "console": "hcwave.adapters.email.console:ConsoleEmailSender",
    },
    "sms": {
        "acs_sms": "hcwave.adapters.sms.acs_sms:AcsSmsSender",
        "msg91": "hcwave.adapters.sms.msg91:Msg91SmsSender",
        "console": "hcwave.adapters.sms.console:ConsoleSmsSender",
    },
    "language": {
        "azure_translator": "hcwave.adapters.language.azure_translator:AzureTranslatorDetector",
        "heuristic": "hcwave.adapters.language.heuristic:ScriptHeuristicDetector",
    },
    "safety": {
        "azure_content_safety": "hcwave.adapters.safety.azure_content_safety:AzureContentSafety",
        "none": "hcwave.adapters.safety.noop:NoopSafety",
    },
    "his": {
        "csv": "hcwave.adapters.his.csv_connector:CsvHisConnector",
        "rest_api": "hcwave.adapters.his.rest_api:RestApiHisConnector",
        "fhir": "hcwave.adapters.his.fhir:FhirHisConnector",
        "none": "hcwave.adapters.his.base:NullHisConnector",
    },
    "dashboard": {
        "power_bi": "hcwave.adapters.dashboard.power_bi:PowerBIDashboard",
        "grafana": "hcwave.adapters.dashboard.grafana:GrafanaDashboard",
        "builtin": "hcwave.adapters.dashboard.builtin:BuiltinDashboard",
    },
}


class UnknownProviderError(LookupError):
    """Raised when a provider name is neither registered nor importable."""


def resolve(kind: str, provider: str) -> type[Any]:
    """Imports and returns the class implementing ``provider`` for ``kind``.

    Args:
        kind: Adapter family, for example ``messaging``.
        provider: Registered name, or a ``module:Class`` path.

    Returns:
        The implementation class.

    Raises:
        UnknownProviderError: If the provider cannot be resolved.
    """
    target = REGISTRY.get(kind, {}).get(provider, provider)
    if ":" not in target:
        known = ", ".join(sorted(REGISTRY.get(kind, {})))
        raise UnknownProviderError(f"Unknown {kind} provider '{provider}'. Known: {known}")
    module_name, _, class_name = target.partition(":")
    module = importlib.import_module(module_name)
    try:
        return getattr(module, class_name)
    except AttributeError as exc:
        raise UnknownProviderError(f"{target} not found") from exc
