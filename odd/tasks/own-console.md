# Feature: own-console — interfaz web propia de My NotebookLM

**Project**: My NotebookLM — Personal Learning & Knowledge System (`personal-knowledge-agent`).
**Driver**: follow-up del usuario (2026-09-18) + plan de despliegue anunciado: correr PKA en la PC-NAS (OpenMediaVault) como stack docker compose (PKA + qdrant + searxng + open-webui), con vault/DB/servicios en esa máquina. La consola debe ser compatible con ese despliegue: estáticos servidos por la app, sin build step, cero dependencias externas.

**Branch policy**: commits on `main`.
**Status**: done — consola web propia funcionando (2026-09-18).

## Scope

1. **Static SPA** served by the FastAPI app at `GET /` + `/static/**` (files under `app/static/`: `index.html`, `app.js`, `styles.css`). Vanilla JS + `fetch` against the existing same-origin API (`/api/v1/*`) — no CORS, no build step, no CDN (must work offline on the LAN container).
2. **Tabs (the PKA-specific things Open WebUI can't show)**:
   - **Chat**: message → `POST /api/v1/chat` → answer + sources list (title/score).
   - **Aprender**: goal + mode (do/learn/deep_learn) + `allow_research` → `POST /learn/run` → tutorial content + needs_research + vault path.
   - **Memorias**: list (filters `?type=&status=`), approve/reject/delete buttons, and an extract box (conversation text → `POST /memories/extract` → candidates).
   - **Vault**: document list (title, project, `stale`), upload file, resync, delete, and the append-section form (PATCH — the two-session workflow).
   - **Mapa**: topic → `GET /knowledge/map` → rendered content.
3. **Markdown rendering, zero-dependency**: minimal client-side formatter (headers `#`–`###`, bold, lists, code fences → `<pre>`), or plain `<pre>` display where formatting is too risky. NO CDN/marked.js (offline).
4. **Minimal styling** (inline CSS, readable). No auth in v1 (LAN; same posture as the API) — documented.
5. **Tests (light)**: `GET /` serves the SPA (200 + contains the app id), `/static/app.js` serves, and the page references the real API base. UI logic is thin JS over already-tested endpoints.

## Design notes / deployment requirements (for the OMV compose stack)

- Console ships inside the app container (static dir) → no extra service.
- PKA already deploys as: FastAPI app (stateless besides `data/`) + qdrant + searxng; config via env (`VAULT_PATH`, `DATABASE_URL`, `QDRANT_URL`, `SEARXNG_URL`, providers). The OMV compose stack will mount volumes for the vault/sqlite/qdrant data, run the three containers + the user's open-webui, and re-expose port 8000/3000. Migration of the current local data to the NAS is a separate deployment task (future session, when the NAS is ready).
- Env note for the future stack: bind the app to `0.0.0.0` inside the container and set `host.docker.internal` equivalents per compose network (services talk by service name, not localhost).

## Tasks

| # | Task | Status | Commit |
|---|------|--------|--------|
| 1 | `app/static/` SPA (index + app.js + styles.css) with the 5 tabs over existing endpoints | pending | |
| 2 | `GET /` + `/static` mount in `app/main.py` | pending | |
| 3 | Tests: static serving + page references | pending | |
| 4 | Live E2E on the real server (page loads, chat + memorize + vault + map calls work from the browser origin) + README | done | 251f1ed + docs |

## Acceptance criteria

- `uv run pytest` green; `ruff` clean.
- Live: `GET http://localhost:8000/` returns the SPA; the flows it drives (chat, learn, memorias approve, vault append, mapa) resolve via the existing API.

## Evidence

- `251f1ed` feat: own static console (5 tabs over the existing API) (tasks 1–3).

### Live E2E (task 4, real server :8000)

- `GET /` serves the SPA (title “My NotebookLM”, dark theme, local assets); `/static/app.js` (text/javascript) and `/static/styles.css` serve; `/api/v1/health` and `/v1/models` still respond (no shadowing).
- A console-driven chat flow resolves (answer + sources with scores) — same-origin works in the browser (user can open http://localhost:8000/).