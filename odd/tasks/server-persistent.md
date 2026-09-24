**Project**: My NotebookLM — Personal Learning & Knowledge System (`personal-knowledge-agent`).
**Driver**: follow-up de document-append.md — el server se levanta con `nohup` manual y hay que reiniciarlo a mano tras cada boot; pendiente del usuario: servidor persistente (launchd/service).

**Branch policy**: commits on `main` (política del repo).
**Status**: done — servidor persistente bajo launchd verificada en vivo (2026-09-24).

## Scope

1. **`scripts/run_server.sh`**: wrapper reproducible del comando exacto de producción local — `cd` al repo, `uv run uvicorn app.main:create_app --factory --host 0.0.0.0 --port 8000`. Bash estricto (errexit), lock simple para no duplicar instancias.
2. **`scripts/install_launchagent.sh`**: instala/desinstala/status del LaunchAgent de usuario `~/Library/LaunchAgents/com.my-notebooklm.server.plist`:
   - `RunAtLoad` + `KeepAlive` (solo reinicia tras salida inesperada: `SuccessfulExit=false`).
   - `WorkingDirectory` = repo, `ProgramArguments` = `run_server.sh`.
   - Logs: `~/Library/Logs/my-notebooklm/{server,server-err}.log`.
   - Subcomandos `install | uninstall | status | logs`; instalar no sobre-escribe un agente existente sin `--force`.
3. **README**: sección corta "Run in background" — instalar el agente, requisitos en boot (Qdrant ya con `restart: unless-stopped` en compose; nota: `brew services start ollama` para embeddings persistentes, aunque el chat hoy va por PayPerQ).
4. **Live**: instalar el agente, recargar launchd, verificar que el puerto 8000 responde y que el proceso es hijo de launchd; dejar instalado (fue el pedido); documentar uninstall. **Entregado en** `~/proyectos/personal-knowledge-agent` (ver Blocker).

## Non-goals

- Daemonizar Qdrant/SearXNG fuera de Docker (ya corren con compose; qdrant con restart policy).
- Multi-user, entorno prod/NAS (eso es deploy/nas, feature separado).
- Espera de dependencias en el agente (la app ya tiene boot retry de colecciones; si Qdrant no está arriba al boot, el health lo reporta).

## Tasks

| # | Task | Status | Commit |
|---|------|--------|--------|
| 1 | `scripts/run_server.sh` (wrapper, errexit, lock) | done | (script en working tree) |
| 2 | `scripts/install_launchagent.sh` (install/uninstall/status/logs + plist) | done | (script en working tree) |
| 3 | README "Run in background" | done | (README en working tree) |
| 4 | Live: instalar, verificar bajo launchd, dejar corriendo | done | |

## Blocker (TCC, macOS) — 2026-09-24

El agente queda en crash loop (`runs=28242`, `last exit code=126`) con
`Operation not permitted` al ejecutar `run_server.sh`. Diagnóstico con prueba
aislada (dos LaunchAgents idénticos, script en `/tmp` vs `~/Documents`): el
agente con script en `/tmp` corre OK; el de `~/Documents` falla con EPERM al
`getcwd`. Causa: TCC protege `~/Documents`; los procesos de la sesión
interactiva tienen permiso, los lanzados por launchd no (y launchd no puede
mostrar el popup de permiso → denegación silenciosa). Re-bootstrap desde una
sesión con acceso no cambia la atribución.

Decisión final del usuario (2026-09-24): **mover el repo fuera de
`~/Documents`** — cero permisos especiales, solución permanente. `mv` a
`~/proyectos/personal-knowledge-agent` conservando el nombre de carpeta
(project name de docker compose idéntico → volúmenes `qdrant_data`/
`searxng_data` intactos; único bind mount es relativo). Se descartó FDA a
`/bin/bash` (permiso ancho: cualquier script bajo bash tendría acceso a todos
los datos protegidos) y el launcher propio (costo extra sin beneficio vs.
la relocación).

### Hallazgos adicionales del live (2026-09-24)

- **El venv no es reubicable**: mover el repo rompe los shebangs de
  `.venv/bin/*` (apuntan a la ruta absoluta vieja) → `uv run` falla con
  "Failed to spawn: `uvicorn`: No such file or directory (os error 2)". Fix:
  `rm -rf .venv && uv sync` (uv lo regenera desde `uv.lock`, caché local).
- **Race bootout/bootstrap en launchd**: tras uninstall, `bootout` puede
  devolver 0 dejando un ghost del label; el `bootstrap` posterior falla
  ("already loaded") y el fallback legacy `load -w` "confirma" sin registrar
  nada. Fix aplicado en `install_launchagent.sh`: bootout defensivo antes de
  cada bootstrap. El round-trip uninstall→install quedó verificado.

## Acceptance criteria

- `plutil -lint` valida el plist; `launchctl print` muestra el servicio cargado; `curl :8000/api/v1/health` responde sin intervención manual tras install.
- Uninstall documentado y funcional.

## Evidence

- 2026-09-24: plist lint OK (`plutil -lint`); diagnóstico TCC con dos agentes
  de prueba (A=/tmp OK, B=Documents EPERM).
- 2026-09-24 live (2ª instancia, `~/proyectos/...`): `launchctl print` →
  `state = running`, `pid = 2369`, `last exit = (never exited)`;
  `ps -o ppid` → **1** (hijo de launchd); `curl :8000/api/v1/health` →
  `{"status":"ok","qdrant":true,"ollama":true}`; stderr log limpio
  (uvicorn startup complete).
- Round-trip uninstall→install verificado (script con bootout defensivo).
- **Deliverable**: agente instalado y corriendo bajo launchd; README
  documenta install/uninstall/status/logs.