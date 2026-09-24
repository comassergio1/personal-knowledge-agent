"""Integration tests for the own-console SPA: static serving + API survival.

The console ships as a zero-dependency static SPA (no build step, no CDN)
served by the app itself: ``GET /`` returns the index and ``/static/**``
serves the assets. The markdown renderer lives client-side (plain escaped
JS), so the SPA contract is asserted here by grepping the served static
files: the index references the assets and the JS talks to the same-origin
absolute API paths only. The static routes are registered after the API
routers, so ``/api/v1/*`` and ``/v1/*`` keep answering.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

# JavaScript media types accepted by browsers: modern CPython maps .js to
# text/javascript (RFC 9239), legacy/other mime.types databases may report
# application/javascript. The observed value on this project's environments
# is text/javascript.
_JS_MEDIA_TYPES = {"text/javascript", "application/javascript"}


def test_index_serves_the_console(test_app: TestClient) -> None:
    response = test_app.get("/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    body = response.text
    assert "My NotebookLM" in body
    assert 'id="app"' in body
    assert "app.js" in body
    assert "styles.css" in body


def test_static_assets_are_served(test_app: TestClient) -> None:
    app_js = test_app.get("/static/app.js")

    assert app_js.status_code == 200
    assert app_js.headers["content-type"].split(";")[0] in _JS_MEDIA_TYPES

    styles = test_app.get("/static/styles.css")
    assert styles.status_code == 200
    assert styles.headers["content-type"].startswith("text/css")


def test_static_mount_does_not_shadow_api_routes(test_app: TestClient) -> None:
    health = test_app.get("/api/v1/health")

    assert health.status_code == 200
    assert health.json()["status"] == "ok"

    models = test_app.get("/v1/models")
    assert models.status_code == 200
    assert models.json()["data"][0]["id"] == "my-notebooklm"


def test_page_references_assets_and_same_origin_api(test_app: TestClient) -> None:
    index = test_app.get("/").text
    app_js = test_app.get("/static/app.js").text

    # The index loads both assets from the same origin (offline requirement).
    assert 'href="/static/styles.css"' in index
    assert 'src="/static/app.js"' in index

    # The JS drives the existing endpoints; a drift in these literals would
    # break the console flows (the renderer is client-side, so this is the
    # only server-visible contract of the SPA).
    for endpoint in (
        "/api/v1/chat",
        "/api/v1/learn/run",
        "/api/v1/memories",
        "/api/v1/memories/extract",
        "/api/v1/documents",
        "/api/v1/knowledge/map",
        "/api/v1/research/sessions",
    ):
        assert endpoint in app_js