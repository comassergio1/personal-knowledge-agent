"""Unit tests for app.services.chunking (deterministic, no LLM, no I/O)."""

from __future__ import annotations

import pytest

from app.services.chunking import chunk_text


def test_empty_text_yields_no_chunks() -> None:
    assert chunk_text("", size=1000, overlap=120) == []


def test_whitespace_only_text_yields_no_chunks() -> None:
    assert chunk_text(" \n\t \n", size=1000, overlap=120) == []


def test_short_document_is_a_single_chunk() -> None:
    text = "Short note with a few words."
    assert chunk_text(text, size=1000, overlap=120) == [text]


def test_paragraph_boundaries_are_preferred() -> None:
    text = "First paragraph.\n\nSecond paragraph.\n\nThird paragraph."
    chunks = chunk_text(text, size=20, overlap=0)
    assert chunks == ["First paragraph.", "Second paragraph.", "Third paragraph."]


def test_paragraphs_pack_into_one_chunk_when_they_fit() -> None:
    text = "Short A.\n\nShort B."
    assert chunk_text(text, size=100, overlap=0) == ["Short A.\n\nShort B."]


def test_headings_start_new_chunks_before_size_forces_it() -> None:
    # Both sections fit inside one chunk on size alone, so the split can only
    # come from the heading boundary preference.
    text = (
        "# Section One\n\n"
        "Body of the first section.\n\n"
        "# Section Two\n\n"
        "Body of the second section."
    )
    chunks = chunk_text(text, size=90, overlap=0)
    assert chunks == [
        "# Section One\n\nBody of the first section.",
        "# Section Two\n\nBody of the second section.",
    ]


def test_consecutive_chunks_overlap_by_configured_amount() -> None:
    text = "A long running sentence with many words. " * 8
    chunks = chunk_text(text, size=100, overlap=10)
    assert len(chunks) >= 3
    assert chunks[1].startswith(chunks[0][-10:])
    assert chunks[2].startswith(chunks[1][-10:])


def test_never_splits_mid_word() -> None:
    words = [f"word{i}" for i in range(80)]
    text = " ".join(words)
    chunks = chunk_text(text, size=64, overlap=0)
    assert len(chunks) > 1
    for chunk in chunks:
        assert len(chunk) <= 64
        assert chunk.split()[0] in words
        assert chunk.split()[-1] in words


def test_chunking_is_deterministic() -> None:
    text = (
        "# Section One\n\n"
        "Repeated sentence content here. " * 4
        + "\n\n# Section Two\n\n"
        + "More words to chunk. " * 4
    )
    assert chunk_text(text, size=40, overlap=8) == chunk_text(text, size=40, overlap=8)


def test_rejects_non_positive_size() -> None:
    with pytest.raises(ValueError, match="size"):
        chunk_text("some text", size=0, overlap=0)