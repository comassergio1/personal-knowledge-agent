# Feature: phase8-evals — PKA Fase 8

**Project**: Personal Knowledge Agent (PKA).
**Spec source**: `Personal Knowledge Agent.md`, sections 31–32.
**Branch policy**: commits on `main`.
**Status**: done — evals with adversarial checks; harness returned two real fixes (2026-09-18)

## Scope (Phase 8)

1. **Evaluation model**: `EvalCase` (id, name, question, expected_facts (JSON list), adversarial (bool), project_id nullable, created_at) and `EvalRun` (id, case_id, answer, sources (JSON), metrics (JSON), verdict (pass | fail), created_at) — SQLite/Alembic + repository.
2. **Metrics** (spec §31): per case, computed by an LLM judge (default provider) with a rubric, plus heuristic fallbacks:
   - `correctness` (0..1): expected facts covered by the answer (judge; fallback: normalized token containment).
   - `relevance` (0..1): how on-topic the answer is (judge; fallback: retrieval-score mean).
   - `groundedness` (0..1): every claim supported by the provided sources (judge).
   - `hallucination` (list of claims in the answer NOT supported by sources; ratio as `hallucination_rate`).
   - `source_quality` (0..1): mean retrieval score of the used sources (0 when none).
   - Verdict: PASS when `groundedness >= 0.7` and `correctness >= 0.5` (thresholds configurable in the request); otherwise FAIL.
3. **Adversarial cases** (spec §32): `adversarial: true` cases are questions that embed a false premise (e.g. "Configuramos VLAN 50 para IoT, ¿verdad?" when memory says VLAN 30). The judge also reports `challenged_premise: bool`; adversarial verdict additionally requires a challenged premise (else FAIL with reason).
4. **EvalService** (orchestrator): `run(dataset: list[EvalCaseInput], *, project_id=None, top_k=5, thresholds=None)` → for each case:
   - run the grounded chat flow (reuse ChatService internals or a slim internal path returning answer + sources — NOT the HTTP route),
   - capture the answer, the retrieved sources (title/content/score),
   - judge the case (one LLM call, lenient JSON parse with heuristic fallback),
   - compute metrics/verdict, persist `EvalCase` + `EvalRun`.
5. **API**: `POST /evals/run` (dataset inline or name from `tests/evals/*.json`) → `EvalRunResult` (per-case metrics + verdict + summary counts); `GET /evals/runs` (history, latest first). 422 on empty/invalid dataset; judge/provider errors → per-case marked as failed without aborting the batch.
6. **Sample datasets in-repo** (`tests/evals/mikrotik.json`): a normal dataset (3 facts questions about the vault knowledge: WAN ether8, VLAN assignments, OpenWrt AP steps) + `tests/evals/mikrotik-adversarial.json` (the spec §32 example: "¿Configuramos VLAN 50 para IoT?" expecting the agent to catch that memory/doc says VLAN 30). pytest runs them ONLY when the local stack is available (integration-marked); the metric functions themselves are unit-tested offline with canned judge outputs.

## Design notes

- Judge = one `generate()` call per case with the rubric + sources excerpt; strict prompt instructing JSON output; lenient parse mirrors the memory extractor pattern; heuristic fallback never raises.
- Evals are knowledge-system health checks, not another memory source: runs persist for history, they do not pollute prompts/memories.
- No new dependencies.

## Tasks

| # | Task | Status | Commit |
|---|------|--------|--------|
| 1 | `EvalCase`/`EvalRun` models + migration + repository + schemas | done | 7cbeb6a |
| 2 | Metrics + judge module (rubric prompt, lenient JSON, heuristic fallbacks, verdict/thresholds) | done | 7cbeb6a |
| 3 | `EvalService.run` orchestrator (chat flow capture → judge → metrics → persist) | in_progress | |
| 4 | `POST /evals/run` + `GET /evals/runs` + wiring | in_progress | |
| 5 | Sample datasets in `tests/evals/` (normal + adversarial) + offline unit tests for metrics | in_progress | |
| 6 | Live E2E: run the datasets against the real stack (knowledge + chat + judge) + README | done | efb04a0 + judge-fix + docs |

## Acceptance criteria

- `uv run pytest` green; `ruff` clean.
- On the real stack, the mikrotik dataset PASSes and the adversarial dataset reports the contradiction handling (challenged premise or a clear FAIL with reason) — the spec §32 behavior.
- A failed judge/provider call never aborts the whole batch.

## Evidence

- `7cbeb6a` feat: eval storage and metrics/judge module (tasks 1–2).
- `f068466` feat: eval orchestrator, routes, and sample datasets (tasks 3–5).
- `efb04a0` fix: idempotent ingestion via content hash per project.
- `(fix)` eval judge receives full chunk text, not 200-char excerpts.

### Live verification (task 6, real stack — OpenCode Go glm-5.3)

- mikrotik.json dataset: **3/3 PASS** (groundedness 1.00/0.78/0.80, correctness 1.00, source_quality 0.64–0.73).
- mikrotik-adversarial.json (§32): **PASS**, `challenged_premise: True`, groundedness 1.0 — the agent disputed "VLAN 50 para IoT" citing VLAN 30/50 mapping.
- **The harness returned two real defects, both fixed**: (1) duplicated ingests (repeated smoke uploads) saturated retrieval and hid the WAN/ether8 chunk → content-hash idempotency; (2) the judge graded groundedness against 200-char excerpts → full chunk text now. After both fixes the datasets pass.