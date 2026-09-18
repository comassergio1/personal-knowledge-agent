"""Pydantic schemas for memories (spec §13), decoupled from the ORM model."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from fastapi import Query
from pydantic import BaseModel, ConfigDict, Field

from app.domain.models.memory import MEMORY_STATUSES, MEMORY_TYPES

# Single source of truth lives in the domain module; the Literals below
# validate at the schema/query layer, never in the ORM model.
MemoryType = Literal[*MEMORY_TYPES]
MemoryStatus = Literal[*MEMORY_STATUSES]

# Query-parameter validators for the list endpoint (`?type=` / `?status=`).
MemoryTypeQuery = Annotated[MemoryType | None, Query()]
MemoryStatusQuery = Annotated[MemoryStatus | None, Query()]


class ConversationTurn(BaseModel):
    """One message of a conversation handed to the extractor."""

    role: str
    content: str


class MemoryRead(BaseModel):
    """A memory as returned to API consumers."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    memory_type: str
    content: str
    source: str | None
    confidence: float
    status: str
    created_at: datetime
    updated_at: datetime


class MemoryList(BaseModel):
    """A (currently unpaginated) list of memories."""

    items: list[MemoryRead]
    total: int


class MemoryExtractRequest(BaseModel):
    """Payload for the explicit extraction endpoint (unit 2's route)."""

    conversation: list[ConversationTurn] = Field(min_length=1)


class MemoryExtractResponse(BaseModel):
    """Extraction outcome: the redacted candidates produced from a conversation."""

    candidates: list[MemoryRead]