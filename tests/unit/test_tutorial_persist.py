"""Unit tests for TutorialService.persist: vault write + immediate ingest."""

from __future__ import annotations

from pathlib import Path

from app.core.config import Settings
from app.providers.llm.base import LLMResult
from app.repositories.document_repository import DocumentRepository
from app.repositories.project_repository import ProjectRepository
from app.services.ingestion_service import IngestionService
from app.services.tutorial_service import TutorialResult, TutorialService
from app.services.vault_service import VaultService
from tests.unit.fakes import CapturingVectorStore, FakeEmbeddingProvider, build_stack

_MARKDOWN = "# Objetivo\n\nCuerpo del tutorial.\n\n# Fuentes\n\n- [1] Nota A\n"


class _FakeLLM:
    """Never called by persist; satisfies the constructor."""

    name = "fake-persist-llm"

    async def generate(self, messages, *, model: str | None = None, **kwargs) -> LLMResult:
        return LLMResult(
            content=_MARKDOWN,
            prompt_tokens=None,
            completion_tokens=None,
            provider="fake-persist-llm",
            model="test-model",
        )


def _result() -> TutorialResult:
    return TutorialResult(
        document_id=None,
        title="Guest VLAN Guide",
        file_path=None,
        content=_MARKDOWN,
        sources=[],
    )


def _service(
    db_session, tmp_path: Path, *, with_vault: bool = True
) -> tuple[TutorialService, VaultService | None, DocumentRepository, ProjectRepository | None]:
    settings = Settings(_env_file=None, llm_model="test-model")  # type: ignore[arg-type]
    if with_vault:
        ingestion, _, _, vault, documents, projects = build_stack(db_session, tmp_path)
    else:
        vault = None
        documents = DocumentRepository(db_session)
        ingestion = IngestionService(
            documents, CapturingVectorStore(), FakeEmbeddingProvider()
        )
        projects = None
    service = TutorialService(  # type: ignore[arg-type]
        _FakeLLM(),
        retrieval=None,
        memory=None,
        vault=vault,
        ingestion=ingestion,
        settings=settings,
        projects=projects,
    )
    return service, vault, documents, projects


async def test_persist_writes_file_under_inbox_and_ingests(
    db_session, tmp_path
) -> None:
    service, _, documents, _ = _service(db_session, tmp_path)
    result = _result()

    document = await service.persist(result, title="Guest VLAN Guide")

    target = tmp_path / "vault" / "inbox" / "guest-vlan-guide.md"
    assert target.exists()
    assert target.read_text(encoding="utf-8") == _MARKDOWN
    assert document.file_path == "inbox/guest-vlan-guide.md"
    assert document.file_mtime is not None
    assert document.source_type == "tutorial"
    assert result.document_id == document.id
    assert result.file_path == "inbox/guest-vlan-guide.md"

    persisted = await documents.get(document.id)
    assert persisted is not None  # row created by the immediate ingest


async def test_persist_unknown_project_falls_back_to_inbox(
    db_session, tmp_path
) -> None:
    service, _, _, _ = _service(db_session, tmp_path)

    document = await service.persist(_result(), project_id="missing", title="Guest VLAN Guide")

    assert document.file_path == "inbox/guest-vlan-guide.md"
    assert (tmp_path / "vault" / "inbox" / "guest-vlan-guide.md").exists()


async def test_persist_writes_file_under_the_project_folder(
    db_session, tmp_path
) -> None:
    service, _, _, projects = _service(db_session, tmp_path)
    project = await projects.create(name="Deep Dive Notes")

    document = await service.persist(
        _result(), project_id=project.id, title="Guest VLAN Guide"
    )

    target = tmp_path / "vault" / "deep-dive-notes" / "guest-vlan-guide.md"
    assert target.exists()
    assert document.file_path == "deep-dive-notes/guest-vlan-guide.md"
    assert document.project_id == project.id


async def test_persist_without_vault_returns_fileless_document(
    db_session, tmp_path
) -> None:
    service, vault, _, _ = _service(db_session, tmp_path, with_vault=False)
    result = _result()

    document = await service.persist(result, project_id=None)

    assert vault is None
    assert document.file_path is None
    assert document.file_mtime is None
    assert result.document_id == document.id
    assert result.file_path is None
    assert not (tmp_path / "vault").exists()


async def test_persist_without_ingestion_raises(db_session, tmp_path) -> None:
    service = TutorialService(  # type: ignore[arg-type]
        _FakeLLM(),
        retrieval=None,
        memory=None,
        vault=VaultService(tmp_path / "vault"),
        ingestion=None,
        settings=Settings(_env_file=None, llm_model="test-model"),  # type: ignore[arg-type]
    )

    try:
        await service.persist(_result())
    except ValueError as exc:
        assert "IngestionService" in str(exc)
    else:
        raise AssertionError("persist without ingestion must raise ValueError")