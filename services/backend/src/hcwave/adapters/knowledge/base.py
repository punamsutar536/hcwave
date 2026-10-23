"""Knowledge retrieval contract (RAG over hospital FAQs and policies).

The assistant only answers from the hospital's own content. Each store keeps
documents partitioned by ``hospital_id`` and every query filters on it.
"""

from __future__ import annotations

import abc
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from hcwave.adapters.base import Adapter, AdapterContext
from hcwave.adapters.llm.base import LLMGateway
from hcwave.db.session import Database


@dataclass(frozen=True)
class KnowledgeDocument:
    """A chunk of hospital content to index."""

    id: str
    title: str
    content: str
    source: str
    language: str = "en"
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class KnowledgeHit:
    """A retrieved chunk with a relevance score normalised to 0..1."""

    id: str
    title: str
    content: str
    source: str
    score: float


class KnowledgeStore(Adapter, abc.ABC):
    """Abstract knowledge store.

    Args:
        raw_settings: Provider settings.
        ctx: Adapter context.
        db: Database (for Postgres-backed stores).
        llm: LLM gateway (for embeddings).
        embedding_profile: LLM profile used to embed text.
    """

    def __init__(
        self,
        raw_settings: Mapping[str, Any],
        ctx: AdapterContext,
        *,
        db: Database,
        llm: LLMGateway,
        embedding_profile: str = "embedding",
    ) -> None:
        super().__init__(raw_settings, ctx)
        self.db = db
        self.llm = llm
        self.embedding_profile = embedding_profile

    @abc.abstractmethod
    async def search(
        self, hospital_id: str, query: str, language: str, top_k: int
    ) -> list[KnowledgeHit]:
        """Returns the most relevant chunks for ``query`` within one hospital."""

    @abc.abstractmethod
    async def replace_all(self, hospital_id: str, documents: list[KnowledgeDocument]) -> int:
        """Replaces a hospital's indexed content. Returns the number indexed."""
