"""Unit tests for the SearXNG search adapter (monkeypatched httpx, no network)."""

from __future__ import annotations

import httpx
import pytest

from app.providers.search.base import SearchError
from app.providers.search.searxng import SearxngSearchProvider

# A realistic SearXNG JSON API response (format=json) with quirks: items with a
# missing/empty URL, missing title/content, and a non-dict entry must be
# tolerated; search engines that are not configured may still emit such rows.
SEARXNG_PAYLOAD = {
    "query": "python asyncio",
    "number_of_results": 4,
    "results": [
        {
            "url": "https://docs.python.org/3/library/asyncio.html",
            "title": "asyncio — Asynchronous I/O",
            "content": "Infrastructure for writing single-threaded concurrent code.",
            "engine": "wikipedia",
        },
        {
            "url": "https://example.com/async-guide",
            "title": "Async guide",
            "content": "Snippet for the second result.",
        },
        {"url": "", "title": "Empty URL", "content": "must be skipped"},
        {"url": None, "title": "None URL", "content": "must be skipped"},
        {"url": "https://bare.example/", "title": None, "content": None},
        "not-a-dict",
    ],
    "answers": [],
    "corrections": [],
    "infoboxes": [],
    "suggestions": [],
    "unresponsive_engines": [],
}


class FakeResponse:
    """Minimal httpx.Response stand-in exposing what the provider uses."""

    def __init__(self, payload, *, status_code: int = 200, bad_json: bool = False) -> None:
        self._payload = payload
        self.status_code = status_code
        self._bad_json = bad_json

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"error {self.status_code}",
                request=httpx.Request("GET", "http://searxng.test/search"),
                response=self,
            )

    def json(self):
        if self._bad_json:
            raise ValueError("not json")
        return self._payload


def _provider(languages: list[str] | None = None) -> SearxngSearchProvider:
    return SearxngSearchProvider(
        base_url="http://searxng.test", languages=languages or ["es"]
    )


async def test_search_maps_results(monkeypatch) -> None:
    captured: dict = {}

    async def fake_get(self, url: str, **kwargs):
        captured["url"] = url
        captured["params"] = kwargs["params"]
        return FakeResponse(SEARXNG_PAYLOAD)

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    hits = await _provider().search("python asyncio")

    assert captured["url"] == "/search"
    assert captured["params"] == {
        "q": "python asyncio",
        "format": "json",
        "language": "es",
        "safesearch": 0,
    }
    # The empty-URL, None-URL and non-dict items are skipped; the item with
    # missing title/content survives with empty strings.
    assert len(hits) == 3

    first = hits[0]
    assert first.title == "asyncio — Asynchronous I/O"
    assert first.url == "https://docs.python.org/3/library/asyncio.html"
    assert first.snippet == "Infrastructure for writing single-threaded concurrent code."
    assert first.domain == "docs.python.org"
    assert hits[1].domain == "example.com"
    assert hits[2].title == ""
    assert hits[2].snippet == ""
    assert hits[2].domain == "bare.example"


async def test_search_empty_results_returns_empty_list(monkeypatch) -> None:
    async def fake_get(self, url: str, **kwargs):
        return FakeResponse({"results": [], "answers": [], "unresponsive_engines": []})

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    assert await _provider().search("nothing") == []


async def test_search_respects_limit(monkeypatch) -> None:
    async def fake_get(self, url: str, **kwargs):
        return FakeResponse(SEARXNG_PAYLOAD)

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    hits = await _provider().search("python asyncio", limit=2)
    assert len(hits) == 2


async def test_search_malformed_json_raises_search_error(monkeypatch) -> None:
    async def fake_get(self, url: str, **kwargs):
        return FakeResponse(None, bad_json=True)

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    with pytest.raises(SearchError, match="invalid response"):
        await _provider().search("x")


async def test_search_http_status_raises_search_error(monkeypatch) -> None:
    async def fake_get(self, url: str, **kwargs):
        return FakeResponse({"error": "nope"}, status_code=500)

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    with pytest.raises(SearchError, match="SearXNG request failed"):
        await _provider().search("x")


async def test_search_transport_error_raises_search_error(monkeypatch) -> None:
    async def fake_get(self, url: str, **kwargs):
        raise httpx.TransportError("connection refused")

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    with pytest.raises(SearchError, match="connection refused"):
        await _provider().search("x")


async def test_search_missing_results_list_raises_search_error(monkeypatch) -> None:
    async def fake_get(self, url: str, **kwargs):
        return FakeResponse({"query": "x"})

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    with pytest.raises(SearchError, match="results list"):
        await _provider().search("x")


