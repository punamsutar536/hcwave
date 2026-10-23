"""pgvector knowledge store – keeps RAG inside PostgreSQL.

Portable to any managed Postgres with the ``vector`` extension (Azure Database
for PostgreSQL, Amazon RDS/Aurora, Google Cloud SQL/AlloyDB).
"""

from __future__ import annotations

import uuid

from sqlalchemy import text

from hcwave.adapters.base import AdapterSettings
from hcwave.adapters.knowledge.base import KnowledgeDocument, KnowledgeHit, KnowledgeStore


class PgVectorSettings(AdapterSettings):
    """Settings for pgvector (none beyond the shared database)."""


def _vector_literal(vector: list[float]) -> str:
    return "[" + ",".join(f"{v:.6f}" for v in vector) + "]"


class PgVectorStore(KnowledgeStore):
    """Knowledge store using the ``knowledge_chunks.embedding`` vector column."""

    settings_model = PgVectorSettings
    name = "pgvector"

    async def search(
        self, hospital_id: str, query: str, language: str, top_k: int
    ) -> list[KnowledgeHit]:
        """Cosine-similarity search within the hospital."""
        vector = (await self.llm.embed([query], self.embedding_profile))[0]
        async with self.db.tenant_session(hospital_id) as session:
            rows = await session.execute(
                text(
                    "SELECT id, title, content, source, "
                    "1 - (embedding <=> CAST(:vec AS vector)) AS score "
                    "FROM knowledge_chunks WHERE hospital_id = :hid AND embedding IS NOT NULL "
                    "ORDER BY embedding <=> CAST(:vec AS vector) LIMIT :k"
                ),
                {"vec": _vector_literal(vector), "hid": hospital_id, "k": top_k},
            )
            return [
                KnowledgeHit(str(r.id), r.title, r.content, r.source, float(r.score)) for r in rows
            ]

    async def replace_all(self, hospital_id: str, documents: list[KnowledgeDocument]) -> int:
        """Re-embeds and replaces the hospital's chunks in one transaction."""
        vectors = await self.llm.embed(
            [f"{d.title}\n{d.content}" for d in documents], self.embedding_profile
        )
        async with self.db.tenant_session(hospital_id) as session:
            await session.execute(
                text("DELETE FROM knowledge_chunks WHERE hospital_id = :hid"), {"hid": hospital_id}
            )
            for doc, vector in zip(documents, vectors, strict=True):
                await session.execute(
                    text(
                        "INSERT INTO knowledge_chunks (id, hospital_id, source, title, content, language, embedding) "
                        "VALUES (:id, :hid, :source, :title, :content, :lang, CAST(:vec AS vector))"
                    ),
                    {
                        "id": uuid.uuid4(),
                        "hid": hospital_id,
                        "source": doc.source,
                        "title": doc.title,
                        "content": doc.content,
                        "lang": doc.language,
                        "vec": _vector_literal(vector),
                    },
                )
        return len(documents)
