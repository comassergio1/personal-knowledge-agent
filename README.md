# Personal Knowledge Agent (PKA)

Self-hosted personal knowledge OS: conversational chat, persistent personal memory,
semantic search, and RAG over your own documents.

> **Your knowledge is the product. LLMs are interchangeable providers.**

The application owns Conversations, Documents, Knowledge, Memories, Embeddings,
Research, Projects, and Evals. LLM providers (Ollama, PayPerQ, OpenCode Go) only
provide inference — switching providers never loses or touches your data.

**Current status: Fase 6 — research agent.**

Everything from Fase 5, plus a **self-hosted research agent**: SearXNG (Docker)
searches the web without third-party keys, trafilatura extracts page text
locally, and `POST /research/run` writes a Spanish report (Objetivo/Resumen/
Hallazgos con citas `[n]`/Contradicciones/Conclusión/Fuentes) into the vault,
indexed immediately. Tutorial engine, memory, projects, PDF ingestion, three
LLM providers with cost accounting all live. Evals and the coding-agent
integration are later phases.

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

## Knowledge vault (Obsidian)

Knowledge is stored as **markdown files on disk** so you own it and can edit it
with any tool — Obsidian works out of the box:

- The vault lives at `VAULT_PATH` (default `data/vault`, gitignored). Open that
  folder with Obsidian's "Open folder as vault" to browse and edit your notes.
- Each project maps to a folder (`slugify(project.name)`); files without a
  project go to `inbox/`. Safe kebab-case filenames (`slugify(title)`).
- **Editing a note** (in Obsidian or any editor): `GET /documents/{id}` reports
  `stale: true`; `POST /documents/{id}/resync` re-indexes one note, or
  `POST /vault/sync` reconciles the whole vault (created/updated/deleted).
- PDF uploads are copied into the vault as `.pdf` and their text is extracted
  (pypdf) for RAG. Exporting markdown → PDF stays your job.
- Deleting a project removes its documents (rows + vectors + vault files).

## API (prefix `/api/v1`)

| Method | Path | Description |
|--------|------|-------------|
| POST | `/documents` | Upload a markdown/txt/PDF file (multipart) → stored, chunked, embedded, indexed |
| GET | `/documents` | List documents (optional `?project_id=` filter) |
| GET | `/documents/{id}` | Detail: file content + `stale` flag (edited on disk?) |
| POST | `/documents/{id}/resync` | Re-index one document after editing its vault file |
| DELETE | `/documents/{id}` | Delete document (rows + vector points) |
| POST | `/projects` · GET · DELETE | Project CRUD (DELETE cascades docs + vectors + vault files) |
| POST | `/vault/sync` | Scan the vault: create/update/delete rows+vectors to match files |
| POST | `/chat` | `{"message": "...", "top_k": 5, "document_id": "...", "project_id": "..."}` → grounded answer + sources |
| POST | `/memories/extract` | `{"conversation": [{"role", "content"}...]}` → candidate memories (redacted) |
| POST | `/tutorials/generate` | `{"objective": "...", "project_id": "...", "title": "..."}` → Spanish step-by-step tutorial written to the vault + indexed |
| POST | `/research/run` | `{"question": "...", "project_id": "...", "max_sources": 6}` → Spanish research report with cited sources, saved to the vault (SearXNG + trafilatura) |
| GET | `/memories` · `/{id}` | List (`?type=`/`?status=`) / get memories |
| POST | `/memories/{id}/approve` · `/reject` | Validation gate: approve stores vector + Obsidian mirror |
| DELETE | `/memories/{id}` | Remove memory (row + vector + mirror) |
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

## Research (Fase 6)

`POST /research/run` answers open web questions with a **Spanish report with
citations** (spec §21): it turns the question into 2–4 search queries (LLM),
queries **SearXNG** (self-hosted Docker service, no API keys — JSON format
enabled in `config/searxng/settings.yml`), dedupes by URL, ranks sources by a
quality heuristic (official docs/GitHub > tech sites > forums), extracts each
page's main text with **trafilatura** (fallback: search snippet), and has the
LLM synthesize a report:

- `# Objetivo` · `# Resumen` · `# Hallazgos` (findings cite `[n]`)
- `# Contradicciones detectadas` (explicit cross-source conflicts)
- `# Conclusión` · `# Fuentes` (title — URL — fecha de consulta)

The report is written to the vault (project folder or `inbox`) and indexed
immediately; re-read it with `GET /documents/{id}`. With SearXNG down the
endpoint answers 503 cleanly and the rest of the app keeps working. Turning
findings into long-term facts stays manual via `POST /memories/extract`
(spec §22: no automatic knowledge pollution).

## Tutorials (Fase 5)

`POST /tutorials/generate` produces a grounded **Spanish** step-by-step
tutorial (spec §20): `# Objetivo`, `# Prerrequisitos`, `# Materiales`,
`# Paso N…`, `# Verificación`, `# Troubleshooting`, `# Errores comunes`,
`# Rollback`, `# Fuentes`. It retrieves the top chunks (scoped to the project
when given) plus approved memories, adapts the style to your preferences, and
detects contradictions against the knowledge base (it warns inside the
tutorial instead of inventing facts). The result is written to the vault
(`data/vault/<project>/…md`) and indexed on the spot — re-read/sync/delete
through the documents endpoints.

## Memory (Fase 4)

Memories follow a **candidate → approve/reject** lifecycle (spec §13); only
approved memories reach the chat prompt:

- `POST /memories/extract` runs the conversation through the LLM Gateway and
  produces candidates: `semantic`, `episodic`, `procedural`, `preference`,
  each with content + confidence. Secrets are redacted (`[REDACTED]`) before
  anything is stored (spec §34: passwords, api keys, Bearer tokens, private
  key blocks, AWS keys, JWTs).
- `POST /memories/{id}/approve` stores the memory (Qdrant `memories`
  collection) and writes an Obsidian mirror at
  `data/vault/_memories/<type>/<slug>.md` with YAML frontmatter — review your
  memory vault in Obsidian. `reject`/`delete` remove the vector and mirror.
- Chat automatically retrieves approved memories (top-k=3) and places them in
  the prompt as the labeled `MEMORY` section (spec §25).
- Extraction is **explicit** (no per-chat auto-extraction) by design.

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
  api/routes/      chat · documents · health · memories · projects · sync
                   · tutorials · usage
  core/            config (pydantic-settings) · logging
  domain/models/   Document · Chunk · Project · Memory · LLMUsage (SQLAlchemy 2.0)
  providers/       llm/ (base · ollama · payperq · opencode_go · factory)
                   embeddings/ (base · ollama · factory)
  repositories/    document · project · memory · usage
  schemas/         document · chat · project · memory · sync · tutorial · usage
  services/        chunking · ingestion · retrieval · chat · memory · redaction
                   research · sync · tutorial · vault
  providers/       llm/ · embeddings/ · search/ (searxng)
  vector/          qdrant store (knowledge + memories) · collections constants
examples/          sample knowledge document
scripts/           smoke_e2e.py
odd/tasks/         feature tracking (vertical-slice, phase2-5)
```

## Roadmap

Fase 1 vertical slice ✔ → Fase 2 multi-provider ✔ → Fase 3 knowledge vault +
projects + PDF ✔ → Fase 4 memory (extraction + approval + chat) ✔ → Fase 5
tutorial generator ✔ → Fase 6 research agent (SearXNG + trafilatura + citas) ✔
→ coding-agent integration → evals → LangGraph workflows when stateful
multi-step flows demand it.