"""Concrete LLM providers.

* ``azure_openai`` – Azure OpenAI in Microsoft Foundry (default). Keyless via
  workload identity, or via an Azure API Management AI gateway endpoint.
* ``anthropic_foundry`` – Claude in Microsoft Foundry (Anthropic Messages API).
* ``openai_compatible`` – any OpenAI-compatible endpoint (vLLM, Ollama,
  LiteLLM, a Bedrock gateway...) for portability to other clouds.
"""

from __future__ import annotations

from typing import Any

from langchain_core.embeddings import Embeddings
from langchain_core.language_models import BaseChatModel

from hcwave.adapters.base import AdapterSettings
from hcwave.adapters.llm.base import LLMProvider
from hcwave.config.schema import LLMProfile

_COGNITIVE_SCOPE = "https://cognitiveservices.azure.com/.default"


def _common(profile: LLMProfile) -> dict[str, Any]:
    """Arguments shared by every chat model; omits unset sampling params."""
    kwargs: dict[str, Any] = {
        "timeout": profile.timeout_seconds,
        "max_retries": profile.max_retries,
    }
    if profile.temperature is not None:
        kwargs["temperature"] = profile.temperature
    if profile.max_tokens is not None:
        kwargs["max_tokens"] = profile.max_tokens
    return kwargs


class AzureOpenAISettings(AdapterSettings):
    """Settings for Azure OpenAI.

    Attributes:
        endpoint: Foundry/Azure OpenAI endpoint, or the APIM gateway URL.
        api_version: Azure OpenAI data-plane API version.
        api_key: Optional key (or APIM subscription key). Empty = Entra ID.
    """

    endpoint: str
    api_version: str = "2025-04-01-preview"
    api_key: str = ""


class AzureOpenAIProvider(LLMProvider):
    """Azure OpenAI chat and embeddings."""

    settings_model = AzureOpenAISettings
    name = "azure_openai"
    system = "az.ai.openai"

    def _auth(self) -> dict[str, Any]:
        if self.config.api_key:
            return {"api_key": self.config.api_key}
        return {
            "azure_ad_token_provider": self.ctx.credentials.bearer_token_provider(_COGNITIVE_SCOPE),
            "azure_ad_async_token_provider": self.ctx.credentials.async_bearer_token_provider(
                _COGNITIVE_SCOPE
            ),
        }

    def chat_model(self, profile: LLMProfile) -> BaseChatModel:
        """Returns an ``AzureChatOpenAI`` bound to the profile's deployment."""
        from langchain_openai import AzureChatOpenAI

        return AzureChatOpenAI(
            azure_endpoint=self.config.endpoint,
            azure_deployment=profile.model,
            api_version=self.config.api_version,
            **self._auth(),
            **_common(profile),
        )

    def embeddings(self, profile: LLMProfile) -> Embeddings:
        """Returns ``AzureOpenAIEmbeddings`` for the profile's deployment."""
        from langchain_openai import AzureOpenAIEmbeddings

        return AzureOpenAIEmbeddings(
            azure_endpoint=self.config.endpoint,
            azure_deployment=profile.model,
            api_version=self.config.api_version,
            dimensions=profile.dimensions,
            **self._auth(),
        )


class AnthropicFoundrySettings(AdapterSettings):
    """Settings for Claude in Microsoft Foundry.

    Attributes:
        base_url: Foundry Anthropic endpoint,
            e.g. ``https://<resource>.services.ai.azure.com/anthropic``.
        api_key: Foundry resource key (secret, from env).
    """

    base_url: str
    api_key: str


class AnthropicFoundryProvider(LLMProvider):
    """Claude models served by Microsoft Foundry."""

    settings_model = AnthropicFoundrySettings
    name = "anthropic_foundry"
    system = "anthropic"

    def chat_model(self, profile: LLMProfile) -> BaseChatModel:
        """Returns a ``ChatAnthropic`` pointed at the Foundry endpoint."""
        from langchain_anthropic import ChatAnthropic

        kwargs = _common(profile)
        kwargs.setdefault("max_tokens", 1024)  # required by the Messages API
        return ChatAnthropic(
            model=profile.model,
            base_url=self.config.base_url,
            api_key=self.config.api_key,
            **kwargs,
        )


class OpenAICompatibleSettings(AdapterSettings):
    """Settings for an OpenAI-compatible endpoint."""

    base_url: str
    api_key: str = "not-needed"


class OpenAICompatibleProvider(LLMProvider):
    """Any OpenAI-compatible chat/embeddings endpoint."""

    settings_model = OpenAICompatibleSettings
    name = "openai_compatible"
    system = "openai"

    def chat_model(self, profile: LLMProfile) -> BaseChatModel:
        """Returns a ``ChatOpenAI`` pointed at ``base_url``."""
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=profile.model,
            base_url=self.config.base_url,
            api_key=self.config.api_key,
            **_common(profile),
        )

    def embeddings(self, profile: LLMProfile) -> Embeddings:
        """Returns ``OpenAIEmbeddings`` pointed at ``base_url``."""
        from langchain_openai import OpenAIEmbeddings

        return OpenAIEmbeddings(
            model=profile.model,
            base_url=self.config.base_url,
            api_key=self.config.api_key,
            dimensions=profile.dimensions,
            check_embedding_ctx_length=False,
        )
