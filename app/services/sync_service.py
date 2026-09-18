"""Manual vault sync: make rows and vectors match the files on disk (spec §14).

The file on disk is the source of truth; sync is the user-driven
Obsidian-edits → memory path. One pass reconciles every vault file against the
documents table: new files are ingested, files whose mtime differs from the
recorded one are resynced (re-extracted and re-embedded), and documents whose
file is gone are deleted (rows + vector points). No filesystem watcher — the
user decides when to call ``POST /vault/sync``.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.core.logging import get_logger
from app.domain.models.project import Project
from app.repositories.document_repository import DocumentRepository
from app.repositories.project_repository import ProjectRepository
from app.services.ingestion_service import INBOX, IngestionService, as_naive_utc
from app.services.vault_service import VaultFile, VaultService

_ALLOWED_MIME_BY_SUFFIX = {
    ".md": "text/markdown",
    ".markdown": "text/markdown",
    ".txt": "text/plain",
}


@dataclass(frozen=True)
class SyncSummary:
    """Counts from one sync: files created, updated, and deleted."""

    created: int
    updated: int
    deleted: int


class SyncService:
    """Reconciles the vault with the document and vector stores."""

    def __init__(
        self,
        vault: VaultService,
        documents: DocumentRepository,
        projects: ProjectRepository,
        ingestion: IngestionService,
    ) -> None:
        self._vault = vault
        self._documents = documents
        self._projects = projects
        self._ingestion = ingestion
        self._logger = get_logger("sync_service")

    async def sync(self) -> SyncSummary:
        """Scan the vault and reconcile rows/vectors; return outcome counts.

        Every write goes through the existing repositories/services, each in a
        single committed transaction, so a partial failure never leaves a
        half-written document behind.
        """
        scanned = {file.rel_path: file for file in self._vault.scan()}
        known = [
            document
            for document in await self._documents.list_with_file_paths()
            if document.file_path is not None
        ]
        known_by_path = {document.file_path: document for document in known}

        # folder slug → project, created lazily (slug remains stable).
        projects_by_folder = {
            VaultService.slugify(project.name): project
            for project in await self._projects.list()
        }

        created = updated = deleted = 0
        for rel_path in sorted(scanned):
            document = known_by_path.get(rel_path)
            if document is None:
                if await self._ingest_new_file(
                    scanned[rel_path], projects_by_folder
                ):
                    created += 1
            elif as_naive_utc(scanned[rel_path].mtime) != as_naive_utc(
                document.file_mtime
            ):
                await self._ingestion.resync(document.id)
                updated += 1

        for rel_path, document in known_by_path.items():
            if rel_path not in scanned:
                await self._ingestion.delete_document(document.id)
                deleted += 1

        self._logger.info(
            "vault sync completed",
            extra={
                "files_created": created,
                "files_updated": updated,
                "files_deleted": deleted,
            },
        )
        return SyncSummary(created=created, updated=updated, deleted=deleted)

    async def _project_id_for(
        self, rel_path: str, projects_by_folder: dict[str, Project]
    ) -> str | None:
        """Return the project id for a file, creating the project if needed.

        A file in folder ``F`` belongs to the project whose slugged name is
        ``F``; the ``inbox`` folder and files directly under the vault root
        belong to the default project (no ``project_id``).
        """
        folder = Path(rel_path).parent
        if folder == Path("."):
            return None
        folder_name = folder.as_posix()
        if folder_name == INBOX:
            return None
        project = projects_by_folder.get(folder_name)
        if project is None:
            project = await self._projects.get_by_name(folder_name)
        if project is None:
            # Name is the slug itself, so the folder mapping stays stable.
            project = await self._projects.create(name=folder_name)
            projects_by_folder[folder_name] = project
        return project.id

    async def _ingest_new_file(
        self, file: VaultFile, projects_by_folder: dict[str, Project]
    ) -> bool:
        """Ingest one new vault file. Returns False when it was skipped."""
        title = Path(file.rel_path).stem
        project_id = await self._project_id_for(file.rel_path, projects_by_folder)
        suffix = Path(file.rel_path).suffix.lower()
        if suffix == ".pdf":
            raw = self._vault.read_bytes(file.rel_path)
            await self._ingestion.ingest_pdf(
                title=title,
                pdf_bytes=raw,
                project_id=project_id,
                file_path=file.rel_path,
                file_mtime=file.mtime,
            )
            return True
        mime_type = _ALLOWED_MIME_BY_SUFFIX.get(suffix)
        if mime_type is None:
            self._logger.warning(
                "skipping unsupported file type",
                extra={"file_path": file.rel_path},
            )
            return False
        content = self._vault.read_text(file.rel_path)
        if not content.strip():
            self._logger.warning(
                "skipping empty file", extra={"file_path": file.rel_path}
            )
            return False
        await self._ingestion.ingest(
            title=title,
            content=content,
            mime_type=mime_type,
            source_type="file",
            project_id=project_id,
            file_path=file.rel_path,
            file_mtime=file.mtime,
        )
        return True