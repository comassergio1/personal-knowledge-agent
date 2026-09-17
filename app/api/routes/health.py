"""Health probe: app reachability with soft Qdrant/Ollama checks (spec §41).

Probes are best-effort and never raise: an unreachable backend reports
``False`` and the endpoint still answers 200 (``"status": "ok"``).
"""

from __future__ import annotations

from typing import Annotated

import httpx
from fastapi import APIRouter, Depends

from app.api.dependencies import get_settings, get_vector_store
from app.core.config import Settings
from app.core.logging import get_logger
from app.vector.collections import DEFAULT_COLLECTION
from app.vector.qdrant import QdrantVectorStore

router = APIRouter(tags=["health"])

_logger = get_logger("health")


async def _probe_qdrant(vector_store: QdrantVectorStore) -> bool:
    """True when the vector store answers a collection probe; never raises."""
    probe = getattr(vector_store, "collection_exists", None)
    if probe is None:
        client = getattr(vector_store, "_client", None)
        probe = getattr(client, "collection_exists", None) if client is not None else None
    if probe is None:
        return False
    try:
        return bool(await probe(DEFAULT_COLLECTION))
    except Exception:  # noqa: BLE001 - soft health semantics (spec §41): an
        # unreachable qdrant backend (or any probe failure) reads as False.
        return False


async def _probe_ollama(base_url: str) -> bool:
    """True when the local Ollama server answers /api/tags; never raises."""
    try:
        async with httpx.AsyncClient(base_url=base_url, timeout=2.0) as client:
            response = await client.get("/api/tags")
            response.raise_for_status()
        return True
    except httpx.HTTPError:
        return False


@router.get("/health")
async def health(
    settings: Annotated[Settings, Depends(get_settings)],
    vector_store: Annotated[QdrantVectorStore, Depends(get_vector_store)],
) -> dict[str, object]:
    """Report application health plus soft backend reachability flags."""
    qdrant_ok = await _probe_qdrant(vector_store)
    ollama_ok = await _probe_ollama(settings.ollama_base_url)
    _logger.info("health probe completed", extra={"qdrant": qdrant_ok, "ollama": ollama_ok})
    return {"status": "ok", "qdrant": qdrant_ok, "ollama": ollama_ok}