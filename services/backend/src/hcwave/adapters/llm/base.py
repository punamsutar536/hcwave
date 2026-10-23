"""LLM provider contract and the gateway used by business code.

Business code asks for a *profile* (``intent``, ``reply``, ``tagger``,
``embedding``) instead of a model. The profile, defined in YAML, names the
provider and model, so moving intent detection from GPT-5-mini to Claude
Haiku – or to a self-hosted model on another cloud – is a config change.

All calls are wrapped in OpenTelemetry GenAI spans that land in Application
Insights for Microsoft Foundry tracing and evaluations.
"""

from __future__ import annotations

import abc
from typing import Any, TypeVar

from langchain_core.embeddings import Embeddings
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from pydantic import BaseModel

from hcwave.adapters.base import Adapter, AdapterContext
from hcwave.config.schema import LLMProfile, LLMSection
from hcwave.core.errors import ConfigurationError
from hcwave.core.registry import resolve
from hcwave.core.telemetry import llm_span, record_llm_content

SchemaT = TypeVar("SchemaT", bound=BaseModel)


class LLMProvider(Adapter, abc.ABC):
    """Creates LangChain chat and embedding models for a provider."""

    #: Value for the ``gen_ai.system`` span attribute.
    system: str = "unknown"

    @abc.abstractmethod
    def chat_model(self, profile: LLMProfile) -> BaseChatModel:
        """Returns a chat model configured for ``profile``."""

    def embeddings(self, profile: LLMProfile) -> Embeddings:
        """Returns an embeddings model configured for ``profile``."""
        raise ConfigurationError(f"{self.name} does not provide embeddings")


class LLMGateway:
    """Resolves profiles to models and wraps calls with tracing.

    Args:
        section: The ``llm`` configuration section.
        ctx: Adapter context.
    """

    def __init__(self, section: LLMSection, ctx: AdapterContext) -> None:
        self._section = section
        self._ctx = ctx
        self._providers: dict[str, LLMProvider] = {}
        self._chat_cache: dict[str, BaseChatModel] = {}

    def profile(self, name: str) -> LLMProfile:
        """Returns the named profile.

        Raises:
            ConfigurationError: If the profile is not configured.
        """
        try:
            return self._section.profiles[name]
        except KeyError as exc:
            raise ConfigurationError(f"llm.profiles.{name} is not configured") from exc

    def _provider(self, name: str) -> LLMProvider:
        if name not in self._providers:
            cls = resolve("llm", name)
            self._providers[name] = cls(self._section.providers.get(name) or {}, self._ctx)
        return self._providers[name]

    def chat(self, profile_name: str) -> BaseChatModel:
        """Returns the (cached) chat model for a profile."""
        if profile_name not in self._chat_cache:
            profile = self.profile(profile_name)
            self._chat_cache[profile_name] = self._provider(profile.provider).chat_model(profile)
        return self._chat_cache[profile_name]

    async def structured(
        self, profile_name: str, schema: type[SchemaT], system: str, user: str
    ) -> SchemaT:
        """Calls a model and parses its answer into ``schema``.

        Args:
            profile_name: LLM profile to use.
            schema: Pydantic model describing the expected output.
            system: System prompt.
            user: User content.

        Returns:
            A validated ``schema`` instance.
        """
        profile = self.profile(profile_name)
        provider = self._provider(profile.provider)
        messages: list[BaseMessage] = [SystemMessage(system), HumanMessage(user)]
        with llm_span(
            "chat", provider.system, profile.model, **{"hcwave.profile": profile_name}
        ) as span:
            runnable = self.chat(profile_name).with_structured_output(schema)
            result = await runnable.ainvoke(messages)
            record_llm_content(span, user, result.model_dump_json() if result else "")
        if isinstance(result, dict):  # some providers return dicts
            return schema.model_validate(result)
        return result  # type: ignore[return-value]

    async def complete(self, profile_name: str, system: str, user: str) -> str:
        """Returns a plain-text completion."""
        profile = self.profile(profile_name)
        provider = self._provider(profile.provider)
        with llm_span(
            "chat", provider.system, profile.model, **{"hcwave.profile": profile_name}
        ) as span:
            response = await self.chat(profile_name).ainvoke(
                [SystemMessage(system), HumanMessage(user)]
            )
            usage: dict[str, Any] = getattr(response, "usage_metadata", None) or {}
            if usage:
                span.set_attribute("gen_ai.usage.input_tokens", usage.get("input_tokens", 0))
                span.set_attribute("gen_ai.usage.output_tokens", usage.get("output_tokens", 0))
            text = response.content if isinstance(response.content, str) else str(response.content)
            record_llm_content(span, user, text)
        return text

    async def embed(self, texts: list[str], profile_name: str = "embedding") -> list[list[float]]:
        """Embeds texts with the embedding profile."""
        profile = self.profile(profile_name)
        provider = self._provider(profile.provider)
        with llm_span("embeddings", provider.system, profile.model):
            return await provider.embeddings(profile).aembed_documents(texts)

    async def aclose(self) -> None:
        """Closes provider clients."""
        for provider in self._providers.values():
            await provider.aclose()
