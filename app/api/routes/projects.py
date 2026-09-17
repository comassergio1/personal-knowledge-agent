"""Project endpoints: create, list, and delete with a full cascade (spec §17).

Deleting a project is destructive by design: it removes every document of
the project (database rows and chunks), their Qdrant vector points, and the
project's markdown files inside the vault.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_db, get_vault_service, get_vector_store
from app.repositories.document_repository import DocumentRepository
from app.repositories.project_repository import ProjectNameConflict, ProjectRepository
from app.schemas.project import ProjectCreate, ProjectRead
from app.services.vault_service import VaultService
from app.vector.qdrant import QdrantVectorStore

router = APIRouter(prefix="/projects", tags=["projects"])


@router.post("", response_model=ProjectRead, status_code=status.HTTP_201_CREATED)
async def create_project(
    payload: ProjectCreate,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> ProjectRead:
    """Create a project. Returns 409 when the name already exists."""
    repository = ProjectRepository(session)
    try:
        project = await repository.create(
            name=payload.name, description=payload.description
        )
    except ProjectNameConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return ProjectRead.model_validate(project)


@router.get("", response_model=list[ProjectRead])
async def list_projects(
    session: Annotated[AsyncSession, Depends(get_db)],
) -> list[ProjectRead]:
    """Return all projects, newest first."""
    projects = await ProjectRepository(session).list()
    return [ProjectRead.model_validate(project) for project in projects]


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(
    project_id: str,
    session: Annotated[AsyncSession, Depends(get_db)],
    vector_store: Annotated[QdrantVectorStore, Depends(get_vector_store)],
    vault: Annotated[VaultService, Depends(get_vault_service)],
) -> None:
    """Delete a project and everything it owns — DESTRUCTIVE, no undo.

    Removes the project row, every document row (and chunk) belonging to the
    project, their Qdrant vector points, and the project's markdown files
    from the vault. Returns 404 when the project is missing.
    """
    repository = ProjectRepository(session)
    if await repository.get_by_id(project_id) is None:
        raise HTTPException(status_code=404, detail="Project not found")

    document_repository = DocumentRepository(session)
    for document in await document_repository.list(project_id=project_id):
        await vector_store.delete_by_document(document.id)
        if document.file_path is not None:
            vault.delete(document.file_path)
        await document_repository.delete(document.id)
    await repository.delete(project_id)