"""Research content extraction: fetch a page and pull its main text (spec §21).

Fetches the page HTML over the caller-provided httpx client (redirects
followed) and extracts readable main text with ``trafilatura``. Extraction is
best-effort: any failure (network, non-200, or no extractable content) returns
``None`` so the research service falls back to the search snippet. The caller
owns inter-fetch delays; a single fetch has no built-in pause.
"""

from __future__ import annotations

import httpx
import trafilatura

from app.core.logging import get_logger

logger = get_logger("research_extraction")


async def extract_page_text(
    url: str,
    *,
    client: httpx.AsyncClient,
    timeout: float = 15.0,
    max_chars: int = 20_000,
) -> str | None:
    """Return the main readable text of ``url``, or ``None`` on any failure.

    Non-200 responses and fetch or parse errors return ``None`` (the caller
    falls back to the search snippet); surviving text is truncated to
    ``max_chars``.
    """
    try:
        response = await client.get(url, follow_redirects=True, timeout=timeout)
    except httpx.HTTPError as exc:
        logger.debug("fetch failed: %s (%s)", url, exc)
        return None
    if response.status_code != 200:
        logger.debug("non-200 response for %s: %s", url, response.status_code)
        return None

    try:
        text = trafilatura.extract(
            response.text, include_comments=False, include_tables=False
        )
    except Exception as exc:  # noqa: BLE001  best-effort extraction never crashes a research run
        logger.debug("trafilatura failed for %s: %s", url, exc)
        return None
    if not text:
        return None
    return text[:max_chars]