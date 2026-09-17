# Feature: vertical-slice — PKA Fase 1 (Foundation)

**Project**: Personal Knowledge Agent (PKA) — self-hosted personal knowledge OS.
**Spec source**: `Personal Knowledge Agent.md` (Obsidian Vault, "Memoria local rag"), sections 10, 41, 42.
**Branch policy**: commits on `main` (fresh repo), one Conventional Commit per work unit.
**Status**: in_progress

## Scope (vertical slice, §41)

1. `docker compose up -d` runs Qdrant.
2. `uv run fastapi dev app/main.py` starts API.
3. `POST /api/v1/documents` ingests a markdown/txt file: store → chunk → embed → upsert to Qdrant.
4. `POST /api/v1/chat` with `{"message": "..."}`: embed question → Qdrant top-k → build grounded context → LLM Gateway → answer with sources.
5. `LLM_PROVIDER` swap (ollama → payperq → opencode_go) changes nothing in domain code.
6. `GET /api/v1/health` reports app, Qdrant, and Ollama reachability (soft, non-500).

## Non-goals (this slice)

Web UI, memory extraction/approval, research agent, tutorial generator, coding agent, evals, LangGraph, PDF/HTML ingestion, reranking, cost/observability tables (only structured logging now).

## Environment facts

- Host: macOS Apple Silicon, Python 3.13, uv 0.11.21, Docker 29.6.2 + Compose v5.3.1.
- Ollama installed (0.20.7) but server NOT running — `ollama serve` must be started for live verification.
- Local Ollama models present: `gemma4:26b`, `llama3.1:latest`, `gemma:7b-instruct`, `nomic-embed-text:latest` (embeddings), plus coder models.
- PayPerQ: OpenAI-compatible, base URL `https://api.ppq.ai/v1` (per spec §3).
- OpenCode Go: no direct HTTP endpoint found in `~/.config/opencode/opencode.json` (built-in CLI provider). Slice implements `OpenCodeGoProvider` as a configurable OpenAI-compatible adapter (env `OPENCODE_GO_BASE_URL`/`OPENCODE_GO_API_KEY`), raising a clear config error when unset. Live validation pending endpoint discovery — domain stays untouched.
- `proyectos_mios` is not a git repo; `personal-knowledge-agent/` is its own fresh repo.
- Deviation: Pi's safety policy blocks the sensitive `.env*` pattern, so `.env.example` (spec §27) is committed as `env.template` (user-approved rename); `Settings` still reads runtime `.env`.

## Tasks

| # | Task | Status | Commit |
|---|------|--------|--------|
| 1 | Repo bootstrap: git init, pyproject.toml (uv), .python-version 3.12, .gitignore, env.template, docker-compose.yml (Qdrant), README skeleton, Alembic init | done | (see Evidence) |
| 2 | Core: `core/config.py` (pydantic-settings) + `core/logging.py` | done | (see Evidence) |
| 3 | Persistence: SQLAlchemy `Document` model + `document_repository` + initial migration | done | (see Evidence) |
| 4 | Providers: LLM gateway (`base`, `ollama`, `payperq`, `opencode_go`, `factory`) + embeddings (`base`, `ollama`) | done | c6246e0 |
| 5 | Vector: `vector/qdrant.py` client + `vector/collections.py` bootstrap (create collection + payload index) | done | c6246e0 |
| 6 | Services: `ingestion_service` (markdown/txt chunking, embed, upsert), `retrieval_service` (embed → search → top-k), `chat_service` (context build per §25, gateway call, sources) | in_progress | |
| 7 | API: routes `chat`, `documents`, `health` + `api/dependencies.py` + `main.py` + schemas | pending | |
| 8 | Tests: unit (chunking, retrieval with fake store, chat with fake providers, factory) + API integration (TestClient, in-memory) | pending | |
| 9 | README quickstart + live end-to-end verification (real Qdrant via Docker, real Ollama) | pending | |

## Acceptance criteria

- Unit + API tests green via `uv run pytest`.
- With Qdrant up and Ollama serving, ingest `mikrotik.md` → `POST /api/v1/chat` returns a grounded answer citing the ingested content.
- Changing `LLM_PROVIDER=payperq` (or a fake) serves without touching `app/` domain files.
- No secrets stored in knowledge stores; `.env` gitignored; `API keys never in DB` (spec §27).

## Evidence

- `015973a`/`7228260` feat: bootstrap PKA scaffold with config, persistence, and migrations (tasks 1–3).
- `c6246e0` feat: add LLM gateway, embedding providers, and Qdrant vector store (tasks 4–5; included LLM_TIMEOUT_SECONDS fix).