"""Deterministic Markdown/TXT chunking (spec §14/§15).

Pure functions with no I/O and no LLM: paragraphs are packed greedily into
chunks of at most ``size`` characters, preferring boundaries at headings and
blank-line paragraph breaks. Over-long paragraphs are split at word
boundaries, so a word is never cut in half. Every chunk after the first
carries the tail of its predecessor, so consecutive chunks overlap by
``overlap`` characters.
"""

from __future__ import annotations

import re

_HEADING_RE = re.compile(r"^#{1,6}[ \t]+")


def chunk_text(text: str, *, size: int, overlap: int) -> list[str]:
    """Split ``text`` into deterministic, overlapping chunks.

    Args:
        text: Document content (markdown or plain text).
        size: Maximum characters per chunk (before overlap).
        overlap: Characters of the previous chunk prepended to the next.

    Returns:
        The list of chunks; empty for empty input. Raises ``ValueError`` for
        a non-positive ``size``.
    """
    if size <= 0:
        raise ValueError("size must be a positive integer")
    if overlap < 0:
        raise ValueError("overlap must not be negative")
    normalized = _normalize(text)
    if not normalized:
        return []
    return _apply_overlap(_pack(_paragraphs(normalized), size), overlap)


def _normalize(text: str) -> str:
    """Normalize line endings and trim the outer whitespace."""
    return text.replace("\r\n", "\n").strip()


def _paragraphs(text: str) -> list[str]:
    """Split text into paragraphs at blank lines, dropping empty ones."""
    return [part.strip() for part in re.split(r"\n[ \t]*\n", text) if part.strip()]


def _is_heading(paragraph: str) -> bool:
    """True for markdown ATX headings like ``# Title``."""
    return _HEADING_RE.match(paragraph) is not None


def _pack(paragraphs: list[str], size: int) -> list[str]:
    """Group paragraphs into chunks, splitting at headings and size limits."""
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        if _is_heading(paragraph) and current:
            chunks.append(current)
            current = paragraph
            continue
        separator = "\n\n" if current else ""
        if len(current) + len(separator) + len(paragraph) <= size:
            current = current + separator + paragraph
            continue
        if current:
            chunks.append(current)
            current = ""
        if len(paragraph) > size:
            chunks.extend(_split_long_paragraph(paragraph, size))
        else:
            current = paragraph
    if current:
        chunks.append(current)
    return chunks


def _split_long_paragraph(paragraph: str, size: int) -> list[str]:
    """Split one over-long paragraph into word-aligned pieces of at most size."""
    pieces: list[str] = []
    current = ""
    for word in paragraph.split():
        separator = " " if current else ""
        if len(current) + len(separator) + len(word) <= size:
            current = current + separator + word
            continue
        if current:
            pieces.append(current)
            current = ""
        if len(word) > size:
            # A single word longer than the chunk size cannot be word-aligned;
            # split it by characters so the function still terminates.
            pieces.extend(word[i : i + size] for i in range(0, len(word), size))
        else:
            current = word
    if current:
        pieces.append(current)
    return pieces


def _apply_overlap(chunks: list[str], overlap: int) -> list[str]:
    """Prefix each chunk after the first with its predecessor's tail."""
    if overlap <= 0 or len(chunks) <= 1:
        return chunks
    result = [chunks[0]]
    for index in range(1, len(chunks)):
        result.append(chunks[index - 1][-overlap:] + chunks[index])
    return result