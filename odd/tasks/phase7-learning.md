# Feature: phase7-learning — PKA Fase 7 (product pivot)

**Project**: My NotebookLM — Personal Learning & Knowledge System (technical package name keeps `personal-knowledge-agent`; user decision 2026-09-18 to rebrand docs, keep the repo name).
**Spec source**: `Memoria local rag/My notebook lm.md` (product change: learning-by-doing core; coding-agent/OpenCode moved OUT of the core pillars to an optional future integration) + `Personal Knowledge Agent.md` (§20 tutorials, §21/§22 research).
**Branch policy**: commits on `main`.
**Status**: in_progress

## Scope (Phase 7 — Learning Engine)

1. **Tutorial depth modes** (spec change §1 of the new doc): `POST /tutorials/generate` gains `mode: "do" | "learn" | "deep_learn"` (default `do`; backwards compatible):
   - `do`: concrete steps only (depth 1).
   - `learn`: steps + per-step rationale ("¿Por qué hacemos esto?") + Conceptos previos (depth 2–3).
   - `deep_learn`: full concepts (e.g. 802.1Q, tagging, trunk/access), theory + practice + exercises + evaluation (depth 4).
   - Structure grows per mode; core headers stay (Objetivo, Paso a paso, Verificación, Troubleshooting, Fuentes); extended: Qué vas a aprender, Conceptos previos, Preparación, ¿Por qué hacemos esto?, Problemas frecuentes, Ejercicios, Resumen. The response carries the mode.
2. **Learning loop orchestrator** (new doc "La idea central"): `POST /learn/run {goal, mode="learn", project_id?, title?, allow_research=true, research_threshold=0.5}`:
   1. assess: retrieve the goal; when the top retrieval score is below `research_threshold` (or no hits) → knowledge insufficient.
   2. research on demand: when insufficient and `allow_research`, run the research agent (its report lands in the vault + index, so re-retrieval includes it).
   3. generate: build the tutorial with the requested mode (now grounded on own knowledge + the fresh research report).
   4. return `LearnResult{goal, mode, needs_research, research?: {document_id, file_path}, tutorial: {document_id, file_path, content, sources}}` + a reflect hint.
   - `POST /learn/reflect {goal, what_i_learned, project_id?}` → builds a short conversation and runs the memory extractor → returns **candidate memories** ("¿Qué aprendí?" → Aprendizajes/Experiencias, spec memory types cover it).
3. **Knowledge map** (new doc "¿Qué sé sobre X?"): `GET /knowledge/map?topic=&project_id=` → embed the topic, retrieve approved memories + documents (top-k each), LLM builds a hierarchical knowledge map markdown (Conceptos / Tutoriales / Experiencias / Recursos / huecos), citing titles. Response-only in v1.
4. **Rebrand (docs only)**: README headline/status → "My NotebookLM — Personal Learning & Knowledge System"; OpenCode section rewritten as an optional future integration (no code); roadmap updated. Repo name stays.

## Non-goals (this phase)

- OpenCode/coding-agent adapter (deferred, documented as optional plugin): the product pivot removes it from the core.
- LangGraph; knowledge-graph storage (the map is generated on demand, not persisted).

## Design notes

- The learning loop reuses existing services (retrieval, research, tutorials, memory) — no new dependencies; research is the expensive step, gated by the threshold.
- Tutorial modes only change the prompt scaffolding + structure contract, so provider/domain code stays untouched (same gateway).
- Knowledge map is generated on demand over approved memories + documents; it never writes to the vault in v1.

## Tasks

| # | Task | Status | Commit |
|---|------|--------|--------|
| 1 | Tutorial `mode` (do/learn/deep_learn): prompt variants + structure + tests | done | d9db528 |
| 2 | `LearnService.run` loop (assess → research on-demand → tutorial) + tests | done | d9db528 |
| 3 | `LearnService.reflect` (¿qué aprendí? → memory candidates) + tests | done | d9db528 |
| 4 | `KnowledgeMapService` + `GET /knowledge/map` + tests | in_progress | |
| 5 | Routes + wiring (tutorials mode, learn, knowledge-map) + integration tests | in_progress | |
| 6 | Rebrand README (My NotebookLM) + Live E2E (full learn cycle w/ research + reflect + map) | pending | |

## Acceptance criteria

- `uv run pytest` green; `ruff` clean.
- Live: `POST /learn/run` with a goal absent from the knowledge base (e.g. VPN) triggers research, produces a mode-aware tutorial in the vault, `learn/reflect` yields memory candidates, and `GET /knowledge/map?topic=redes` returns a coherent map citing own knowledge.
- Mode-aware prompts verified via captured prompts in unit tests.

## Evidence

- `d9db528` feat: tutorial depth modes and learning-loop orchestrator (tasks 1–3).