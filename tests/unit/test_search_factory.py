"""Unit tests for the search provider factory (no network)."""

from __future__ import annotations

import pytest

from app.core.config import Settings
from app.providers.search.base import SearchError
from app.providers.search.factory import SearchProviderFactory
from app.providers.search.searxng import SearxngSearchProvider


def _settings(**overrides: object) -> Settings:
    return Settings(_env_file=None, **overrides)  # type: ignore[arg-type]


def test_create_searxng() -> None:
    provider = SearchProviderFactory.create("searxng", _settings())
    assert isinstance(provider, SearxngSearchProvider)
    assert provider.name == "searxng"


def test_create_uses_settings_values() -> None:
    provider = SearchProviderFactory.create(
        "searxng",
        _settings(searxng_url="http://searxng.local:8080", searxng_language="fr"),
    )
    assert isinstance(provider, SearxngSearchProvider)
    assert provider._base_url == "http://searxng.local:8080"
    assert provider._language == "fr"


def test_create_normalizes_case_and_whitespace() -> None:
    provider = SearchProviderFactory.create("  SEARXNG ", _settings())
    assert isinstance(provider, SearxngSearchProvider)


def test_create_unknown_provider_lists_valid_choices() -> None:
    with pytest.raises(SearchError, match="searxng"):
        SearchProviderFactory.create("bogus", _settings())