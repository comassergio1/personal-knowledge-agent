"""Vault sync endpoint: manual Obsidian-edits → memory reconciliation."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.dependencies import get_sync_service
from app.schemas.sync import SyncSummary
from app.services.sync_service import SyncService

router = APIRouter(prefix="/vault", tags=["vault"])


@router.post("/sync", response_model=SyncSummary)
async def sync_vault(
    sync_service: Annotated[SyncService, Depends(get_sync_service)],
) -> SyncSummary:
    """Scan the vault and reconcile rows/vectors; return outcome counts."""
    return SyncSummary.model_validate(await sync_service.sync())