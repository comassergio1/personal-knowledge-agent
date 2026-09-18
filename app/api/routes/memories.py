"""Memory endpoints: list, detail, status flips, delete (spec §13).

Unit 1 scope: ``approve``/``reject`` only flip the row's status. The vector
upsert/removal and the vault mirror are wired onto these routes in unit 2;
until then the status change is the sole persisted side effect.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.dependencies import get_memory_repository
from app.domain.models.memory import Memory
from app.repositories.memory_repository import MemoryRepository
from app.schemas.memory import (
    MemoryList,
    MemoryRead,
    MemoryStatusQuery,
    MemoryTypeQuery,
)

router = APIRouter(prefix="/memories", tags=["memories"])


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


@router.post("/{memory_id}/approve", response_model=MemoryRead)
async def approve_memory(
    memory_id: str,
    repository: Annotated[MemoryRepository, Depends(get_memory_repository)],
) -> MemoryRead:
    """Approve a candidate memory (status → ``approved``).

    Unit 1 performs ONLY the status flip; the vector upsert and the vault
    mirror write are wired here in unit 2. Returns 404 when the memory is
    missing and 409 when it is not a candidate.
    """
    memory = await repository.get(memory_id)
    if memory is None:
        raise HTTPException(status_code=404, detail="Memory not found")
    if memory.status != "candidate":
        raise HTTPException(
            status_code=409, detail="Only candidate memories can be approved"
        )
    return _read(await repository.set_status(memory_id, "approved"))


@router.post("/{memory_id}/reject", response_model=MemoryRead)
async def reject_memory(
    memory_id: str,
    repository: Annotated[MemoryRepository, Depends(get_memory_repository)],
) -> MemoryRead:
    """Reject a candidate memory (status → ``rejected``).

    Unit 1 performs ONLY the status flip; the vector/mirror removal is wired
    here in unit 2. Returns 404 when the memory is missing and 409 when it is
    not a candidate.
    """
    memory = await repository.get(memory_id)
    if memory is None:
        raise HTTPException(status_code=404, detail="Memory not found")
    if memory.status != "candidate":
        raise HTTPException(
            status_code=409, detail="Only candidate memories can be rejected"
        )
    return _read(await repository.set_status(memory_id, "rejected"))


@router.delete("/{memory_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_memory(
    memory_id: str,
    repository: Annotated[MemoryRepository, Depends(get_memory_repository)],
) -> None:
    """Delete a memory row; 404 when missing.

    Unit 1 removes only the database row; the vector-point removal and the
    vault mirror cleanup are wired here in unit 2.
    """
    deleted = await repository.delete(memory_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Memory not found")