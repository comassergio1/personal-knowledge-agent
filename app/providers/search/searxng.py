"""SearXNG search adapter: JSON API against a self-hosted instance (spec §21).

Queries ``GET /search?q=...&format=json&language=...&safesearch=0`` on the
configured base URL and maps the JSON ``results`` list to ``SearchHit`` items.
The provider issues one request per configured language, in order (Spanish
first, then English), and merges the hits deduped by URL keeping the first
occurrence. All transport/JSON/HTTP failures are wrapped in ``SearchError``
with a clear message; oddly-shaped result items are skipped defensively (e.g.
results from engines that report ``image/videos not configured`` quirks).
"""

from __future__ import annotations

import httpx

from app.providers.search.base import (
    SearchError,
    SearchHit,
    SearchProvider,
    domain_of_url,
)


class SearxngSearchProvider(SearchProvider):
    """Search results from a self-hosted SearXNG instance (JSON format)."""

    def __init__(
        self, base_url: str, languages: list[str], *, timeout: float = 20.0
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._languages = list(languages)
        self._timeout = timeout
        self._client = httpx.AsyncClient(base_url=self._base_url, timeout=timeout)

    @property
    def name(self) -> str:
        return "searxng"

    async def search(self, query: str, *, limit: int = 10) -> list[SearchHit]:
        # One request per language in configured order; merge deduped by URL,
        # keeping the first occurrence (Spanish hits win over English).
        merged: list[SearchHit] = []
        seen_urls: set[str] = set()
        for language in self._languages:
            hits = await self._search_language(query, language, limit=limit)
            for hit in hits:
                if hit.url in seen_urls:
                    continue
                seen_urls.add(hit.url)
                merged.append(hit)
                if len(merged) >= limit:
                    return merged
        return merged

    async def _search_language(
        self, query: str, language: str, *, limit: int
    ) -> list[SearchHit]:
        params = {
            "q": query,
            "format": "json",
            "language": language,
            "safesearch": 0,
        }
        try:
            response = await self._client.get("/search", params=params)
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPError as exc:
            raise SearchError(f"SearXNG request failed: {exc}") from exc
        except ValueError as exc:
            raise SearchError(f"SearXNG returned an invalid response: {exc}") from exc

        if not isinstance(data, dict):
            raise SearchError("SearXNG returned an unexpected response shape")
        raw_results = data.get("results")
        if not isinstance(raw_results, list):
            raise SearchError("SearXNG response is missing the results list")

        hits: list[SearchHit] = []
        for item in raw_results:
            if not isinstance(item, dict):
                continue
            url = item.get("url")
            if not isinstance(url, str) or not url.strip():
                continue  # items with a missing/empty URL are unusable
            hits.append(
                SearchHit(
                    title=str(item.get("title") or ""),
                    url=url,
                    snippet=str(item.get("content") or ""),
                    domain=domain_of_url(url),
                )
            )
            if len(hits) >= limit:
                break
        return hits

    async def ping(self) -> bool:
        """Return True when the SearXNG server answers (short 3s timeout).

        Never raises: the research route probes this for a clean 503 instead
        of a nested exception when the container is down.
        """
        try:
            response = await self._client.get("/", timeout=3.0)
        except httpx.HTTPError:
            return False
        return response.status_code < 500

    async def close(self) -> None:
        """Close the underlying httpx client."""
        await self._client.aclose()