**Project**: My NotebookLM — Personal Learning & Knowledge System (`personal-knowledge-agent`).
**Driver**: follow-up de Fase 6 (phase6-research.md) — la búsqueda en español devolvía sobre todo hilos de Reddit (tier 1 del ranking) y pocas fuentes oficiales; el follow-up pedía "consultas en inglés o más engines". Pendiente del usuario: tuning SearXNG.

**Branch policy**: commits on `main` (política del repo).
**Status**: done — cerrado en vivo (2026-09-21).

## Scope

1. **Engines curados en `config/searxng/settings.yml`**: definir un set explícito orientado a documentación oficial y publicaciones (wikipedia, wikidata, arxiv, pubmed, crossref, europepmc, google scholar, semantic scholar, openalex, duckduckgo, brave, sistemas/wikis técnicas: arch linux wiki, gentoo, nixos wiki, free software directory). Se excluye explícitamente el ruido social (reddit/9gag/etc.), que hoy gana el ranking en español. Nota: definir engines explícitos desactiva los ~260 defaults de SearXNG; solo quedan los listados. Mantener `search.formats: [json, html]` (API JSON del research) y `safe_search`.
2. **Provider bilingüe** (`app/providers/search/searxng.py` + `factory.py` + `app/core/config.py`): `searxng_language: str = "es"` pasa a `searxng_languages: str = "es,en"` (lista separada por comas; cada idioma se consulta, merge dedupe por URL preservando orden: primero los hits en español, después los de inglés). La query en inglés es la que trae las fuentes oficiales/documentación.
   - `env.template` y `.env` actualizados; `.env` lo edita el parent (contiene la API key).
3. **Tests**: factory/provider multi-idioma con httpx mock (merge dedupe por URL, orden ES→EN, `language` param por request) + ajuste de tests existentes que asuman `searxng_language`.
4. **Live E2E**: repetir una búsqueda de research real (p.ej. "mejores prácticas de seguridad red doméstica") y verificar fuentes: dominios oficiales presentes (`.org`/`.edu`/wikipedia/wiki/official docs) y Reddit ausente o marginal. README nota (search config).

## Non-goals

- Traducción automática de queries (el LLM ya genera las queries; el provider consulta cada idioma sobre la misma query).
- Ranking por dominio (ResearchService ya rankea por calidad de fuente).
- Multi-provider adicional (solo searxng implementado, §21).

## Tasks

| # | Task | Status | Commit |
|---|------|--------|--------|
| 1 | `settings.yml` con engines curados (offset oficiales, sin social) | done | (paquete searxng-tuning) |
| 2 | Provider bilingüe es+en (merge dedupe por URL) + `searxng_languages` en config/factory + env.template | done | (paquete searxng-tuning) |
| 3 | Tests (multi-idioma, dedupe, orden) + ajuste tests existentes | done | (paquete searxng-tuning) |
| 4 | Live E2E (research real con fuentes oficiales, sin Reddit dominante) + README | done | (paquete searxng-tuning) |

## Acceptance criteria

- `uv run pytest` verde (`499 passed`); `ruff` limpio.
- Live: research real con fuentes oficiales; Reddit dejó de dominar.

## Evidence

- `(paquete searxng-tuning)` settings.yml curado (17 engines via `use_default_settings.engines.keep_only` — mecanismo real de reemplazo, verificado en searxng/settings_loader.py; `enabled:` es inerte en SearXNG, los toggles reales son `disabled:`; 6 engines deshabilitados upstream se forzaron a `disabled: false`) + provider bilingüe `languages` (request por idioma, merge dedupe por URL, primer idioma gana; `SearchError` igual) + `SEARXNG_LANGUAGES=es,en` (config/factory/env.template/.env) + 6 tests nuevos + adaptación de tests existentes.

### Live E2E (task 4, stack real)

- `docker compose restart searxng` → `/config` muestra **17 engines habilitados** (los 17 curados; la imagen soporta `keep_only`, sin crash).
- `POST /research/run` "¿Cuáles son las mejores prácticas de seguridad para redes domésticas en 2026?" (max_sources 8) → HTTP 201 en 69s, informe en el vault; fuentes: 2× wikipedia, 5 blogs/guias técnicas serias, **1× Reddit** (antes tier 1 dominante). Los engines generales (duckduckgo/brave/yahoo) aún pueden indexar reddit.com — el engine dedicado ya no existe; si molestara, follow-up futuro: blocklist de dominios sociales en el provider (anotado, no hecho para evitar scope creep).