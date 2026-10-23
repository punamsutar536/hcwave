"""Azure AI Search knowledge store: hybrid (keyword + vector) with semantic ranker.

Authenticates with the workload identity (``Search Index Data Contributor`` /
``Reader`` roles); API keys are disabled on the service.
"""

from __future__ import annotations

from typing import Any

from hcwave.adapters.base import AdapterSettings
from hcwave.adapters.knowledge.base import KnowledgeDocument, KnowledgeHit, KnowledgeStore


class AzureAISearchSettings(AdapterSettings):
    """Settings for Azure AI Search.

    Attributes:
        endpoint: ``https://<service>.search.windows.net``.
        index_name: Index holding all hospitals' chunks.
        api_key: Optional admin/query key; empty = Entra ID.
        semantic_configuration: Semantic ranker configuration name.
        use_semantic_ranker: Disable on tiers without the semantic ranker.
        vector_dimensions: Embedding size (must match the embedding profile).
    """

    endpoint: str
    index_name: str = "hcwave-knowledge"
    api_key: str = ""
    semantic_configuration: str = "default"
    use_semantic_ranker: bool = True
    vector_dimensions: int = 1536


class AzureAISearchStore(KnowledgeStore):
    """Knowledge store backed by Azure AI Search."""

    settings_model = AzureAISearchSettings
    name = "azure_ai_search"

    def _credential(self) -> Any:
        if self.config.api_key:
            from azure.core.credentials import AzureKeyCredential

            return AzureKeyCredential(self.config.api_key)
        return self.ctx.credentials.aio

    def _search_client(self) -> Any:
        from azure.search.documents.aio import SearchClient

        return SearchClient(self.config.endpoint, self.config.index_name, self._credential())

    async def search(
        self, hospital_id: str, query: str, language: str, top_k: int
    ) -> list[KnowledgeHit]:
        """Runs a hybrid query filtered to the hospital."""
        from azure.search.documents.models import VectorizedQuery

        vector = (await self.llm.embed([query], self.embedding_profile))[0]
        options: dict[str, Any] = {
            "search_text": query,
            "vector_queries": [
                VectorizedQuery(
                    vector=vector, k_nearest_neighbors=top_k * 2, fields="content_vector"
                )
            ],
            "filter": f"hospital_id eq '{hospital_id.replace(chr(39), chr(39) * 2)}'",
            "top": top_k,
            "select": ["id", "title", "content", "source"],
        }
        if self.config.use_semantic_ranker:
            options["query_type"] = "semantic"
            options["semantic_configuration_name"] = self.config.semantic_configuration
        hits: list[KnowledgeHit] = []
        async with self._search_client() as client:
            results = await client.search(**options)
            async for doc in results:
                reranker = doc.get("@search.reranker_score")
                # Semantic reranker scores run 0..4; hybrid RRF scores are small.
                score = (
                    reranker / 4.0 if reranker is not None else min(doc["@search.score"] * 30, 1.0)
                )
                hits.append(
                    KnowledgeHit(doc["id"], doc["title"], doc["content"], doc["source"], score)
                )
        return hits

    async def ensure_index(self) -> None:
        """Creates or updates the index schema (idempotent)."""
        from azure.search.documents.indexes.aio import SearchIndexClient
        from azure.search.documents.indexes.models import (
            HnswAlgorithmConfiguration,
            SearchableField,
            SearchField,
            SearchFieldDataType,
            SearchIndex,
            SemanticConfiguration,
            SemanticField,
            SemanticPrioritizedFields,
            SemanticSearch,
            SimpleField,
            VectorSearch,
            VectorSearchProfile,
        )

        index = SearchIndex(
            name=self.config.index_name,
            fields=[
                SimpleField(name="id", type=SearchFieldDataType.String, key=True),
                SimpleField(name="hospital_id", type=SearchFieldDataType.String, filterable=True),
                SimpleField(name="language", type=SearchFieldDataType.String, filterable=True),
                SimpleField(name="source", type=SearchFieldDataType.String),
                SearchableField(name="title", type=SearchFieldDataType.String),
                SearchableField(name="content", type=SearchFieldDataType.String),
                SearchField(
                    name="content_vector",
                    type=SearchFieldDataType.Collection(SearchFieldDataType.Single),
                    searchable=True,
                    vector_search_dimensions=self.config.vector_dimensions,
                    vector_search_profile_name="default",
                ),
            ],
            vector_search=VectorSearch(
                algorithms=[HnswAlgorithmConfiguration(name="hnsw")],
                profiles=[VectorSearchProfile(name="default", algorithm_configuration_name="hnsw")],
            ),
            semantic_search=SemanticSearch(
                configurations=[
                    SemanticConfiguration(
                        name=self.config.semantic_configuration,
                        prioritized_fields=SemanticPrioritizedFields(
                            title_field=SemanticField(field_name="title"),
                            content_fields=[SemanticField(field_name="content")],
                        ),
                    )
                ]
            ),
        )
        async with SearchIndexClient(self.config.endpoint, self._credential()) as client:
            await client.create_or_update_index(index)

    async def replace_all(self, hospital_id: str, documents: list[KnowledgeDocument]) -> int:
        """Deletes the hospital's documents and uploads the new set."""
        await self.ensure_index()
        vectors = await self.llm.embed(
            [f"{d.title}\n{d.content}" for d in documents], self.embedding_profile
        )
        async with self._search_client() as client:
            existing = await client.search(
                search_text="*", filter=f"hospital_id eq '{hospital_id}'", select=["id"], top=1000
            )
            stale = [{"id": doc["id"]} async for doc in existing]
            if stale:
                await client.delete_documents(stale)
            if documents:
                await client.upload_documents(
                    [
                        {
                            "id": f"{hospital_id}--{d.id}",
                            "hospital_id": hospital_id,
                            "language": d.language,
                            "source": d.source,
                            "title": d.title,
                            "content": d.content,
                            "content_vector": vector,
                        }
                        for d, vector in zip(documents, vectors, strict=True)
                    ]
                )
        return len(documents)
