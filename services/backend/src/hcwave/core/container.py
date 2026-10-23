"""Dependency container: builds every adapter from configuration once.

API, worker and jobs all create one :class:`Container` at start-up and pass it
down. Swapping a provider in YAML changes what gets built here – no business
code imports a concrete adapter.
"""

from __future__ import annotations

import logging
from typing import Any

from hcwave.adapters.base import AdapterContext
from hcwave.adapters.dashboard.base import DashboardProvider
from hcwave.adapters.email.base import EmailSender
from hcwave.adapters.his.base import HisConnector
from hcwave.adapters.knowledge.base import KnowledgeStore
from hcwave.adapters.language.base import LanguageDetector
from hcwave.adapters.llm.base import LLMGateway
from hcwave.adapters.messaging.base import MessagingProvider
from hcwave.adapters.queue.base import MessageQueue
from hcwave.adapters.safety.base import ContentSafety
from hcwave.adapters.sms.base import SmsSender
from hcwave.adapters.storage.base import ObjectStorage
from hcwave.config.schema import AdapterSection, HospitalConfig, Settings
from hcwave.core.identity import CredentialFactory
from hcwave.core.registry import resolve
from hcwave.db.session import Database

_log = logging.getLogger(__name__)


class Container:
    """Holds configured adapters and shared services.

    Args:
        settings: Validated settings.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.credentials = CredentialFactory(settings.identity)
        self.ctx = AdapterContext(settings=settings, credentials=self.credentials)
        self.db = Database(settings.database, self.credentials)
        self.llm = LLMGateway(settings.llm, self.ctx)

        self.messaging: MessagingProvider = self._build("messaging", settings.messaging)
        self.queue: MessageQueue = self._build("queue", settings.queue)
        self.storage: ObjectStorage = self._build("storage", settings.storage)
        self.email: EmailSender = self._build("email", settings.email)
        self.sms: SmsSender = self._build("sms", settings.sms)
        self.language: LanguageDetector = self._build("language", settings.language)
        self.safety: ContentSafety = self._build("safety", settings.safety)
        self.dashboard: DashboardProvider = self._build("dashboard", settings.dashboard)
        self.knowledge: KnowledgeStore = self._build(
            "knowledge",
            settings.knowledge,
            db=self.db,
            llm=self.llm,
            embedding_profile=settings.knowledge.embedding_profile,
        )
        self._his: dict[str, HisConnector] = {
            "__default__": self._build("his", settings.his, storage=self.storage)
        }
        _log.info(
            "container ready: messaging=%s queue=%s storage=%s knowledge=%s",
            settings.messaging.provider,
            settings.queue.provider,
            settings.storage.provider,
            settings.knowledge.provider,
        )

    def _build(self, kind: str, section: AdapterSection, **deps: Any) -> Any:
        cls = resolve(kind, section.provider)
        return cls(section.provider_settings(), self.ctx, **deps)

    def his_for(self, hospital: HospitalConfig) -> HisConnector:
        """Returns the HIS connector for a hospital.

        A hospital may override the platform default in its own YAML with
        ``his: {provider: rest_api, providers: {rest_api: {...}}}``.
        """
        if not hospital.his:
            return self._his["__default__"]
        if hospital.id not in self._his:
            section = AdapterSection.model_validate(hospital.his)
            self._his[hospital.id] = self._build("his", section, storage=self.storage)
        return self._his[hospital.id]

    def hospital(self, hospital_id: str) -> HospitalConfig:
        """Returns a hospital's configuration.

        Raises:
            KeyError: If the hospital is not configured.
        """
        return self.settings.hospitals[hospital_id]

    async def aclose(self) -> None:
        """Closes every adapter and the database pool."""
        adapters = [
            self.messaging,
            self.queue,
            self.storage,
            self.email,
            self.sms,
            self.language,
            self.safety,
            self.dashboard,
            self.knowledge,
            *self._his.values(),
        ]
        for adapter in adapters:
            try:
                await adapter.aclose()
            except Exception:  # noqa: BLE001 - best effort on shutdown
                _log.exception("error closing %s", type(adapter).__name__)
        await self.llm.aclose()
        await self.credentials.aclose()
        await self.db.dispose()
