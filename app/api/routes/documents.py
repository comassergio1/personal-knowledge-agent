"""Document endpoints: ingest a file, list, and delete (spec §41)."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_db, get_ingestion_service, get_vector_store
from app.domain.models.document import Document
from app.repositories.document_repository import DocumentRepository
from app.schemas.document import DocumentList, DocumentRead
from app.services.ingestion_service import IngestionService
from app.vector.qdrant import QdrantVectorStore

router = APIRouter(prefix="/documents", tags=["documents"])

_MIME_BY_SUFFIX = {
    ".md": "text/markdown",
    ".markdown": "text/markdown",
    ".txt": "text/plain",
}


def _mime_type(filename: str) -> str:
    """Derive the mime type from the filename suffix."""
    return _MIME_BY_SUFFIX.get(Path(filename).suffix.lower(), "application/octet-stream")


def _to_read(document: Document) -> DocumentRead:
    """Map a persisted document (chunks loaded) to its API shape."""
    return DocumentRead(
        id=document.id,
        title=document.title,
        mime_type=document.mime_type,
        source_type=document.source_type,
        created_at=document.created_at,
        updated_at=document.updated_at,
        chunk_count=len(document.chunks),
    )


@router.post("", response_model=DocumentRead, status_code=status.HTTP_201_CREATED)
async def create_document(
    file: Annotated[UploadFile, File()],
    ingestion_service: Annotated[IngestionService, Depends(get_ingestion_service)],
    title: Annotated[str | None, Form()] = None,
    project_id: Annotated[str | None, Form()] = None,
) -> DocumentRead:
    """Ingest an uploaded markdown/plain-text file (chunk → embed → upsert)."""
    raw = (await file.read()).decode("utf-8")
    content = raw.strip()
    filename = file.filename or "document"
    document = await ingestion_service.ingest(
        title=title or Path(filename).stem,
        content=content,
        mime_type=_mime_type(filename),
        source_type="file",
        project_id=project_id,
    )
    return _to_read(document)


@router.get("", response_model=DocumentList)
async def list_documents(
    session: Annotated[AsyncSession, Depends(get_db)],
    project_id: str | None = None,
) -> DocumentList:
    """Return documents, newest first, optionally scoped to one project."""
    documents = await DocumentRepository(session).list(project_id=project_id)
    return DocumentList(items=[_to_read(d) for d in documents], total=len(documents))


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    document_id: str,
    session: Annotated[AsyncSession, Depends(get_db)],
    vector_store: Annotated[QdrantVectorStore, Depends(get_vector_store)],
) -> None:
    """Delete a document's vector points and rows; 404 when it is missing."""
    repository = DocumentRepository(session)
    if await repository.get(document_id) is None:
        raise HTTPException(status_code=404, detail="Document not found")
    await vector_store.delete_by_document(document_id)
    await repository.delete(document_id)