# Feature: research-session — "Explorar": sesión conversacional de investigación

**Project**: My NotebookLM — Personal Learning & Knowledge System (`personal-knowledge-agent`).
**Driver**: follow-up del usuario (2026-09-24) — quiere entender cómo funciona la búsqueda web y tener una sesión tipo ChatGPT donde investigar en la web interactivamente y al final guardar los puntos importantes como tutorial. La feature chat-history (multi-turno en chat/shim) queda separada; esta es la sesión de investigación.

**Branch policy**: commits on `main` (política del repo).
**Status**: in-progress (2026-09-24).

## Decisiones del usuario (cerradas, 2026-09-24)

1. **Persistencia**: server-side — tablas nuevas en SQLite (`research_sessions`, `research_turns`) + endpoints. La sesión sobrevive al refresco; dejamos sembrado el terreno para chat-history.
2. **Búsqueda web**: solo a pedido explícito. Disparadores curados: "buscar en la web", "busca en internet" (y variantes voseo "buscá en internet", "investigá en la web", "investigar en la web"...). Sin disparador → respuesta grounded en el vault (con el contexto acumulado de la sesión). NO usar los disparadores anchos de `research_intent` (false positives documentados); solo verbo + ubicación explícitos.
3. **Nombre de pestaña**: "Explorar".

## Scope

1. **Modelos + migración Alembic**: `research_sessions` (id UUID, title, created_at, updated_at) y `research_turns` (id, session_id FK, role user|assistant, content, kind `answer`|`research`, research_document_id nullable, sources JSON nullable, created_at). Patrón de repositorio existente (session app-lifetime, `Repository` async).
2. **`ResearchChatService`**: orquesta una sesión:
   - Turno con disparador web → `ResearchService.run(target)` (target = mensaje menos la frase disparadora; si queda vacío, usar el título/último tema de la sesión) → informe persistido en vault → respuesta = resumen corto del informe + file_path + sources. Preflight `SearchProvider.ping()` (503 con mensaje reutilizable de research route).
   - Turno sin disparador → respuesta grounded: prompt propio (SYSTEM + MEMORY + KNOWLEDGE + HISTORY + USER REQUEST) sobre retrieval del vault + contexto acumulado de la sesión (turnos previos + informes). Reutilizar retrieval/memory como `ChatService`.
   - Guardado como tutorial: `TutorialService.generate` (retrieval ya verá los informes persistidos) + `persist` con mode do|learn|deep_learn → devuelve file_path + content.
3. **Rutas** (prefix `/api/v1/research/sessions`, no chocar con `/api/v1/research/run`): POST crear sesión, GET listar, GET detalle (con turns), POST `/{id}/turn {message}`, POST `/{id}/tutorial {mode}`. Wiring en `app/main.py` + `app/api/dependencies.py`.
4. **Consola — tab "Explorar"** (entre Aprender y Memorias): lista de sesiones (crear nueva / retomar), vista de hilo, input, hint de disparadores, botón "Guardar como tutorial" + select de modo, muestra file_path del tutorial. Copy en español.
5. **Tests**: unit (detección de disparadores, extracción de target, repository) + integration (flujo session→turn con/sin disparador→tutorial con los fakes offline de `testing=True`). README: sección corta de la nueva pestaña.

## Non-goals

- Multi-turno en chat `/api/v1/chat` ni en shim `/v1` (eso es chat-history, candidata separada).
- Cambiar Aprender ni el detector de desconocimiento (umbral 0.5) — mejora aparte.
- Research automático por turno (decidido: solo a pedido).
- Autenticación (postura v1: red local, sin auth).

## Tasks

| # | Task | Status | Commit |
|---|------|--------|--------|
| 1 | Modelos (`research_sessions`, `research_turns`) + migración Alembic + repository | pending | |
| 2 | `ResearchChatService` (disparadores + grounded + tutorial) | pending | |
| 3 | Rutas session/turn/tutorial + wiring (main.py, dependencies) | pending | |
| 4 | Consola: tab Explorar (thread, triggers, guardar tutorial) | pending | |
| 5 | Tests unit + integration + README | pending | |
| 6 | Live E2E en server real + commit work-unit (orchestrator) | pending | |

## Acceptance criteria

- Crear sesión → enviar "explicame X" → respuesta grounded del vault con fuentes (sin tocar web; log investigación no ejecutada).
- Enviar "buscar en la web X" → corre §21 (SearXNG + informe persistido en vault) → respuesta resume el informe y muestra file_path + fuentes.
- "guardame un tutorial" / botón → genera tutorial modo elegido, persistido en vault, con file_path devuelto a la UI.
- Sesión persiste entre peticiones/refrescos (server-side); listado retoma sesiones viejas.
- `uv run pytest -x -q` green; `uv run ruff check` clean; alembic upgrade head aplica sobre la DB existente sin tocar datos.

## Evidence

- (se llena al cerrar)