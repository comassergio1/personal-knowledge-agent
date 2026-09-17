"""Pydantic schemas for projects (spec §17), decoupled from the ORM model."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ProjectCreate(BaseModel):
    """Payload for creating a project."""

    name: str = Field(min_length=1, max_length=128)
    description: str | None = None


class ProjectRead(BaseModel):
    """A project as returned to API consumers."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    description: str | None
    created_at: datetime
    updated_at: datetime