async def test_search_no_languages_returns_empty_without_requests(monkeypatch) -> None:
    requested = False

    async def fake_get(self, url: str, **kwargs):
        nonlocal requested
        requested = True
        return FakeResponse({"results": []})

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    provider = SearxngSearchProvider(base_url="http://searxng.test", languages=[])
    assert await provider.search("nothing") == []
    assert requested is False


async def test_search_one_request_per_language_in_order(monkeypatch) -> None:
    seen: list[dict] = []

    async def fake_get(self, url: str, **kwargs):
        seen.append(kwargs["params"])
        return FakeResponse({"results": []})

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    await _provider(["es", "en"]).search("python asyncio")

    assert [p["language"] for p in seen] == ["es", "en"]
    assert all(p["q"] == "python asyncio" for p in seen)
    assert all(p["format"] == "json" for p in seen)


async def test_search_merges_languages_es_first_deduping_by_url(monkeypatch) -> None:
    payloads = {
        "es": {
            "results": [
                {"url": "https://es.example/1", "title": "es 1"},
                {"url": "https://shared.example/", "title": "shared es"},
                {"url": "https://es.example/2", "title": "es 2"},
            ]
        },
        "en": {
            "results": [
                {"url": "https://shared.example/", "title": "shared en"},
                {"url": "https://en.example/1", "title": "en 1"},
                {"url": "https://en.example/2", "title": "en 2"},
            ]
        },
    }

    async def fake_get(self, url: str, **kwargs):
        return FakeResponse(payloads[kwargs["params"]["language"]])

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    hits = await _provider(["es", "en"]).search("query")

    # Order is preserved ES-then-EN; the shared URL appears once and keeps the
    # first (Spanish) occurrence.
    assert [h.url for h in hits] == [
        "https://es.example/1",
        "https://shared.example/",
        "https://es.example/2",
        "https://en.example/1",
        "https://en.example/2",
    ]
    assert hits[1].title == "shared es"


async def test_search_stops_requesting_once_merged_limit_reached(monkeypatch) -> None:
    languages_requested: list[str] = []
    es_payload = {
        "results": [{"url": f"https://es.example/{i}"} for i in range(3)]
    }

    async def fake_get(self, url: str, **kwargs):
        languages_requested.append(kwargs["params"]["language"])
        return FakeResponse(es_payload)

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    hits = await _provider(["es", "en"]).search("query", limit=3)

    # The Spanish hits alone fill the merged limit, so English is never
    # requested: the merged limit caps both requests and results.
    assert [h.url for h in hits] == [
        "https://es.example/0",
        "https://es.example/1",
        "https://es.example/2",
    ]
    assert languages_requested == ["es"]


async def test_search_merged_limit_across_languages(monkeypatch) -> None:
    payloads = {
        "es": {
            "results": [
                {"url": "https://es.example/1"},
                {"url": "https://es.example/2"},
                {"url": "https://es.example/3"},
            ]
        },
        "en": {
            "results": [
                {"url": "https://en.example/1"},
                {"url": "https://en.example/2"},
                {"url": "https://en.example/3"},
            ]
        },
    }

    async def fake_get(self, url: str, **kwargs):
        return FakeResponse(payloads[kwargs["params"]["language"]])

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    hits = await _provider(["es", "en"]).search("query", limit=4)

    assert [h.url for h in hits] == [
        "https://es.example/1",
        "https://es.example/2",
        "https://es.example/3",
        "https://en.example/1",
    ]


async def test_search_error_in_later_language_still_raises(monkeypatch) -> None:
    async def fake_get(self, url: str, **kwargs):
        if kwargs["params"]["language"] == "en":
            raise httpx.TransportError("connection refused")
        return FakeResponse({"results": [{"url": "https://es.example/1"}]})

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    with pytest.raises(SearchError, match="connection refused"):
        await _provider(["es", "en"]).search("query")


async def test_ping_true_when_server_answers(monkeypatch) -> None:
    async def fake_get(self, url: str, **kwargs):
        assert kwargs["timeout"] == 3.0
        return FakeResponse({})

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    assert await _provider().ping() is True


async def test_ping_false_on_server_error(monkeypatch) -> None:
    async def fake_get(self, url: str, **kwargs):
        return FakeResponse({}, status_code=503)

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    assert await _provider().ping() is False


async def test_ping_false_on_transport_error(monkeypatch) -> None:
    async def fake_get(self, url: str, **kwargs):
        raise httpx.TransportError("connection refused")

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    assert await _provider().ping() is False


async def test_close_releases_client(monkeypatch) -> None:
    closed = False

    async def fake_aclose(self) -> None:
        nonlocal closed
        closed = True

    monkeypatch.setattr(httpx.AsyncClient, "aclose", fake_aclose)

    provider = _provider()
    await provider.close()
    assert closed is True