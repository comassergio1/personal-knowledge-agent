# Feature: openai-shim — OpenAI-compatible surface for My NotebookLM

**Project**: My NotebookLM — Personal Learning & Knowledge System (`personal-knowledge-agent`).
**Driver**: user question 2026-09-18 (web UI path decision): expose PKA as an OpenAI-compatible provider so the already-running Open WebUI (port 3000) becomes the chat UI while PKA keeps ownership of knowledge/memory. Optional later: a minimal own console for memory/vault/learn/map.

**Branch policy**: commits on `main`.

## Scope

1. `POST /v1/chat/completions` (OpenAI wire format):
   - accepts `{model, messages: [{role, content}], stream?, temperature?, max_tokens?}`; the **last user message** is the query (multi-turn history summarization is a later enhancement; the model field is accepted and intentionally ignored — the provider stack is fixed by settings).
   - internally runs the **grounded chat** (retrieval + approved memories + sources, spec §25) via the shared `ChatService`;
   - response shape: `{id, object: "chat.completion", created, model, choices: [{index, message: {role: "assistant", content}}, finish_reason]}` — content = answer + a markdown `**Fuentes:**` block listing the retrieved titles (grounding visible in the client);
   - `usage` reflects tokens when available (`ChatResult` gains optional token counts); graceful when unknown.
   - `stream: true` is honored with a minimal **SSE pseudo-stream** (OpenAI delta format: one content delta + finish chunk + `data: [DONE]`) so clients like Open WebUI work.
2. `GET /v1/models` → `{object: "list", data: [{id: "my-notebooklm", object: "model", owned_by: "pka"}]}` (single model).
3. Prefix mount: `/v1` routes mounted alongside `/api/v1` (no collision).
4. **No auth in v1** (LAN/personal server; the app binds to the host). Open WebUI connects as an OpenAI provider at `http://host.docker.internal:8000/v1` on Docker Desktop.
5. Architectural guard: Open WebUI must be used as a **client only** — its own RAG/document features stay off so knowledge lives exclusively in PKA (spec: no split memory).

## Non-goals

- Own console UI (follow-up); OpenAI Responses API; tool/function calling; per-request provider selection; multi-user auth; chat history summarization.

## Design notes

- No new dependencies: the `messages`/SSE handling is plain Pydantic + FastAPI `StreamingResponse`.
- `ChatResult` gains optional `prompt_tokens`/`completion_tokens` (additive; `/api/v1/chat` response may expose them too).
- The `model` string `my-notebooklm` is a module constant surfaced by `/v1/models`.

## Tasks

| # | Task | Status | Commit |
|---|------|--------|--------|
| 1 | `ChatResult` token counts (additive) + schemas | pending | |
| 2 | `/v1/models` + `/v1/chat/completions` (non-stream + SSE pseudo-stream) + sources block | pending | |
| 3 | Wiring + tests (unit format/edge + integration via test app) | pending | |
| 4 | Live E2E: real server curl + `host.docker.internal` reachability + connect Open WebUI (user click-path documented) + README | pending | |

## Acceptance criteria

- `uv run pytest` green; `ruff` clean.
- `curl POST /v1/chat/completions` (and with `stream: true`) returns valid OpenAI-format responses with the grounded answer + Fuentes block; `/v1/models` lists `my-notebooklm`.

## Evidence

- Commit ids appended here as units close.