"""LLM Gateway contracts: message type, provider interface, and errors.

Every LLM adapter (Ollama, PayPerQ, OpenCode Go) implements ``LLMProvider`` so
the rest of the application can swap ``LLM_PROVIDER`` without touching domain
code (spec §4).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class ChatMessage:
    """A single chat turn passed to an LLM provider."""

    role: str
    content: str


class LLMProviderError(Exception):
    """Raised when an LLM provider cannot serve a request."""


class LLMProvider(ABC):
    """Abstract contract every LLM gateway adapter implements."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Stable provider identifier, e.g. ``ollama`` (spec §28)."""

    @abstractmethod
    async def generate(
        self, messages: list[ChatMessage], *, model: str | None = None, **kwargs
    ) -> str:
        """Return the assistant reply to ``messages`` as plain text."""

    async def close(self) -> None:
        """Release any held resources; no-op unless overridden."""