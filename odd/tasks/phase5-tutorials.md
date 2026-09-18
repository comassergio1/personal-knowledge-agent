# Feature: phase5-tutorials — PKA Fase 5

**Project**: Personal Knowledge Agent (PKA).
**Spec source**: `Personal Knowledge Agent.md`, sections 19–20, 25, 37 (Learn mode).
**Branch policy**: commits on `main`.
**Status**: in_progress

## Scope (Phase 5)

1. **TutorialGenerator service** (spec §20): `generate(objective, *, project_id=None, title=None) -> TutorialResult`:
   - Retrieval: embed the objective → top-k document chunks from the project/all knowledge + approved memories (`MemoryService.search_approved`) — the tutorial **adapts to retrieved knowledge and the user's memory preferences**.
   - Prompt (spec §25 pattern): SYSTEM (tutorial writer persona; structure contract; Spanish content because the user's knowledge/tutorials are Spanish — the spec §20 headers are Spanish) + `MEMORY` + `KNOWLEDGE` + `USER REQUEST` sections.
   - Output: markdown following the spec §20 structure — `# Objetivo`, `# Prerrequisitos`, `# Materiales`, `# Paso N…`, `# Verificación`, `# Troubleshooting`, `# Errores comunes`, `# Rollback`, `# Fuentes` — with the retrieved sources listed under Fuentes.
   - Light post-check: warn (never fail) when `# Objetivo`/`# Fuentes` are missing from the LLM output.
2. **Vault + immediate indexing**: the generated tutorial is written to the vault (`project` folder when `project_id` given else `inbox`, slugged filename) AND ingested right away via `IngestionService` so it is searchable and visible in Obsidian without a manual sync (ingest records `file_mtime`, so a later `POST /vault/sync` sees no change).
3. **API**: `POST /tutorials/generate {objective, project_id?, title?}` → `TutorialRead` (document id, title, file_path, content, sources `[{title, score}]`). Re-reading / deleting / syncing reuses the existing documents endpoints.
4. Explicit endpoint only (chat intent detection for `TUTORIAL` is a later enhancement — spec §19 stays a roadmap item).

## Design notes

- Content language: **Spanish** (the spec's tutorial structure and the user's knowledge are Spanish); code/comments stay English.
- Sources are surfaced to the model for grounding and to the user in the response `sources`.
- No new dependencies.

## Tasks

| # | Task | Status | Commit |
|---|------|--------|--------|
| 1 | `TutorialService.generate`: retrieval (docs + memories), §20/§25 prompt, LLM call, markdown + sources | pending | |
| 2 | Vault write + immediate ingest (reuse VaultService/IngestionService) | pending | |
| 3 | `POST /tutorials/generate` + schema + wiring (main/dependencies) | pending | |
| 4 | Tests: prompt assembly, memories in prompt, write+ingest, response shape | pending | |
| 5 | Live E2E (real stack: generate a guest-VLAN tutorial adapted to Home Lab knowledge + step-by-step preference) + README | pending | |

## Acceptance criteria

- `uv run pytest` green; `ruff` clean.
- `POST /tutorials/generate` returns a Spanish markdown tutorial with the §20 headers, grounded in retrieved knowledge and personalized by approved memories; the file lands in the vault and is immediately searchable (GET /documents works on it, chat can cite it).

## Evidence

- Commit ids appended here as units close.