"""Search gateway contracts: result type, errors, provider interface (spec §21).

Every search adapter (SearXNG today, API-backed engines later) implements
``SearchProvider`` so the research service can swap providers without touching
domain code — the same interchangeability the LLM gateway already provides.

``SearchHit.domain`` is derived from the result URL host so callers never parse
URLs themselves.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from urllib.parse import urlsplit


def domain_of_url(url: str) -> str:
    """Return the lowercase host of ``url`` (drops scheme, port, userinfo).

    ``"https://docs.python.org:8080/x"`` -> ``"docs.python.org"``.
    """
    return (urlsplit(url).hostname or "").lower()


@dataclass
class SearchHit:
    """A single search result: title, URL, snippet, and host domain."""

    title: str
    url: str
    snippet: str
    domain: str


class SearchError(Exception):
    """Raised when a search provider cannot serve a request."""


class SearchProvider(ABC):
    """Abstract contract every search gateway adapter implements."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Stable provider identifier, e.g. ``searxng``."""

    @abstractmethod
    async def search(self, query: str, *, limit: int = 10) -> list[SearchHit]:
        """Return up to ``limit`` hits for ``query``, ordered as the engine returns them."""

    async def close(self) -> None:
        """Release any held resources; no-op unless overridden."""