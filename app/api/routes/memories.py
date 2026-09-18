"""Memory endpoints: list, detail, extract, approve/reject, delete (spec §13).

Unit 2 scope: ``approve``/``reject``/``delete`` route through ``MemoryService``
so status changes carry their full side effects (vector upsert/removal, vault
mirror write/removal), and ``POST /memories/extract`` turns a conversation into
redacted candidates. 404/409 semantics stay identical to unit 1; extractor
failures surface as 502.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.dependencies import get_memory_repository, get_memory_service
from app.domain.models.memory import Memory
from app.repositories.memory_repository import MemoryRepository
from app.schemas.memory import (
    MemoryExtractRequest,
    MemoryExtractResponse,
    MemoryList,
    MemoryRead,
    MemoryStatusQuery,
    MemoryTypeQuery,
)
from app.services.memory_extractor import MemoryExtractionError
from app.services.memory_service import (
    MemoryNotFoundError,
    MemoryService,
    MemoryStateError,
)

router = APIRouter(prefix="/memories", tags=["memories"])

# Roles accepted by the extractor prompt; anything else is a 422.
_ALLOWED_ROLES = {"user", "assistant"}


def _read(memory: Memory) -> MemoryRead:
    """Map a persisted memory to its API shape."""
    return MemoryRead.model_validate(memory)


@router.get("", response_model=MemoryList)
async def list_memories(
    repository: Annotated[MemoryRepository, Depends(get_memory_repository)],
    type: MemoryTypeQuery = None,
    status: MemoryStatusQuery = None,
) -> MemoryList:
    """Return memories, newest first, optionally filtered by type/status."""
    items = await repository.list(memory_type=type, status=status)
    return MemoryList(items=[_read(m) for m in items], total=len(items))


@router.get("/{memory_id}", response_model=MemoryRead)
async def get_memory(
    memory_id: str,
    repository: Annotated[MemoryRepository, Depends(get_memory_repository)],
) -> MemoryRead:
    """Return one memory; 404 when it is missing."""
    memory = await repository.get(memory_id)
    if memory is None:
        raise HTTPException(status_code=404, detail="Memory not found")
    return _read(memory)


@router.post("/extract", response_model=MemoryExtractResponse)
async def extract_memories(
    payload: MemoryExtractRequest,
    service: Annotated[MemoryService, Depends(get_memory_service)],
) -> MemoryExtractResponse:
    """Extract candidates from a conversation and persist them (status candidate).

    Empty conversations are rejected by the schema and unknown roles by this
    route (422); LLM extraction failures surface as 502. Candidates are stored
    redacted (spec §34) and stay candidates until approved or rejected.
    """
    for turn in payload.conversation:
        if turn.role not in _ALLOWED_ROLES:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Unknown role: {turn.role!r}; expected one of "
                    "user, assistant"
                ),
            )
    try:
        rows = await service.extract(payload.conversation)
    except MemoryExtractionError as exc:
        raise HTTPException(
            status_code=502, detail=f"Memory extraction failed: {exc}"
        ) from exc
    return MemoryExtractResponse(candidates=[_read(m) for m in rows])


@router.post("/{memory_id}/approve", response_model=MemoryRead)
async def approve_memory(
    memory_id: str,
    service: Annotated[MemoryService, Depends(get_memory_service)],
) -> MemoryRead:
    """Approve a candidate: status flip + vector upsert + vault mirror write.

    Returns 404 when the memory is missing and 409 when it is not a candidate.
    """
    try:
        memory = await service.approve(memory_id)
    except MemoryNotFoundError:
        raise HTTPException(status_code=404, detail="Memory not found")
    except MemoryStateError:
        raise HTTPException(
            status_code=409, detail="Only candidate memories can be approved"
        )
    return _read(memory)


@router.post("/{memory_id}/reject", response_model=MemoryRead)
async def reject_memory(
    memory_id: str,
    repository: Annotated[MemoryRepository, Depends(get_memory_repository)],
    service: Annotated[MemoryService, Depends(get_memory_service)],
) -> MemoryRead:
    """Reject a candidate: status flip + vector/mirror removal.

    Unit-1 semantics are kept: only candidates may be rejected through the
    API (404 when missing, 409 otherwise). The service-level ``reject`` also
    cleans up the vector/mirror of approved memories; the candidate-only
    guard below is what keeps the 409 contract intact.
    """
    memory = await repository.get(memory_id)
    if memory is None:
        raise HTTPException(status_code=404, detail="Memory not found")
    if memory.status != "candidate":
        raise HTTPException(
            status_code=409, detail="Only candidate memories can be rejected"
        )
    try:
        rejected = await service.reject(memory_id)
    except MemoryNotFoundError:
        raise HTTPException(status_code=404, detail="Memory not found")
    return _read(rejected)


@router.delete("/{memory_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_memory(
    memory_id: str,
    service: Annotated[MemoryService, Depends(get_memory_service)],
) -> None:
    """Delete a memory: row + vector point + vault mirror; 404 when missing."""
    if not await service.delete(memory_id):
        raise HTTPException(status_code=404, detail="Memory not found")