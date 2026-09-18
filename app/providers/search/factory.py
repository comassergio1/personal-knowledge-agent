"""Search provider factory: maps ``SEARCH_PROVIDER`` names to adapters.

The factory is the only code that reads provider values from ``Settings``;
adapters receive plain values. Swapping providers never touches domain code
(spec §21).
"""

from __future__ import annotations

from app.core.config import Settings
from app.providers.search.base import SearchError, SearchProvider
from app.providers.search.searxng import SearxngSearchProvider


class SearchProviderFactory:
    """Builds a ``SearchProvider`` instance for a configured provider name."""

    @staticmethod
    def create(provider: str, settings: Settings) -> SearchProvider:
        name = provider.strip().lower()
        if name == "searxng":
            return SearxngSearchProvider(
                base_url=settings.searxng_url,
                language=settings.searxng_language,
            )
        raise SearchError(
            f"Unknown search provider {provider!r}; valid choices: searxng"
        )