"""Chat result shapes returned by the chat service."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class SourceRef:
    """One knowledge source cited in a chat answer."""

    document_id: str
    title: str
    chunk_index: int
    score: float
    excerpt: str


@dataclass
class ChatResult:
    """A chat answer together with the sources it was grounded in."""

    answer: str
    sources: list[SourceRef] = field(default_factory=list)