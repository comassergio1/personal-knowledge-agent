# Feature: chat-web-research — investigación web desde el chat

**Project**: My NotebookLM — Personal Learning & Knowledge System (`personal-knowledge-agent`).
**Driver**: follow-up elegido tras la sesión 2026-09-18 — el chat pedía "investigá en la web…" y respondía "no puedo navegar" (evidencia live). Cierra la brecha: *"¿Falta información? → Research web"* (spec §21) dentro del flujo conversacional.

**Branch policy**: commits on `main`.

## Scope

1. **Intent detection** (spec §19 RESEARCH intent, v1 heurística): a small curated, case-insensitive trigger list applied to the last user message — e.g. `investigá (en)? (la )?(web|internet)`, `buscá fuentes`, `buscá en la web`, `buscá en internet`, `investiga`, `research`, `look up on the web`, `search the web`… (module constant; falsos positivos documentados). Message length cap (e.g. 400 chars) to avoid huge research inputs.
2. **Routing in the OpenAI-compatible shim** (`/v1/chat/completions`): when triggered, call the shared `ResearchService.run(question, …)` (synchronous; the report persists to the vault + index by its own behavior), then respond with the OpenAI response whose content = a short header (informe + ruta del archivo en el vault) + the report markdown (structured Spanish with sources already). No extra LLM call.
   - On `ResearchError` → OpenAI error envelope (500-type) with a clear message; the chat does not silently fall back (honesty: the user asked for research).
   - Non-trigger messages keep the current grounded chat.
3. **Wiring**: `v1_compat` gains the research service via dependency (`get_research_service`); testing seam already provides an offline fake.
4. **Known trade-offs (documented)**: research takes ~1–3 min synchronously; Open WebUI clients with short timeouts may cut long waits (acceptable personal use; async answer later).

## Non-goals

- Intent detection on `/api/v1/chat` (same helper could be reused later), LLM-based intent classification, async job queue, per-project research scoping beyond the existing source defaults.

## Tasks

| # | Task | Status | Commit |
|---|------|--------|--------|
| 1 | Research intent detection (curated patterns, case-insensitive, length cap) + unit tests | pending | |
| 2 | Shim routing: research trigger → `ResearchService.run` → report in the response (header + file path + markdown) | pending | |
| 3 | Error envelope for failed research + integration tests | pending | |
| 4 | Live E2E: repeat the exact "investigá en la web…" that previously refused; report lands in the vault; README | pending | |

## Acceptance criteria

- `uv run pytest` green; `ruff` clean.
- Live: the same question that answered "no puedo navegar" now triggers a real research run and returns the report with sources; the vault file exists.

## Evidence

- Commit ids appended here as units close.