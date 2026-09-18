"""Unit tests for research page extraction (offline: fake fetcher + trafilatura).

trafilatura runs fully offline (no models/assets are downloaded on import or
extraction), so the real library is exercised here against small inline HTML
fixtures.
"""

from __future__ import annotations

from types import SimpleNamespace

import httpx

from app.services.research_extraction import extract_page_text

HTML_FIXTURE = """<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <title>Prueba de extracción</title>
</head>
<body>
  <nav>Navegación sin importancia</nav>
  <article>
    <h1>Título del artículo</h1>
    <p>Este es el párrafo principal del contenido de prueba.</p>
    <p>Un segundo párrafo que da contexto adicional a la prueba offline de
    extracción de texto con trafilatura.</p>
    <ul>
      <li>Primer punto de la lista</li>
      <li>Segundo punto de la lista</li>
    </ul>
  </article>
  <footer>Pie de página sin contenido relevante</footer>
</body>
</html>"""

PARAGRAPH = "Este es el párrafo principal del contenido de prueba."


class FakeFetcher:
    """Async stand-in for httpx.AsyncClient exposing only ``get``."""

    def __init__(self, *, status_code: int = 200, text: str = "", error: Exception | None = None) -> None:
        self.status_code = status_code
        self.text = text
        self.error = error
        self.calls: list[tuple[str, dict]] = []

    async def get(self, url: str, **kwargs):
        self.calls.append((url, kwargs))
        if self.error is not None:
            raise self.error
        return SimpleNamespace(status_code=self.status_code, text=self.text)


async def test_extracts_main_text_offline() -> None:
    fetcher = FakeFetcher(text=HTML_FIXTURE)
    text = await extract_page_text("https://example.com/post", client=fetcher)
    assert text is not None
    assert PARAGRAPH in text


async def test_follows_redirects_with_default_timeout() -> None:
    fetcher = FakeFetcher(text=HTML_FIXTURE)
    await extract_page_text("https://example.com/post", client=fetcher)
    url, kwargs = fetcher.calls[0]
    assert url == "https://example.com/post"
    assert kwargs["follow_redirects"] is True
    assert kwargs["timeout"] == 15.0


async def test_non_200_response_returns_none() -> None:
    fetcher = FakeFetcher(status_code=404, text="<html><body>nope</body></html>")
    assert await extract_page_text("https://example.com/missing", client=fetcher) is None


async def test_network_error_returns_none() -> None:
    fetcher = FakeFetcher(error=httpx.ConnectError("connection refused"))
    assert await extract_page_text("https://example.com/down", client=fetcher) is None


async def test_unparseable_html_returns_none() -> None:
    fetcher = FakeFetcher(
        text="<html><head><title>x</title></head><body><script>var a = 1;</script></body></html>"
    )
    assert await extract_page_text("https://example.com/js-only", client=fetcher) is None


async def test_truncates_to_max_chars() -> None:
    fetcher = FakeFetcher(text=HTML_FIXTURE)
    text = await extract_page_text("https://example.com/post", client=fetcher, max_chars=40)
    assert text is not None
    assert len(text) <= 40