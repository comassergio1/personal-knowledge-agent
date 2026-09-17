# Personal Knowledge Agent (PKA)

A self-hosted personal knowledge OS. PKA ingests your notes and documents,
chunks and embeds them, stores the vectors in Qdrant, and answers questions
about your knowledge with grounded citations. Your knowledge belongs to you:
it lives in your own database and vector store, never in a third-party
service. LLMs are interchangeable providers — swap `LLM_PROVIDER` (ollama,
payperq, opencode_go) and the application code does not change.

## Stack

- FastAPI (async) + SQLAlchemy 2.0 + Alembic
- Qdrant for vector search (docker-compose)
- uv for dependency and environment management (Python 3.12)

## Quickstart

> Full quickstart lands in a later work unit; this is a placeholder.

```bash
docker compose up -d            # start Qdrant
uv sync                         # install dependencies
uv run fastapi dev app/main.py  # start the API
```