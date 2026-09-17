"""Unit tests for project schemas and the chat request project filter."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.schemas.chat import ChatRequest
from app.schemas.project import ProjectCreate, ProjectRead

_TS = datetime(2025, 1, 2, 3, 4, 5, tzinfo=UTC)


def test_project_create_defaults_description_to_none() -> None:
    project = ProjectCreate(name="Research")
    assert project.name == "Research"
    assert project.description is None


def test_project_create_requires_non_empty_name() -> None:
    with pytest.raises(ValidationError):
        ProjectCreate()  # type: ignore[call-arg]
    with pytest.raises(ValidationError):
        ProjectCreate(name="")


def test_project_read_validates_fields() -> None:
    project = ProjectRead(
        id="proj-1",
        name="Research",
        description="Notes",
        created_at=_TS,
        updated_at=_TS,
    )
    assert project.id == "proj-1"
    assert project.name == "Research"
    assert project.description == "Notes"


def test_project_read_rejects_wrong_id_type() -> None:
    with pytest.raises(ValidationError):
        ProjectRead(  # type: ignore[call-arg]
            id=123, name="Research", created_at=_TS, updated_at=_TS  # type: ignore[arg-type]
        )


def test_chat_request_project_id_defaults_to_none() -> None:
    assert ChatRequest(message="hi").project_id is None


def test_chat_request_accepts_project_id() -> None:
    assert ChatRequest(message="hi", project_id="proj-1").project_id == "proj-1"