"""Document endpoints: ingest a file, list, and delete (spec §41)."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import (
    get_db,
    get_ingestion_service,
    get_vault_service,
    get_vector_store,
)
from app.domain.models.document import Document
from app.repositories.document_repository import DocumentRepository
from app.schemas.document import (
    DocumentAppendRequest,
    DocumentDetail,
    DocumentList,
    DocumentRead,
)
from app.services.ingestion_service import IngestionService, ResyncError
from app.services.vault_service import VaultService
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
    """Ingest an uploaded file: PDFs are stored + text-extracted, plain text
    is written into the vault; both go through chunk → embed → upsert."""
    filename = file.filename or "document"
    resolved_title = title or Path(filename).stem
    if Path(filename).suffix.lower() == ".pdf":
        document = await ingestion_service.ingest_pdf(
            title=resolved_title,
            pdf_bytes=await file.read(),
            project_id=project_id,
        )
    else:
        content = (await file.read()).decode("utf-8").strip()
        document = await ingestion_service.ingest(
            title=resolved_title,
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


@router.get("/{document_id}", response_model=DocumentDetail)
async def get_document_detail(
    document_id: str,
    ingestion_service: Annotated[IngestionService, Depends(get_ingestion_service)],
) -> DocumentDetail:
    """Return one document with its file content and a ``stale`` flag."""
    detail = await ingestion_service.detail(document_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return detail


@router.post("/{document_id}/resync", response_model=DocumentDetail)
async def resync_document(
    document_id: str,
    ingestion_service: Annotated[IngestionService, Depends(get_ingestion_service)],
) -> DocumentDetail:
    """Re-read a document's vault file, re-extract, and re-embed it.

    Returns 404 when the document is missing and a 4xx when its vault file is
    gone from disk.
    """
    try:
        detail = await ingestion_service.resync(document_id)
    except ResyncError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if detail is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return detail


@router.patch("/{document_id}/append", response_model=DocumentDetail)
async def append_document_content(
    document_id: str,
    request: DocumentAppendRequest,
    ingestion_service: Annotated[IngestionService, Depends(get_ingestion_service)],
) -> DocumentDetail:
    """Append text to a document's vault file and re-index it.

    Returns 404 when the document is missing and 409 when it is not a
    file-backed text/markdown document (or its vault file is gone from disk).
    """
    try:
        detail = await ingestion_service.append_content(
            document_id, text=request.text, section=request.section
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if detail is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return detail


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    document_id: str,
    session: Annotated[AsyncSession, Depends(get_db)],
    vector_store: Annotated[QdrantVectorStore, Depends(get_vector_store)],
    vault: Annotated[VaultService, Depends(get_vault_service)],
) -> None:
    """Delete a document's vault file, vector points, and rows.

    The vault markdown is the source of truth: a plain index removal would be
    re-ingested by the next ``POST /vault/sync`` (new files on disk are
    ingested), resurrecting the document. Unlinking the source file too makes
    the deletion permanent. ``VaultService.delete`` ignores a file that is
    already gone, and a document without an on-disk file deletes cleanly.
    """
    repository = DocumentRepository(session)
    document = await repository.get(document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")
    if document.file_path:
        vault.delete(document.file_path)
    await vector_store.delete_by_document(document_id)
    await repository.delete(document_id)