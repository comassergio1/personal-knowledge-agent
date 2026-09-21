**Project**: My NotebookLM — Personal Learning & Knowledge System (`personal-knowledge-agent`).
**Driver**: follow-up de Fase 7 (phase7-learning.md) — el knowledge map alimenta al LLM con slices de 300 chars por chunk; el LLM a veces reporta conceptos como "truncados/vacíos" (honesto pero ruidoso). Pendiente del usuario: revisar el tamaño del slice.

**Branch policy**: commits on `main` (política del repo).
**Status**: done — cerrado en vivo (2026-09-21).

## Scope

1. **`_KNOWLEDGE_EXCERPT` 300 → 1800** en `app/services/knowledge_map.py`: el mismo tamaño de "texto completo del chunk" que ya validó el evaluador de groundedness en Fase 8 (phase8-evals.md: los excerpts de 200 chars no dejaban ver el soporte completo; 1800 sí). Con top-k 6 → ~10.8k chars (~3k tokens), aceptable para el contexto del prompt.
2. **Actualizar el test** `test_knowledge_map_truncates_long_chunk_content_to_300_chars` (tests/unit/test_knowledge_map.py) al nuevo tamaño con el mismo patrón de aserción.
3. **Live E2E**: `GET /api/v1/knowledge/map?topic=...` sobre el stack real con un topic con conocimiento (p.ej. "redes"/"VPN") — verificar que el mapa ya no reporta conceptos "truncados/vacíos" para contenido presente y que duplica menos. README nota si aplica.

## Non-goals

- Cambiar el prompt del mapa (secciones/estilo) ni la dedupe por título.
- Persistir el mapa (sigue response-only en v1).

## Tasks

| # | Task | Status | Commit |
|---|------|--------|--------|
| 1 | `_KNOWLEDGE_EXCERPT` 300 → 1800 + docstring | done | (paquete knowledge-map-slices) |
| 2 | Test actualizado al nuevo tamaño | done | (paquete knowledge-map-slices) |
| 3 | Live E2E (mapa con conocimiento real, sin "truncados" espurios) — README sin cambios (no altera API ni config) | done | (paquete knowledge-map-slices) |

## Acceptance criteria

- `uv run pytest` verde (`499 passed`); `ruff` limpio.
- Live: el knowledge map de un topic conocido muestra conceptos completos, sin reportar contenido presente como vacío/truncado.

## Evidence

- `(paquete knowledge-map-slices)` `_KNOWLEDGE_EXCERPT = 1800` (mismo tamaño que el evaluador de groundedness validó en Fase 8 para ver el soporte completo; con top-k 6 ≈ 10.8k chars, aceptable) + docstrings actualizados + test renombrado a `..._to_1800_chars` (fixture `"x"*500` → `"x"*5000`: 500 < 1800 ya no ejercitaba la truncación).

### Live E2E (task 3, stack real)

- `GET /knowledge/map?topic=VLAN` → mapa jerárquico de 4116 chars; **cero menciones de truncado/vacío**; Conceptos citan contenido real ("Segmentación mediante VLANs en MikroTik RB5009", "VLAN vs. VPN"); Huecos genuinos (definiciones generales, pasos completos, relación VLAN-VPN).
- `topic=VPN` (poco conocimiento) → responde honesto: explica qué contiene el material y qué no, sin inventar.
- Bonus: el `.env` local se había desconfigurado en esta sesión (`CHUNK_OVERLAP=120SEARXNG_LANGUAGES=es,en` concatenados por un append sin newline previo) — detectado por el worker, lo arregló el parent; suite completa verde de nuevo.