# Despliegue en tu servidor (OpenMediaVault) — stack docker compose

Este directorio es el paquete de despliegue de **My NotebookLM** en tu PC-NAS.
Corre todo el sistema (app + Qdrant + SearXNG + Ollama-embeddings + Open WebUI)
en un solo stack docker compose, con los datos en tu disco (vault incluido).

**Decisiones de producto aplicadas:**

- El **chat usa la nube** (OpenCode Go por default; PayPerQ opcional — `.env`).
- **Ollama corre en el stack solo para embeddings** (`nomic-embed-text`).
- Se exponen **solo** los puertos `8000` (consola + API) y — si corres el perfil
  completo — `3000` (Open WebUI); Qdrant, SearXNG, Ollama y el app se hablan
  entre sí por la red interna.

## Variante light por defecto (4 GB) vs. completa

El stack arranca **sin Open WebUI** por defecto (perfil `ui` apagado): eso
libera ~400–800 MB, la diferencia entre andar o swapear en una máquina de
4 GB con Nextcloud. Para levantar la UI completa solo cuando la RAM lo
permita:

```bash
docker compose --profile ui up -d   # agrega Open WebUI (:3000)
```

| Escenario | RAM libre | Recomendación |
|---|---|---|
| 4 GB + Nextcloud | ~0 | **light** (este stack sin `--profile ui`) + swapfile de 2 GB |
| 8 GB | cómodo | stack completo (`--profile ui`) |
| 16 GB | sobra | completo |

Swap en OMV (una sola vez): `fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile` y agregar al fstab para que persista.

## Requisitos en la NAS (OMV)

- Docker + el plugin **docker-compose** (compose v2).
- Una carpeta base para el stack, p. ej. `/srv/docker/pka/`.
- Git (o descargás el repo como zip).

## Primer arranque

```bash
# 1) Cloná el repo en la NAS (una sola vez)
cd /srv/docker/pka
git clone https://github.com/comassergio1/personal-knowledge-agent.git
cd personal-knowledge-agent/deploy/nas

# 2) Configuración
cp env.template .env          # → poné tu OPENCODE_GO_API_KEY (y PayPerQ si querés)
nano .env

# 3) Levantá el stack (la primera vez baja ~3 GB de imágenes)
docker compose up -d --build

# 4) Esquema de base de datos (alembic = canónico; el app igual crea tablas en
#    el primer arranque por su fallback init_db)
docker compose exec app uv run alembic upgrade head

# 5) Estado
docker compose ps            # todos "healthy"/"running"
docker compose logs -f app   # si algo falla
```

**Probá:** `http://<ip-de-la-nas>:8000/` (consola) y `http://<ip-de-la-nas>:3000/`
(Open WebUI — primer login: creás el usuario administrador).

## Migrar tu conocimiento desde la Mac (una sola vez)

Con **ambos lados apagados** (la Mac: `pkill -f uvicorn`; la NAS: `docker compose down`):

```bash
# En la Mac, el repo local —
cd ~/Documents/proyectos_mios/personal-knowledge-agent

# 1) El vault (markdowns)
rsync -av data/vault/ <nas>:/srv/docker/pka/personal-knowledge-agent/deploy/nas/vault/

# 2) La base SQLite
rsync -av data/app.db <nas>:/srv/docker/pka/personal-knowledge-agent/deploy/nas/data/

# 3) LOS VECTORES — importante: las memorias aprobadas viven en Qdrant y se
#    pierden si no copiás su storage. (Los documentos se pueden re-indexar con
#    /vault/sync; las memorias NO.)
#    En la Mac el volume es /var/lib/docker/volumes/personal-knowledge-agent_qdrant_data/_data
sudo rsync -av /var/lib/docker/volumes/personal-knowledge-agent_qdrant_data/_data/ \
  <nas>:/srv/docker/pka/personal-knowledge-agent/deploy/nas/qdrant_storage/
```

Después: `docker compose up -d` en la NAS y verificá con la consola que tus
documentos y memorias estén.

## Obsidian + tu vault

- En OMV creá un **shared folder** que apunte a `deploy/nas/vault` y expongas
  por SMB (usuarios de OMV, permisos de escritura).
- En tu Mac: Abrir carpeta como vault → `smb://<nas>/<share>`.
- Editás una nota → la consola la marca `stale`; `POST /vault/sync` (o el botón
  de la consola) la re-indexa.

## Open WebUI → chat grounded

- **Open WebUI** → Settings → Connections/Model Providers → **OpenAI API**:
  - URL: `http://app:8000/v1` si abrís la UI desde la NAS, o
    `http://<ip-de-la-nas>:8000/v1` desde tu navegador/red.
  - Key: cualquier valor.
  - Modelo: `my-notebooklm`.
- Regla de oro: Open WebUI es **cliente**; no le subas tus documentos (el
  conocimiento vive solo en PKA).

## Backup rutinario

Todo el stack vive en `deploy/nas/` → un rsync de esa carpeta (sin imágenes)
es tu respaldo:

```bash
rsync -av --exclude open_webui_data/ollama --exclude ollama_data/models \
  /srv/docker/pka/personal-knowledge-agent/deploy/nas/ \
  /backup/pka/
```

Más simple todavía: un cron en OMV que haga eso diariamente.

## Seguridad

- Es un servicio **LAN-only**: la app no tiene autenticación (v1) — no
  exposes el puerto 8000 a internet y mantené el firewall de OMV en LAN.
- Las API keys viven en `deploy/nas/.env` (no en la base de conocimiento).

## Arranque automático al encender la PC

Con `restart: unless-stopped`, Docker Engine arranca los contenedores solo en
cada boot (incluido el encendido remoto/WoL) — no hay que configurar nada más.
Al arrancar, el app **reintenta hasta ~50s** mientras qdrant se inicializa, así
que el orden del boot no rompe nada (se auto-cura). La primera vez que Ollama
arranca hace `ollama pull nomic-embed-text` (una vez; después es un no-op).

## Troubleshooting rápido

| Síntoma | Qué mirar |
|---|---|
| `app` reinicia | `docker compose logs app` — asegurate que qdrant esté healthy (depende de él) |
| `/api/v1/health` → qdrant false | `docker compose logs qdrant` |
| Chat dice que no investiga | `docker compose logs searxng` (engines) y verificá `/search?format=json` |
| `ollama` lento en el primer arranque | baja `nomic-embed-text` (~0.3 GB); las respuestas de chat no lo usan |
| Open WebUI no ve `my-notebooklm` | revisá la URL del provider (debe ser `/v1`) y la key no vacía |