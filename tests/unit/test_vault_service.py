"""Unit tests for VaultService: slugs, path mapping, file primitives, scan."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.services.vault_service import VaultFile, VaultService

# -- slugify ---------------------------------------------------------------


def test_slugify_lowercases_and_joins_words_with_dashes() -> None:
    assert VaultService.slugify("Hello World") == "hello-world"


def test_slugify_strips_accents_via_nfkd() -> None:
    assert VaultService.slugify("Café Àgro") == "cafe-agro"


def test_slugify_collapses_separator_runs_and_strips_dashes() -> None:
    assert VaultService.slugify("  a -- b!!  ") == "a-b"


def test_slugify_drops_emoji_and_non_ascii() -> None:
    assert VaultService.slugify("📓 Mis Notas") == "mis-notas"


def test_slugify_falls_back_when_nothing_remains() -> None:
    assert VaultService.slugify("") == "nota"
    assert VaultService.slugify("---") == "nota"
    assert VaultService.slugify("💥") == "nota"


# -- path mapping ----------------------------------------------------------


def test_project_folder_is_slugged_name_under_resolved_root(tmp_path) -> None:
    service = VaultService(tmp_path / "vault")
    assert service.project_folder("Deep Dive Notes") == (
        tmp_path / "vault"
    ).resolve() / "deep-dive-notes"


def test_markdown_path_maps_project_and_slugged_title(tmp_path) -> None:
    service = VaultService(tmp_path / "vault")
    path = service.markdown_path("Research", "New Note")
    assert path == (tmp_path / "vault").resolve() / "research" / "new-note.md"


def test_markdown_path_dedupes_existing_files_with_suffix(tmp_path) -> None:
    service = VaultService(tmp_path / "vault")
    first = service.markdown_path("Research", "Note")
    service.write_text(first, "one")

    second = service.markdown_path("Research", "Note")
    assert second == (tmp_path / "vault").resolve() / "research" / "note-2.md"
    service.write_text(second, "two")

    third = service.markdown_path("Research", "Note")
    assert third == (tmp_path / "vault").resolve() / "research" / "note-3.md"


# -- file primitives -------------------------------------------------------


def test_write_read_delete_exists_roundtrip_creates_parents(tmp_path) -> None:
    service = VaultService(tmp_path / "vault")
    path = service.markdown_path("Project One", "Note")
    assert not service.exists(path)

    service.write_text(path, "# Note\n\nSome content.")
    assert path.exists()
    assert service.read_text(path) == "# Note\n\nSome content."

    service.delete(path)
    assert not service.exists(path)
    service.delete(path)  # deleting a missing file is a no-op


def test_file_primitives_accept_vault_relative_paths(tmp_path) -> None:
    service = VaultService(tmp_path / "vault")
    service.write_text("research/note.md", "hello")
    assert service.exists("research/note.md")
    assert service.read_text("research/note.md") == "hello"
    service.delete("research/note.md")
    assert not service.exists("research/note.md")


# -- memory mirror (spec §13) -----------------------------------------------


def _root(tmp_path):
    return (tmp_path / "vault").resolve()


def test_memory_mirror_path_maps_type_folder_and_content_slug(tmp_path) -> None:
    service = VaultService(tmp_path / "vault")

    path = service.memory_mirror_path("semantic", "The user prefers concise answers")

    assert path == (
        _root(tmp_path) / "_memories" / "semantic" / "the-user-prefers-concise-answers.md"
    )


def test_memory_mirror_path_dedupes_existing_files_with_suffix(tmp_path) -> None:
    service = VaultService(tmp_path / "vault")
    first = service.memory_mirror_path("semantic", "Same content here")
    service.write_text(first, "one")

    second = service.memory_mirror_path("semantic", "Same content here")

    assert second == _root(tmp_path) / "_memories" / "semantic" / "same-content-here-2.md"


def test_memory_mirror_path_slugs_only_first_80_chars(tmp_path) -> None:
    service = VaultService(tmp_path / "vault")
    long_content = "word " * 30  # 150 chars

    path = service.memory_mirror_path("procedural", long_content)

    assert path == _root(tmp_path) / "_memories" / "procedural" / f"{service.slugify(long_content[:80])}.md"
    assert len(path.stem) < len(service.slugify(long_content))


def test_write_memory_mirror_roundtrip_with_frontmatter_and_verbatim_content(tmp_path) -> None:
    service = VaultService(tmp_path / "vault")
    content = (
        "MixedMarkdown **bold** and a code block:\n"
        "```py\nx = 1\n```\n"
        "line three"
    )

    path = service.write_memory_mirror("semantic", content, 0.8, "conversation", "approved")

    assert path.exists()
    text = service.read_text(path)
    assert text.startswith("---\n")
    assert "type: semantic" in text
    assert "confidence: 0.8" in text
    assert "status: approved" in text
    assert "source: conversation" in text
    assert text.rstrip().endswith(content)  # content verbatim below the frontmatter


def test_write_memory_mirror_escapes_colon_in_source(tmp_path) -> None:
    service = VaultService(tmp_path / "vault")

    path = service.write_memory_mirror("preference", "likes tea", 0.5, "chat: 2026-09", "approved")

    text = service.read_text(path)
    assert 'source: "chat: 2026-09"' in text


def test_mtime_returns_utc_datetime_and_none_when_missing(tmp_path) -> None:
    service = VaultService(tmp_path / "vault")
    path = service.markdown_path("Project", "Note")
    assert service.mtime(path) is None

    service.write_text(path, "x")
    mtime = service.mtime(path)
    assert mtime is not None
    assert mtime.tzinfo is not None
    assert mtime.utcoffset() == timedelta(0)  # UTC
    assert mtime <= datetime.now(UTC)


# -- scanning --------------------------------------------------------------


def test_scan_returns_sorted_files_recursively_with_abs_paths(tmp_path) -> None:
    service = VaultService(tmp_path / "vault")
    service.write_text("b.md", "b")
    service.write_text("a/deep.md", "deep")
    service.write_text("a/nested/two.md", "two")

    files = service.scan()

    root = (tmp_path / "vault").resolve()
    assert [f.rel_path for f in files] == ["a/deep.md", "a/nested/two.md", "b.md"]
    assert [f.abs_path for f in files] == [
        root / "a/deep.md",
        root / "a/nested/two.md",
        root / "b.md",
    ]
    assert all(f.mtime is not None for f in files)
    assert all(isinstance(f, VaultFile) for f in files)


def test_scan_missing_root_returns_empty_list(tmp_path) -> None:
    service = VaultService(tmp_path / "vault")
    assert service.scan() == []


def test_scan_rejects_symlinked_files_escaping_the_root(tmp_path) -> None:
    service = VaultService(tmp_path / "vault")
    outside = tmp_path / "outside.md"
    outside.write_text("outside the vault")
    service.write_text("inside.md", "kept")
    (tmp_path / "vault" / "evil.md").symlink_to(outside)

    rel_paths = [f.rel_path for f in service.scan()]
    assert rel_paths == ["inside.md"]