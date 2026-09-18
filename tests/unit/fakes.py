"""Offline fakes shared by unit tests: embedding provider, vector store, stack.

Kept out of ``conftest.py`` because pytest would treat fixture modules as
import-time machinery; plain classes here are imported by the test modules
that need them.
"""

from __future__ import annotations

from app.repositories.document_repository import DocumentRepository
from app.repositories.project_repository import ProjectRepository
from app.services.ingestion_service import IngestionService
from app.services.sync_service import SyncService
from app.services.vault_service import VaultService
from app.vector.collections import DOCUMENT_ID_FIELD
from app.vector.qdrant import VectorPoint


class FakeEmbeddingProvider:
    """Fixed-size embedding provider recording every embedded text."""

    EMBEDDING_SIZE = 4

    def __init__(self) -> None:
        self.embedded: list[str] = []

    async def embed(self, text: str) -> list[float]:
        self.embedded.append(text)
        return [0.1, 0.2, 0.3, 0.4]


class CapturingVectorStore:
    """In-memory store capturing upserts and per-document deletes."""

    def __init__(self) -> None:
        self.upserted: list[VectorPoint] = []
        self.deleted: list[str] = []

    async def upsert_chunks(self, points: list[VectorPoint]) -> None:
        self.upserted.extend(points)

    async def delete_by_document(self, document_id: str) -> None:
        self.deleted.append(document_id)
        self.upserted = [
            point
            for point in self.upserted
            if point.payload[DOCUMENT_ID_FIELD] != document_id
        ]


def build_stack(db_session, tmp_path):
    """One IngestionService + SyncService over a shared in-memory DB and vault."""
    vault = VaultService(tmp_path / "vault")
    store = CapturingVectorStore()
    documents = DocumentRepository(db_session)
    projects = ProjectRepository(db_session)
    ingestion = IngestionService(
        documents,
        store,  # type: ignore[arg-type]
        FakeEmbeddingProvider(),  # type: ignore[arg-type]
        vault=vault,
        projects=projects,
    )
    sync = SyncService(vault, documents, projects, ingestion)
    return ingestion, sync, store, vault, documents, projects