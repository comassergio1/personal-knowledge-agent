"""End-to-end smoke test against the real local stack (Qdrant + Ollama).

Requires:
- Qdrant running on QDRANT_URL (e.g. `docker compose up -d`)
- Ollama serving on OLLAMA_BASE_URL with the configured embedding model and
  LLM_MODEL (e.g. `ollama serve`)

Runs through the public API of a real app instance:
health -> ingest examples/mikrotik.md -> list documents -> chat.

Usage: uv run python scripts/smoke_e2e.py
Exit code 0 when every step succeeds.
"""

from __future__ import annotations

import sys
from pathlib import Path

from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import create_app

PROJECT_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_DOC = PROJECT_ROOT / "examples" / "mikrotik.md"
CHAT_QUESTION = "¿Cómo configuramos las VLANs en mi MikroTik?"


def main() -> int:
    settings = get_settings()
    print(f"[smoke] settings: provider={settings.llm_provider} "
          f"model={settings.llm_model} qdrant={settings.qdrant_url} "
          f"ollama={settings.ollama_base_url}")

    with TestClient(create_app(settings)) as client:
        health = client.get("/api/v1/health")
        print(f"[smoke] health {health.status_code}: {health.json()}")
        if health.status_code != 200:
            return 1

        title = "mikrotik-vlans"
        with EXAMPLE_DOC.open("rb") as handle:
            response = client.post(
                "/api/v1/documents",
                files={"file": (EXAMPLE_DOC.name, handle, "text/markdown")},
                data={"title": title},
            )
        print(f"[smoke] ingest {response.status_code}: {response.json()}")
        if response.status_code != 201:
            return 1
        document_id = response.json()["id"]
        chunk_count = response.json()["chunk_count"]
        print(f"[smoke] document {document_id} chunk_count={chunk_count}")

        listing = client.get("/api/v1/documents")
        print(f"[smoke] list {listing.status_code}: "
              f"{[d['title'] for d in listing.json()['items']]}")

        chat = client.post(
            "/api/v1/chat",
            json={"message": CHAT_QUESTION, "document_id": document_id},
        )
        print(f"[smoke] chat {chat.status_code}")
        if chat.status_code != 200:
            print(chat.text)
            return 1
        payload = chat.json()
        print(f"[smoke] sources: {len(payload['sources'])}")
        for source in payload["sources"]:
            print(f"  - {source['title']} chunk={source['chunk_index']} "
                  f"score={source['score']:.3f}")
        print(f"[smoke] answer:\n{payload['answer']}\n")
        return 0


if __name__ == "__main__":
    sys.exit(main())