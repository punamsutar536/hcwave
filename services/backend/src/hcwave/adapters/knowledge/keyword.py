"""Keyword (full-text) knowledge store – no embeddings required.

Uses PostgreSQL full-text search with the language-neutral ``simple``
configuration. Handy for local development and as a fallback.
"""

from __future__ import annotations

import uuid

from sqlalchemy import text

from hcwave.adapters.base import AdapterSettings
from hcwave.adapters.knowledge.base import KnowledgeDocument, KnowledgeHit, KnowledgeStore


class KeywordSettings(AdapterSettings):
    """Settings for the keyword store."""


class KeywordStore(KnowledgeStore):
    """Knowledge store using ``ts_rank`` over ``knowledge_chunks``."""

    settings_model = KeywordSettings
    name = "keyword"

    async def search(
        self, hospital_id: str, query: str, language: str, top_k: int
    ) -> list[KnowledgeHit]:
        """Full-text search; any query word may match (OR semantics)."""
        words = [
            w
            for w in "".join(c if c.isalnum() else " " for c in query.lower()).split()
            if len(w) > 2
        ]
        if not words:
            return []
        async with self.db.tenant_session(hospital_id) as session:
            rows = await session.execute(
                text(
                    "SELECT id, title, content, source, "
                    "ts_rank(to_tsvector('simple', title || ' ' || content), to_tsquery('simple', :q)) AS score "
                    "FROM knowledge_chunks WHERE hospital_id = :hid "
                    "AND to_tsvector('simple', title || ' ' || content) @@ to_tsquery('simple', :q) "
                    "ORDER BY score DESC LIMIT :k"
                ),
                {"q": " | ".join(words), "hid": hospital_id, "k": top_k},
            )
            # ts_rank is unbounded but small; scale into 0..1 for thresholds.
            return [
                KnowledgeHit(str(r.id), r.title, r.content, r.source, min(float(r.score) * 10, 1.0))
                for r in rows
            ]

    async def replace_all(self, hospital_id: str, documents: list[KnowledgeDocument]) -> int:
        """Replaces the hospital's chunks."""
        async with self.db.tenant_session(hospital_id) as session:
            await session.execute(
                text("DELETE FROM knowledge_chunks WHERE hospital_id = :hid"), {"hid": hospital_id}
            )
            for doc in documents:
                await session.execute(
                    text(
                        "INSERT INTO knowledge_chunks (id, hospital_id, source, title, content, language) "
                        "VALUES (:id, :hid, :source, :title, :content, :lang)"
                    ),
                    {
                        "id": uuid.uuid4(),
                        "hid": hospital_id,
                        "source": doc.source,
                        "title": doc.title,
                        "content": doc.content,
                        "lang": doc.language,
                    },
                )
        return len(documents)
