# My NotebookLM — Personal Learning & Knowledge System

> Private, self-hosted NotebookLM oriented to **learning by doing**: your
> knowledge and your memory stay yours, and the LLM is a swappable engine.
> (Technical package/repo name: `personal-knowledge-agent`.)

Self-hosted personal knowledge OS: conversational chat, persistent personal memory,
semantic search, and RAG over your own documents.

> **Your knowledge is the product. LLMs are interchangeable providers.**

The application owns Conversations, Documents, Knowledge, Memories, Embeddings,
Research, Projects, and Evals. LLM providers (Ollama, PayPerQ, OpenCode Go) only
provide inference — switching providers never loses or touches your data.

**Current status: Fase 7 — Learning Engine (product pivot).**

Everything from Fase 8, plus the learning core the new product doc asked for:
tutorials with **depth modes** (`do` / `learn` / `deep_learn`), the orchestrated
**learning loop** (`POST /learn/run`: assess your knowledge → research the web
only when it's missing → generate the tutorial), **`POST /learn/reflect`**
("¿qué aprendí?" → memory candidates) and **`GET /knowledge/map`** ("¿qué sé
sobre X?" → hierarchical map of concepts, tutorials, experiences and gaps).
The coding-agent/OpenCode integration left the core and is now an optional
future plugin.

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
- **Editing by command**: `PATCH /documents/{id}/append {text, section?}` appends a pasted section to a document's vault file and re-indexes it on the spot — create a tutorial in one session, grow it with new sections in later sessions.

## API (prefix `/api/v1`)

| Method | Path | Description |
|--------|------|-------------|
| POST | `/documents` | Upload a markdown/txt/PDF file (multipart) → stored, chunked, embedded, indexed |
| GET | `/documents` | List documents (optional `?project_id=` filter) |
| GET | `/documents/{id}` | Detail: file content + `stale` flag (edited on disk?) |
| POST | `/documents/{id}/resync` | Re-index one document after editing its vault file |
| PATCH | `/documents/{id}/append` | `{"text": "...", "section": "..."}` → append a pasted section to the vault file + re-index (edit by command) |
| DELETE | `/documents/{id}` | Delete document (rows + vector points) |
| POST | `/projects` · GET · DELETE | Project CRUD (DELETE cascades docs + vectors + vault files) |
| POST | `/vault/sync` | Scan the vault: create/update/delete rows+vectors to match files |
| POST | `/chat` | `{"message": "...", "top_k": 5, "document_id": "...", "project_id": "..."}` → grounded answer + sources |
| POST | `/memories/extract` | `{"conversation": [{"role", "content"}...]}` → candidate memories (redacted) |
| POST | `/tutorials/generate` | `{"objective": "...", "mode": "do|learn|deep_learn", "project_id": "..."}` → depth-aware Spanish tutorial written to the vault + indexed |
| POST | `/research/run` | `{"question": "...", "project_id": "...", "max_sources": 6}` → Spanish research report with cited sources, saved to the vault (SearXNG + trafilatura) |
| POST | `/evals/run` | `{"dataset": [{"question", "expected_facts", "adversarial"}...]}` → per-case metrics + verdicts (spec §31/§32) |
| GET | `/evals/runs` | Eval history (newest first) |
| POST | `/learn/run` | `{"goal": "...", "mode": "do|learn|deep_learn", "allow_research": true}` → assess → research on demand → tutorial (the learning loop) |
| POST | `/learn/reflect` | `{"goal": "...", "what_i_learned": "..."}` → candidate memories ("¿qué aprendí?") |
| GET | `/knowledge/map` | `?topic=` → hierarchical map of what you know about a topic (concepts, tutorials, experiences, gaps) |
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

## Learning (Fase 7 — the core of the product)

The product pivot (`My notebook lm.md`) makes **learning** the center and
chat/coding secondary:

- **Tutorial depth modes** — `POST /tutorials/generate` accepts `mode`:
  `do` (concrete steps only), `learn` (steps + Conceptos previos + per-step
  “¿Por qué hacemos esto?”), `deep_learn` (theory, concepts, exercises,
  self-evaluation). The structure grows with the mode; content stays Spanish.
- **The learning loop** — `POST /learn/run {goal, mode}`:
  own knowledge is assessed first (retrieval score vs `research_threshold`);
  when it is insufficient **and** `allow_research`, the research agent goes to
  the web first (its report lands in the vault and is indexed), and the
  tutorial is then generated grounded on both. Returns
  `needs_research`, the research reference and the tutorial.
- **“¿Qué aprendí?”** — `POST /learn/reflect {goal, what_i_learned}` runs the
  reflection through the memory extractor, producing **candidate memories**
  (approve them to keep them; they feed future prompts as MEMORY).
- **Knowledge map** — `GET /knowledge/map?topic=` aggregates approved memories
  and your documents around a topic and builds a hierarchical map
  (`Conceptos`, `Tutoriales`, `Experiencias`, `Recursos`, `Huecos`), citing
  your own material and calling out what is missing.

## Despliegue en servidor (NAS / OpenMediaVault)

`deploy/nas/` contiene el paquete de despliegue: Dockerfile, `docker-compose.yml`
(stack: app + qdrant + searxng + ollama-embeddings + open-webui; puertos solo
`8000` y `3000`), `env.template` y el runbook (`deploy/nas/README.md`) con
primer arranque, migración de datos desde esta Mac, SMB/Obsidian, conexión de
Open WebUI y backup.

## Consola (interfaz web propia)

`GET http://localhost:8000/` serves a small static SPA (vanilla JS, no build
step, works offline inside the LAN container) with the PKA-specific surfaces
that generic UIs can't show:

- **Chat** — grounded answer + Fuentes with scores.
- **Aprender** — goal + mode (`do`/`learn`/`deep_learn`) + `allow_research` →
  the learning loop's tutorial.
- **Memorias** — list, approve/reject/delete, and extract-from-conversation.
- **Vault** — documents with `stale` badges, upload, resync, delete, and the
  append-section form (the two-session edit workflow).
- **Mapa** — `¿qué sé sobre X?` knowledge map.

## OpenAI-compatible surface + Open WebUI

PKA speaks the OpenAI wire format, so any OpenAI-compatible client can use the
grounded chat (retrieval + memory + sources):

```bash
GET  /v1/models              → "my-notebooklm"
POST /v1/chat/completions    → grounded answer + **Fuentes** block (+ SSE stream)
```

**Connect Open WebUI** (the already-running container):

1. Open WebUI → Settings → **Connections/Model Providers** → **OpenAI API**.
2. URL: `http://host.docker.internal:8000/v1` (Docker Desktop macOS/Windows).
   On Linux hosts add `--add-host host.docker.internal:host-gateway` to the
   Open WebUI container.
3. API key: any non-empty value (PKA has no auth in v1; LAN personal server).
4. The `my-notebooklm` model appears in the model picker.

**Web research from the chat**: messages that ask to search the web
("investigá en la web…", "buscá fuentes…") are detected and routed to the
research agent: the fresh report is persisted to the vault and returned in the
reply (synchronous; a run takes ~1–3 minutes).

**Search sources (SearXNG)**: the research agent searches a curated engine set
(`config/searxng/settings.yml`) focused on official/documentation sources
(wikipedia, wikidata, science APIs, technical wikis) instead of the ~260
engines defaults — social noise (Reddit & co.) no longer dominates results.
Each query runs bilingual (`SEARXNG_LANGUAGES=es,en`): Spanish first, then
English, merged deduped by URL. English queries bring official documentation.

**Guard rule:** Open WebUI is a *client*. Do NOT enable its own knowledge/RAG
or upload documents there — knowledge and memory must live only in PKA
(no split memory, spec §7/§42).

## Integrations (optional, future)

- **Coding agent (OpenCode headless)** — deferred out of the core by the
  product pivot. The design stays documented: PKA builds the specification +
  context (knowledge, project, memories) and a `CodingAgent` adapter would run
  `opencode run` against a bounded repository, returning the result as a memory
  candidate. Pi remains the interactive desk harness; nothing of this is
  required for the learning product.

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

## Evals (Fase 8)

`POST /evals/run` checks the grounded chat against a dataset (Spanish;
examples in `tests/evals/mikrotik.json` + `mikrotik-adversarial.json`):

- Per case: a grounded answer is produced (same retrieval/chat pipeline), then
  an **LLM judge** scores `correctness` (expected facts covered), `relevance`,
  `groundedness` (claims supported by the FULL source chunks — not the API
  excerpts), `hallucination_rate` and `source_quality`. Heuristics fill in when
  the judge's JSON fails; nothing aborts the batch.
- **Adversarial cases** (spec §32) also require `challenged_premise`: the
  answer must dispute a false premise (e.g. "¿Configuramos la VLAN 50 para
  IoT?" when knowledge says IoT = VLAN 30) or the case fails.
- Verdict thresholds are configurable per run; runs persist for history
  (`GET /evals/runs`) and never pollute the knowledge base or prompts.
- Live results (2026-09-18): mikrotik dataset 3/3 PASS; adversarial PASS with
  the premise challenged. The harness also caught and fixed two real defects:
  ingest duplication hurting recall (idempotent content hash) and judge
  ground-truth being too short (full chunks now).

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
  api/routes/      chat · documents · health · knowledge · learn · memories
                   · projects · research · sync · tutorials · usage · evals
  core/            config (pydantic-settings) · logging
  domain/models/   Document · Chunk · Project · Memory · LLMUsage (SQLAlchemy 2.0)
  providers/       llm/ (base · ollama · payperq · opencode_go · factory)
                   embeddings/ (base · ollama · factory)
  repositories/    document · project · memory · usage
  schemas/         document · chat · project · memory · eval · learn · sync
                   · research · tutorial · usage
  services/        chunking · ingestion · retrieval · chat · eval · knowledge_map
                   · learn · memory · research · redaction · sync · tutorial · vault
  providers/       llm/ · embeddings/ · search/ (searxng)
  vector/          qdrant store (knowledge + memories) · collections constants
examples/          sample knowledge document
scripts/           smoke_e2e.py
odd/tasks/         feature tracking (vertical-slice, phase2-5)
```

## Roadmap

Fases 1–6 ✔ (slice, multi-provider, vault/projects/PDF, memory, tutorials,
research) → Fase 8 ✔ (evals — surfaced and fixed two real defects) → **Fase 7 ✔
Learning Engine** (depth modes, learn loop, reflect, knowledge map) → LangGraph
when stateful flows demand it. The coding-agent/OpenCode adapter is an
**optional future integration**, no longer a core phase.