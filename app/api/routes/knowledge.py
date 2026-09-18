"""Knowledge-map endpoint: on-demand "Qué sé sobre X?" maps (Phase 7).

``GET /knowledge/map`` embeds the topic, retrieves the top chunks and
approved memories, and asks the LLM for a hierarchical Spanish markdown map;
the response carries the echo of the topic plus the generated ``map``.
Response-only in v1: nothing is persisted to the vault.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from app.api.dependencies import get_knowledge_map_service
from app.services.knowledge_map import KnowledgeMapService


class KnowledgeMapRead(BaseModel):
    """The on-demand knowledge map for a topic."""

    topic: str
    map: str


router = APIRouter(prefix="/knowledge", tags=["knowledge"])


@router.get("/map", response_model=KnowledgeMapRead)
async def knowledge_map(
    topic: Annotated[str, Query(min_length=1)],
    knowledge_map_service: Annotated[
        KnowledgeMapService, Depends(get_knowledge_map_service)
    ],
    project_id: str | None = None,
) -> KnowledgeMapRead:
    """Return the Spanish hierarchical knowledge map markdown for ``topic``.

    An empty or missing topic is rejected by the query validation (422). The
    map is built on demand from approved memories and indexed chunks (scoped
    to ``project_id`` when given) and never persisted to the vault.
    """
    markdown = await knowledge_map_service.knowledge_map(
        topic, project_id=project_id
    )
    return KnowledgeMapRead(topic=topic, map=markdown)