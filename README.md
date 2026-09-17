# Personal Knowledge Agent (PKA)

Self-hosted personal knowledge OS: conversational chat, persistent personal memory,
semantic search, and RAG over your own documents.

> **Your knowledge is the product. LLMs are interchangeable providers.**

The application owns Conversations, Documents, Knowledge, Memories, Embeddings,
Research, Projects, and Evals. LLM providers (Ollama, PayPerQ, OpenCode Go) only
provide inference — switching providers never loses or touches your data.

**Current status: Fase 2 — multi-provider, live-validated.**

Documents → embeddings → Qdrant → retrieval → grounded chat via the LLM
Gateway, with **Ollama (local)**, **PayPerQ** (`deepseek/deepseek-v4.1-flash`)
and **OpenCode Go** (`glm-5.3`) all validated against the real providers, and
per-request token/cost accounting (§30). Memory extraction, research,
tutorials, evals, and the coding-agent integration are later phases.

## Architecture

```
Web/API (FastAPI)
   │
   ├── Services: ChatService · RetrievalService · IngestionService
   │
   ├── Persistence: SQLite (SQLAlchemy + Alembic) → PostgreSQL later
   ├── Vector store: Qdrant (Docker)
   └── Providers (interchangeable):
         LLM Gateway ── Ollama · PayPerQ (OpenAI-compatible) · OpenCode Go
         Embeddings   ── Ollama (nomic-embed-text)
```

Domain code never talks to a provider directly: the `LLMProvider` /
`EmbeddingProvider` interfaces and their factories keep providers swappable via
configuration only (spec §4, §28).

## Requirements

- Python 3.12 (managed by uv)
- Docker (for Qdrant)
- Ollama with an embedding model (`nomic-embed-text`) and a chat model
  (default `gemma4:26b`)

## Quickstart

```bash
# 1. Install dependencies
uv sync

# 2. Start Qdrant
docker compose up -d

# 3. Start Ollama (once per boot; `brew services start ollama` makes it persistent)
ollama serve

# 4. Apply the database schema
uv run alembic upgrade head

# 5. Configure the environment (optional; defaults work for the local stack)
cp env.template .env     # then edit API keys, provider, model...

# 6. Run the API (http://localhost:8000/docs)
uv run fastapi dev app/main.py
```

### Smoke test (real stack)

```bash
uv run python scripts/smoke_e2e.py
```

Ingests `examples/mikrotik.md`, lists documents, asks "¿Cómo configuramos las
VLANs en mi MikroTik?", and prints the grounded answer with its sources.

## API (prefix `/api/v1`)

| Method | Path | Description |
|--------|------|-------------|
| POST | `/documents` | Upload a markdown/txt file (multipart) → stored, chunked, embedded, indexed |
| GET | `/documents` | List documents |
| DELETE | `/documents/{id}` | Delete document (rows + vector points) |
| POST | `/chat` | `{"message": "...", "top_k": 5, "document_id": "..."}` → grounded answer + sources |
| GET | `/usage` | Recent per-request LLM usage, totals, and per-provider breakdown (§30) |
| GET | `/health` | App status + Qdrant/Ollama reachability (never 5xx) |

Example:

```bash
curl -X POST http://localhost:8000/api/v1/documents \
  -F "file=@examples/mikrotik.md" -F "title=mikrotik-vlans"

curl -X POST http://localhost:8000/api/v1/chat \
  -H 'Content-Type: application/json' \
  -d '{"message": "¿Cómo configuramos las VLANs en mi MikroTik?"}'
```

## Switching providers

Every provider swap happens in `.env` — domain code does not change (spec §5):

```bash
# Local (default)
LLM_PROVIDER=ollama
LLM_MODEL=gemma4:26b

# PayPerQ (OpenAI-compatible, https://api.ppq.ai/v1)
LLM_PROVIDER=payperq
PAYPERQ_API_KEY=...
LLM_MODEL=deepseek/deepseek-v4.1-flash   # any id from GET /v1/models

# OpenCode Go (OpenAI-compatible, https://opencode.ai/zen/go/v1)
LLM_PROVIDER=opencode_go
OPENCODE_GO_API_KEY=...                  # OpenCode Go subscription key
OPENCODE_GO_BASE_URL=https://opencode.ai/zen/go/v1   # default when empty
OPENCODE_GO_MODEL=glm-5.3                # default when empty
```

OpenCode Go notes: the adapter sends a stable `x-opencode-session` header and
the `personal-knowledge-agent/0.1.0` User-Agent (per the provider docs);
`gpt-5.6-luna`/`grok-4.6` use the Responses API and are out of scope. All three
providers were validated live (Fase 2). A fallback provider chain (primary →
fallback, spec §29) is a planned enhancement.

## Cost control (spec §30)

Every LLM request is recorded in the `llm_usage` table (provider, model,
input/output tokens, estimated cost, latency) and visible at
`GET /api/v1/usage` (recent rows + totals + per-provider breakdown). The
estimated cost uses per-provider USD-per-1k rates from `.env`:

```bash
PAYPERQ_USD_PER_1K_IN=0.0        # set your real PayPerQ rates
PAYPERQ_USD_PER_1K_OUT=0.0
OPENCODE_GO_USD_PER_1K_IN=0.0    # flat $10/mo subscription
OPENCODE_GO_USD_PER_1K_OUT=0.0
OLLAMA_USD_PER_1K_IN=0.0         # local, free
OLLAMA_USD_PER_1K_OUT=0.0
```

## Security

- API keys live only in `.env` (gitignored) or the process environment — never
  in the knowledge database (spec §27).
- The environment template is committed as `env.template` (the `.env*` filename
  is blocked by the Pi safety policy).
- Secret redaction before memory persistence is a later phase (spec §34).

## Tests

```bash
uv run pytest            # unit + API integration (offline, fakes)
uv run ruff check app tests
```

## Project layout

```
app/
  api/routes/      chat · documents · health · usage
  core/            config (pydantic-settings) · logging
  domain/models/   Document · Chunk · LLMUsage (SQLAlchemy 2.0)
  providers/       llm/ (base · ollama · payperq · opencode_go · factory)
                   embeddings/ (base · ollama · factory)
  repositories/    document_repository · usage_repository
  schemas/         document · chat · usage
  services/        chunking · ingestion · retrieval · chat
  vector/          qdrant store · collections constants
examples/          sample knowledge document
scripts/           smoke_e2e.py
odd/tasks/         feature tracking (vertical-slice, phase2-multi-provider)
```

## Roadmap

Fase 1 vertical slice ✔ → Fase 2 multi-provider live ✔ → knowledge ingestion
formats (PDF/HTML) → memory extraction/approval → tutorial engine → research
agent → coding-agent integration → evals → LangGraph workflows when stateful
multi-step flows demand it.