"""Memory lifecycle coordination: extract, approve, reject, delete, search (spec §13).

The service sits between the API routes and the storage layers. It owns every
side effect beyond the plain status flip: candidate extraction (with secret
redaction, spec §34), the vector upsert/removal in the ``memories`` collection,
and the Obsidian mirror files under ``data/vault/_memories``. The mirror is a
projection of the authoritative DB row: written on approve, removed on
reject/delete.

``MemoryNotFoundError`` and ``MemoryStateError`` are raised for the 404/409
route semantics; ``MemoryExtractionError`` bubbles from the extractor (502).
"""

from __future__ import annotations

from pathlib import Path

from app.core.logging import get_logger
from app.domain.models.memory import Memory
from app.providers.embeddings.base import EmbeddingProvider
from app.repositories.memory_repository import MemoryRepository
from app.schemas.memory import ConversationTurn
from app.services.memory_extractor import MemoryExtractionError, MemoryExtractor
from app.services.redaction import redact_secrets
from app.services.vault_service import VaultService
from app.vector.collections import CONTENT_FIELD, MEMORY_ID_FIELD, MEMORY_TYPE_FIELD
from app.vector.qdrant import QdrantVectorStore, VectorPoint


class MemoryNotFoundError(Exception):
    """Raised when a memory row does not exist (routes map to 404)."""


class MemoryStateError(Exception):
    """Raised when a lifecycle transition is invalid (routes map to 409)."""


class MemoryService:
    """Coordinates repository, vectors, vault mirror, embeddings, extractor."""

    def __init__(
        self,
        memory_repository: MemoryRepository,
        store: QdrantVectorStore,
        embeddings: EmbeddingProvider,
        vault: VaultService | None = None,
        extractor: MemoryExtractor | None = None,
    ) -> None:
        self._repository = memory_repository
        # The store must already be scoped to the memories collection; the
        # wiring layer (main.py) constructs it with collection=MEMORIES_COLLECTION.
        # ``upsert_chunks`` is the store's only upsert entry point and is
        # collection-agnostic, so it doubles as the memory-point upsert.
        self._store = store
        self._embeddings = embeddings
        self._vault = vault
        self._extractor = extractor
        self._logger = get_logger("memory_service")
        # Mirror paths written by this process, keyed by memory id. The mirror
        # filename is content-derived and deduped by existence (Obsidian
        # style), so the exact path used at write time must be remembered to
        # remove the right file later; a restart falls back to recomputation
        # (best effort — see _delete_mirror).
        self._mirror_paths: dict[str, Path] = {}

    async def extract(self, conversation: list[ConversationTurn]) -> list[Memory]:
        """Extract candidates and persist them redacted with status candidate."""
        if self._extractor is None:
            raise MemoryExtractionError("memory extractor is not configured")
        candidates = await self._extractor.extract(conversation)
        redacted = [{**c, "content": redact_secrets(c["content"])} for c in candidates]
        return list(await self._repository.create_candidates(redacted))

    async def approve(self, memory_id: str) -> Memory:
        """Flip to approved, embed + upsert the vector point, write the mirror.

        The store and vault calls repeat the ``status`` payload so consumers
        could later filter by it; approved rows are the only ones retrievable
        by ``search_approved``.
        """
        memory = await self._flip_candidate(memory_id, "approved")
        vector = await self._embeddings.embed(memory.content)
        await self._store.upsert_chunks(
            [
                VectorPoint(
                    id=memory.id,
                    vector=vector,
                    payload={
                        MEMORY_ID_FIELD: memory.id,
                        MEMORY_TYPE_FIELD: memory.memory_type,
                        CONTENT_FIELD: memory.content,
                        "status": memory.status,
                    },
                )
            ]
        )
        if self._vault is not None:
            path = self._vault.write_memory_mirror(
                memory.memory_type,
                memory.content,
                memory.confidence,
                memory.source,
                memory.status,
            )
            self._mirror_paths[memory.id] = path
        return memory

    async def reject(self, memory_id: str) -> Memory:
        """Flip to rejected and remove the vector point and the mirror file.

        Unlike ``approve`` this is an unconditional cleanup operator: it also
        accepts approved memories (undo-approval), removing their vector point
        and mirror file. The route keeps the candidate-only guard, so the API
        still rejects non-candidates with 409 while the service-level
        contract removes artifacts whenever called.
        """
        memory = await self._repository.get(memory_id)
        if memory is None:
            raise MemoryNotFoundError(memory_id)
        flipped = await self._repository.set_status(memory_id, "rejected")
        if flipped is None:
            raise MemoryNotFoundError(memory_id)
        await self._store.delete_by_field(MEMORY_ID_FIELD, memory_id)
        self._delete_mirror(flipped)
        return flipped

    async def delete(self, memory_id: str) -> bool:
        """Remove the row, its vector point, and its mirror file.

        Returns False when the memory is missing (route maps to 404).
        """
        memory = await self._repository.get(memory_id)
        if memory is None:
            return False
        await self._repository.delete(memory_id)
        await self._store.delete_by_field(MEMORY_ID_FIELD, memory_id)
        self._delete_mirror(memory)
        return True

    async def search_approved(self, query: str, top_k: int = 3) -> list[str]:
        """Return the contents of the top-k approved memories for ``query``.

        Only approved memories ever carry a vector point, so the search is
        implicitly scoped to them; used by the chat prompt (spec §25).
        """
        embedding = await self._embeddings.embed(query)
        hits = await self._store.search(embedding, top_k=top_k)
        return [hit.content for hit in hits]

    async def _flip_candidate(self, memory_id: str, status: str) -> Memory:
        """Return the memory flipped to ``status``, or raise the route errors."""
        memory = await self._repository.get(memory_id)
        if memory is None:
            raise MemoryNotFoundError(memory_id)
        if memory.status != "candidate":
            raise MemoryStateError(
                f"only candidate memories can be {'approved' if status == 'approved' else 'rejected'}"
            )
        flipped = await self._repository.set_status(memory_id, status)
        if flipped is None:
            raise MemoryNotFoundError(memory_id)
        return flipped

    def _delete_mirror(self, memory: Memory) -> None:
        """Delete the memory's mirror file when a vault is configured."""
        if self._vault is None:
            return
        path = self._mirror_paths.pop(memory.id, None)
        if path is None:
            # Path lost (e.g. the process restarted between approve and
            # reject): best-effort recomputation. With a same-slug sibling
            # file this can miss or remove the wrong variant; the DB row
            # remains authoritative either way.
            path = self._vault.memory_mirror_path(memory.memory_type, memory.content)
        self._vault.delete(path)