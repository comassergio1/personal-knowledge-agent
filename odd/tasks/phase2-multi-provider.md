# Feature: phase2-multi-provider — PKA Fase 2

**Project**: Personal Knowledge Agent (PKA).
**Spec source**: `Personal Knowledge Agent.md`, sections 3, 4, 5, 27, 28, 30, 41.
**Branch policy**: commits on `main` (no fallback feature: manual swap only, user decision 2026-09-17).
**Status**: in_progress

## Scope (Phase 2)

1. **Usage-aware LLM contract (§30)**: `LLMProvider.generate` returns `LLMResult(content, prompt_tokens, completion_tokens, provider, model)`; per-request token accounting in Ollama (`prompt_eval_count`/`eval_count`) and OpenAI-compatible (`usage.*`) providers; graceful when usage is missing.
2. **OpenCode Go live-ready**: default base URL `https://opencode.ai/zen/go/v1` (OpenAI-compatible chat completions), default model `glm-5.3` (documented on `/chat/completions`; `gpt-5.6-luna`/`grok-4.6` use the Responses API — out of scope), headers `x-opencode-session` (stable per app run) + custom User-Agent, clear error only when API key is missing. Live-validated with the user's key from `~/.local/share/opencode/auth.json` (38 models verified reachable).
3. **Config/env**: `OPENCODE_GO_BASE_URL` default, `OPENCODE_GO_MODEL` default, per-provider cost rates (USD per 1k in/out tokens, default 0; OpenCode Go is $10/mo flat — rate 0 with comments).
4. **Cost accounting (§30)**: `llm_usage` table (request_id, provider, model, input_tokens, output_tokens, estimated_cost_usd, latency_ms, created_at) + Alembic migration + repository; `ChatService` records each request; `GET /api/v1/usage` (recent rows, totals, per-provider breakdown).
5. **Live validation**: real chat through OpenCode Go (key read transiently for the run, never persisted by me) and through PayPerQ (user places `PAYPERQ_API_KEY` in `.env`; user-reported here that the key exists and will be added).

## Non-goals (this phase)

- Provider fallback (§29): declined by user; manual swap only.
- Responses-API models (gpt-5.6-luna, grok-4.6) and smart per-intent routing (§5.1).
- Web UI, memory extraction, research, evals.

## Decisions (user, 2026-09-17)

- PayPerQ: key exists; user adds it to `.env` themselves (never passes through the orchestrator). Steps: `cp env.template .env`, set `PAYPERQ_API_KEY=...`.
- Fallback: NO — swap via `LLM_PROVIDER` only.

## Environment facts

- OpenCode CLI 1.18.31; auth stored at `~/.local/share/opencode/auth.json` with keys `opencode` and `opencode-go` (both sk-* 67 chars).
- Verified: `GET https://opencode.ai/zen/go/v1/models` with the Go key → HTTP 200, 38 models (minimax-m3 … glm-5.1). Doc: GLM-5.3/5.3-flash/5.2 on `/chat/completions`; recommended headers: `x-opencode-session` stable per conversation, distinctive User-Agent.
- PayPerQ base `https://api.ppq.ai/v1`, OpenAI-compatible (spec §3).
- Qdrant + Ollama live on this host (slice E2E).

## Tasks

| # | Task | Status | Commit |
|---|------|--------|--------|
| 1 | Providers: `LLMResult` contract + usage parsing (ollama, openai-compatible) | pending | |
| 2 | OpenCodeGoProvider: default endpoint/model, x-opencode-session + User-Agent, key-missing error | pending | |
| 3 | Config/env: GO base URL + model defaults, cost rates (USD/1k in/out); contract test sync | pending | |
| 4 | `llm_usage` table + migration + repository | pending | |
| 5 | ChatService cost recording + `GET /api/v1/usage` (recent + totals) | pending | |
| 6 | Tests: usage parse paths, Go defaults/headers, usage service + endpoint | pending | |
| 7 | Live validation: OpenCode Go chat (real key), PayPerQ chat (user `.env` key); README update | pending | |

## Acceptance criteria

- `uv run pytest` green; `ruff check` clean.
- Chat with `LLM_PROVIDER=opencode_go` answers grounded questions using the real Go key; usage row recorded with tokens; `/api/v1/usage` shows totals.
- Chat with `LLM_PROVIDER=payperq` answers using the user's `.env` key.
- Swapping providers touches no `app/` domain code (only `.env` + Settings).

## Evidence

- Commit ids appended here as units close.