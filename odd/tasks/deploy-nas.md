# Feature: deploy-nas — stack docker compose para el servidor (OpenMediaVault)

**Project**: My NotebookLM — Personal Learning & Knowledge System (`personal-knowledge-agent`).
**Driver**: usuario (2026-09-18): correr el sistema en su PC-NAS con OpenMediaVault como stack docker compose; vault/DB/servicios viven en esa máquina; Open WebUI también corre ahí.
**Decisions (user 2026-09-18)**: chat en nube (opencode-go / payperq) con Ollama SOLO para embeddings (nomic-embed-text); puertos expuestos solo app:8000 (consola+API) y open-webui:3000; todo lo demás por red interna del stack.

**Branch policy**: commits on `main`.
**Status**: done — paquete + variante light (2026-09-18).

## Deliverables (deploy/nas/)

1. **`Dockerfile`** — image `pka` desde la raíz del repo (context `../..`): python:3.12-slim + uv, `uv sync --frozen --no-dev`, copia `app/` + `migrations/` + `alembic.ini`, CMD `uv run uvicorn app.main:create_app --factory --host 0.0.0.0 --port 8000`. Nota: corre como root dentro del contenedor para simplificar volúmenes en OMV (documentado).
2. **`docker-compose.yml`** — proyecto `pka-nas`, red interna compartida:
   - `app` (build Dockerfile, env desde `.env` + defaults: DATABASE_URL sqlite `//data/app.db`, VAULT_PATH `/data/vault`, QDRANT_URL=http://qdrant:6333, SEARXNG_URL=http://searxng:8080, OLLAMA_BASE_URL=http://ollama:11434, EMBEDDING_PROVIDER=ollama, EMBEDDING_MODEL=nomic-embed-text, LLM_PROVIDER/KEY desde .env; ports 8000:8000; volúmenes: bind `./vault:/data/vault` (editables vía SMB/Obsidian) + bind `./data:/data/app` + bind qdrant_sync; restart unless-stopped).
   - `qdrant` (imagen, volumen `./qdrant_storage:/qdrant/storage`, sin puertos).
   - `searxng` (imagen + settings `../config/searxng/settings.yml:ro` + cache `./searxng_cache:/var/cache/searxng`, sin puertos).
   - `ollama` (imagen, `./ollama_data:/root/.ollama`, entrypoint: sirve + `ollama pull nomic-embed-text` al arrancar, sin puertos).
   - `open-webui` (ghcr main image, ports 3000:8080, `./open_webui_data:/app/backend/data`, habitually connected a Ollama in-stack; conexión a PKA documentada vía `http://app:8000/v1` — en la UI o, si la versión lo soporta, env de “OpenAI API base”; comentado).
3. **`.env.example`** — LLM_PROVIDER (default `opencode_go`), OPENCODE_GO_API_KEY, OPENCODE_GO_MODEL=glm-5.3, PAYPERQ_* opcionales, notas de secretos.
4. **`README.md` (deploy/nas)** — runbook: requisitos OMV (compose plugin, carpetas), clone del repo en la NAS, primer arranque (`docker compose up -d`, `docker compose exec app uv run alembic upgrade head` — alternativa: init_db del lifespan), migración de dato local→NAS (rsync vault + `data/app.db` + `qdrant_storage` con ambos stacks apagados; nota: las memorias vectorizadas viven en qdrant), abrir el vault vía SMB en Obsidian, primer login de Open WebUI + elegir `my-notebooklm`, push a GitHub opcional, backup rutinario, notas de seguridad LAN.

## Design notes

- PKA ya es compose-friendly: config por env, único estado mutable = `data/` (vault + sqlite) y vectores en qdrant; la consola viaja en la misma app (un contenedor).
- Bind mounts (no named volumes) en las rutas del “docker share” de OMV → vault legible/editable desde SMB y backups simples (rsync del directorio del deploy).
- Migración de datos: copiar `vault`, `data/app.db` y `qdrant_storage` (los vectores de documentos y memorias). Alternativa posterior: re-indexar docs con `/vault/sync`; las memorias NO se re-vectorizan solas → copiar qdrant_storage.
- Seguridad: LAN-only; la app no tiene auth en v1 (postura documentada); firewall OMV recomendado.
- No se toca el compose dev del repo (sigue para desarrollo local).

## Tasks

| # | Task | Status | Commit |
|---|------|--------|--------|
| 1 | Dockerfile + compose (app/qdrant/searxng/ollama/open-webui) + .env.example | done | (paquete deploy-nas) |
| 2 | Runbook `deploy/nas/README.md` (arranque, migración, SMB/Obsidian, OWUI, backup) | done | (paquete deploy-nas) |
| 3 | Validación: `docker build`, `docker compose config`, boot smoke de la imagen contra servicios host | done | (paquete deploy-nas) |
| 4 | Referencia en README raíz + commit | done | (paquete deploy-nas) |
| 5 | Variante light: open-webui detrás de `profile: ui` (default = cerebro sin UI) + retry de arranque del app (orden al boot) + test | done | (light) |
| 6 | Runbook actualizado: light/full, swapfile 4GB, escala a 8GB | done | (light) |

## Acceptance criteria

- `docker build` de la imagen OK; `docker compose -f deploy/nas/docker-compose.yml config` válido; la imagen arranca y `/api/v1/health` responde.
- Runbook paso a paso listo para ejecutar en OMV.

## Evidence

- `(paquete deploy-nas)` Dockerfile + compose + env.template + runbook + referencia README.

### Validación live (task 3)

- `docker build -f deploy/nas/Dockerfile` → image `pka:local` OK (fix: README.md debe copiarse a la capa de deps — hatchling lo exige).
- `docker compose config` válido (env_file `.env` string; la validación se hizo sobre copia temporal con `env.template` para no crear `.env` — política Pi; nota: la forma objeto `required:false` no la acepta Compose v5).
- Boot smoke de la imagen contra los servicios del host: `/api/v1/health` → `{qdrant: true, ollama: true}`; la consola sirve; `/v1/models` → `my-notebooklm`. (El primer intento con `LLM_PROVIDER=opencode_go` sin key crashea el startup como está diseñado — el `.env` del stack provee la key.)