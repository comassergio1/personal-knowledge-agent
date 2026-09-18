# Feature: phase4-memory — PKA Fase 4

**Project**: Personal Knowledge Agent (PKA).
**Spec source**: `Personal Knowledge Agent.md`, sections 11–13, 22, 25, 34.
**Branch policy**: commits on `main`.
**Status**: in_progress

## Scope (Phase 4, user-shaped 2026-09-18)

1. **Memory model** (spec §12/§13): `Memory` — id, `type` (semantic | episodic | procedural | preference), `content`, `source` (optional origin), `confidence` (0..1), `status` (candidate | approved | rejected), `created_at`, `updated_at`. SQLite via SQLAlchemy + Alembic migration.
2. **Secret redaction (spec §34)**: `redact_secrets()` — regex patterns (password=, api_key=, token=, Bearer …, `-----BEGIN … PRIVATE KEY-----` blocks, Authorization headers) replaced with a marker, applied to every candidate **before** it is stored.
3. **MemoryExtractor** (spec §13 flow: Conversation → Extractor → Candidate): an LLM-provider-agnostic prompt that turns a conversation (list of `{role, content}`) into a structured JSON array `[{type, content, confidence}]`; robust JSON parsing (code fences, balanced-array recovery, warning on fallback). Candidates are stored with `status=candidate` and redacted content.
4. **Vectors for memories**: `QdrantVectorStore` gains a `collection` parameter (default `knowledge`) so memories live in their own `memories` collection, payload fields `memory_id`/`memory_type`; search/upsert/delete scoped per collection.
5. **Validation gate** (spec §13): `POST /memories/{id}/approve` → approved + vector upsert + **vault mirror write**; `POST /memories/{id}/reject` → rejected + vector/mirror removal; `DELETE` removes everything.
6. **Obsidian mirror (user decision)**: approved memories are written as markdown files under `data/vault/_memories/<type>/<slug>.md` with YAML frontmatter (type, confidence, status) — viewable/editable in Obsidian; vault→DB import of edited mirrors is a future version.
7. **Chat integration (spec §25)**: approved memories are retrieved (semantic, top-k small) alongside documents and injected as a `MEMORY` section in the prompt.
8. **Explicit extraction only (user decision)**: `POST /memories/extract {conversation}` — no automatic per-chat extraction.

## Decisions (user, 2026-09-18)

- Storage: **DB (authoritative) + markdown mirror in vault** (`_memories/`), surveyable/editable in Obsidian.
- Trigger: **explicit endpoints only** (no auto-extraction per chat turn).

## Design notes

- Memory lifecycle: candidate → (approve | reject). Approved memories are the only ones queried by chat; rejected/deleted ones never enter the prompt.
- The mirror is a projection of the authoritative DB row: written on approve, removed on reject/delete. Content file uses Obsidian YAML frontmatter.
- Extraction uses the configured LLM provider (gateway contract unchanged); parsing is lenient because LLM JSON is unreliable.

## Tasks

| # | Task | Status | Commit |
|---|------|--------|--------|
| 1 | `redact_secrets()` (spec §34) + unit tests | done | 6ae6073 |
| 2 | `Memory` model + migration + `MemoryRepository` | done | 6ae6073 |
| 3 | Memory schemas + CRUD routes (list/get/delete, approve/reject status) | done | 6ae6073 |
| 4 | `QdrantVectorStore` multi-collection (`memories`) + constants | done | 6ae6073 |
| 5 | `MemoryExtractor` (LLM JSON candidates, lenient parsing) | in_progress | |
| 6 | Approve/reject side effects: vector upsert/remove + vault mirror | in_progress | |
| 7 | Chat integration: `MEMORY` prompt section (§25) | in_progress | |
| 8 | Tests: redaction, extractor, lifecycle, mirror, chat section | in_progress | |
| 9 | Live E2E (extract real conversation → approve → mirror file → chat uses memory) + README | pending | |

## Acceptance criteria

- `uv run pytest` green; `ruff` clean.
- Conversation → `POST /memories/extract` produces redacted candidates; approve writes the vector + the Obsidian mirror file; reject removes both; chat answers with the approved memory in the prompt.
- Secrets (api_key/password/Bearer/private keys) never reach storage.

## Evidence

- `6ae6073` feat: memory model, secret redaction, CRUD, and multi-collection vectors (tasks 1–4).