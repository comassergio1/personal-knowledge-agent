"""Pydantic schema for the manual vault sync result."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class SyncSummary(BaseModel):
    """Counts from one ``POST /vault/sync`` reconciliation."""

    model_config = ConfigDict(from_attributes=True)

    created: int
    updated: int
    deleted: int