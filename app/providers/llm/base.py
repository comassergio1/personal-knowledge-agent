"""LLM Gateway contracts: message type, result type, provider interface, errors.

Every LLM adapter (Ollama, PayPerQ, OpenCode Go) implements ``LLMProvider`` so
the rest of the application can swap ``LLM_PROVIDER`` without touching domain
code (spec §4). ``generate`` returns an ``LLMResult`` carrying the reply plus
per-request token usage when the provider reports it (spec §30).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class ChatMessage:
    """A single chat turn passed to an LLM provider."""

    role: str
    content: str


@dataclass
class LLMResult:
    """A provider reply plus per-request token usage (spec §30)."""

    content: str
    prompt_tokens: int | None
    completion_tokens: int | None
    provider: str
    model: str


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
    ) -> LLMResult:
        """Return the assistant reply to ``messages`` plus token usage."""

    async def close(self) -> None:
        """Release any held resources; no-op unless overridden."""