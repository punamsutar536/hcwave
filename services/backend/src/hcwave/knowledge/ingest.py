"""Indexes each hospital's FAQ/policy content into the knowledge store.

Content files (``knowledge_files`` in the hospital YAML) contain::

    documents:
      - id: timings
        title: OPD timings
        content: ...
        language: en      # optional

Usage::

    hcwave-knowledge                 # all hospitals
    hcwave-knowledge --hospital demo-hospital
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path

from hcwave.adapters.knowledge.base import KnowledgeDocument
from hcwave.config import find_config_dir, get_settings
from hcwave.config.loader import read_yaml
from hcwave.config.schema import HospitalConfig
from hcwave.core.container import Container
from hcwave.core.logging import configure_logging
from hcwave.domain.tenants import sync_hospitals

_log = logging.getLogger(__name__)


def load_documents(hospital: HospitalConfig, config_dir: Path) -> list[KnowledgeDocument]:
    """Reads every configured content file for a hospital."""
    documents: list[KnowledgeDocument] = []
    for relative in hospital.knowledge_files:
        path = config_dir / relative
        for item in read_yaml(path).get("documents", []):
            documents.append(
                KnowledgeDocument(
                    id=str(item["id"]),
                    title=item["title"],
                    content=" ".join(str(item["content"]).split()),
                    source=relative,
                    language=item.get("language", "en"),
                )
            )
    return documents


async def reindex(container: Container, hospital_ids: list[str] | None = None) -> dict[str, int]:
    """Replaces the indexed content for the given (or all) hospitals."""
    config_dir = find_config_dir()
    results: dict[str, int] = {}
    for hospital in container.settings.hospitals.values():
        if hospital_ids and hospital.id not in hospital_ids:
            continue
        documents = load_documents(hospital, config_dir)
        results[hospital.id] = await container.knowledge.replace_all(hospital.id, documents)
        _log.info("indexed %s documents for %s", results[hospital.id], hospital.id)
    return results


async def amain(hospital: str | None) -> None:
    """Async entry point."""
    settings = get_settings()
    configure_logging(settings.app.log_level, "text")
    container = Container(settings)
    try:
        await sync_hospitals(container.db, settings)
        print(await reindex(container, [hospital] if hospital else None))  # noqa: T201
    finally:
        await container.aclose()


def main() -> None:
    """Console entry point (``hcwave-knowledge``)."""
    parser = argparse.ArgumentParser(description="Index hospital FAQ content")
    parser.add_argument("--hospital", help="Only this hospital ID")
    asyncio.run(amain(parser.parse_args().hospital))


if __name__ == "__main__":
    main()
