# Feature: phase6-research — PKA Fase 6

**Project**: Personal Knowledge Agent (PKA).
**Spec source**: `Personal Knowledge Agent.md`, sections 21–22.
**Branch policy**: commits on `main`.
**Status**: done — self-hosted research with citations (2026-09-18)

## Scope (Phase 6, user-shaped 2026-09-18)

1. **Search provider (decided: SearXNG, self-hosted)**: new `searxng` service in `docker-compose.yml` (port 8080, named volume, repo-shipped `config/searxng/settings.yml` with the JSON format enabled) + `SearchProvider` abstraction (spec-style interchangeability): `base.py` defines `SearchHit{title, url, snippet, domain}` + `async search(query) -> list[SearchHit]`; `SearxngSearchProvider` queries `GET /search?q=&format=json&language=es` (httpx, configurable URL, timeout, clear `SearchError`); factory for future API providers. 503 with clear message when SearXNG is down — the app must keep working otherwise.
2. **Content extraction (decided: trafilatura, local)**: research service fetches page HTML (httpx, 15s timeout, ~0.3s delay between fetches, failure-tolerant) and extracts the main text with `trafilatura.extract` (max ~20k chars). Snippets are the fallback when extraction fails.
3. **ResearchService (spec §21 flow)** — `research.run(question, *, project_id=None, title=None)`:
   1. `interpret`: LLM turns the question into 2–4 Spanish search queries.
   2. search each query via SearXNG; dedupe by URL across queries.
   3. `rank`: heuristic source-quality tiers (official docs domains, github.com, mainstream tech sites > blogs > forums/community), keep top `research_max_sources` (default 6).
   4. `extract`: fetch + trafilatura per source (failure → snippet fallback).
   5. `synthesize`: LLM writes a **Spanish markdown report** with structure `# Objetivo`, `# Resumen`, `# Hallazgos` (numbered source refs `[n]`), `# Contradicciones detectadas`, `# Conclusión`, `# Fuentes` (numbered list with URLs + retrieved_at). Instructed to cite `[n]` for every claim and flag contradictions between sources — never invent.
   6. `persist`: write the report to the vault (project folder or inbox) + immediate ingest (same semantics as tutorials: file_path/file_mtime so later sync is a no-op).
4. **API**: `POST /research/run {question, project_id?, title?}` → `ResearchRead{document_id, title, file_path, report, sources[{title, url, domain, snippet}]}` — 201; 422 empty question; 502 LLM errors; 503/502 when search/extraction infra fails. Synchronous for v1 (a run takes ~1–3 min; async job queue is a later enhancement).
5. **Knowledge flow (spec §22)**: the report lands in the vault as an editable document (user-owned artifact); turning findings into **facts** stays manual through the existing `POST /memories/extract`. No automatic memory pollution.

## Decisions (user, 2026-09-18)

- Web search: **SearXNG self-hosted** (Docker) — JSON API, no third-party keys/costs.
- Content extraction: **trafilatura local** (no external processing service).
- Report language: Spanish (consistent with tutorials).

## Design notes

- New dependencies: `trafilatura` (only new Python dep; SearXNG is reached over HTTP).
- New config: `SEARXNG_URL` (default `http://localhost:8080`), `SEARXNG_LANGUAGE` (default `es`), `RESEARCH_MAX_SOURCES` (default 6) → Settings + env.template + contract test sync.
- Sync execution: shipped with a generous client timeout; infra failures surface as structured errors, never crashes.

## Tasks

| # | Task | Status | Commit |
|---|------|--------|--------|
| 1 | docker-compose `searxng` + `config/searxng/settings.yml` (JSON format) | done | 3aea837 |
| 2 | Config: `searxng_url`/`searxng_language`/`research_max_sources` + env.template + contract sync | done | 3aea837 |
| 3 | `SearchProvider` abstraction + `SearxngSearchProvider` + factory + tests | done | 3aea837 |
| 4 | Content extraction: httpx + trafilatura (offline-testable, snippet fallback) + tests | done | 3aea837 |
| 5 | `ResearchService`: interpret → search → dedupe → rank → extract → synthesize → persist | in_progress | |
| 6 | `POST /research/run` + schemas + wiring | in_progress | |
| 7 | Tests: provider parse, extract, service flow (fakes), route, persist | in_progress | |
| 8 | Live E2E (real SearXNG + trafilatura + LLM) + README | done | 96bf048 + docs |

## Acceptance criteria

- `uv run pytest` green; `ruff` clean; `docker compose config` valid with the new service.
- `POST /research/run` on the real stack produces a Spanish report with numbered sources and URLs, saved to the vault and indexed; contradictions among sources are called out; with SearXNG down the endpoint errors cleanly without breaking other API calls.

## Evidence

- `3aea837` feat: SearXNG search provider and trafilatura extraction (tasks 1–4).
- `f2ab2c7` feat: research agent orchestration and /research/run (tasks 5–7).
- `96bf048` fix: valid SearXNG settings (use_default_settings + secret_key) — the first settings.yml crashed the container; verified by loading the exact `init_settings` path in the image before applying.

### Live verification (task 8, real stack)

- SearXNG container up (HTTP 200; only optional engines ahmia/torch fail to register).
- `POST /research/run` "Cómo configurar OpenWrt como access point" (project Home Lab) → 201; report `home-lab/como-configurar-openwrt-como-access-point-en-una-red-domest.md` in the vault; 5 real sources (Reddit threads) with domains/snippets; all six §21 headers (Objetivo/Resumen/Hallazgos/Contradicciones detectadas/Conclusión/Fuentes).
- Nota de tuning: la búsqueda en español devolvió sobre todo hilos de Reddit (tier 1 del ranking); para documentos oficiales convendría consultas en inglés o más engines — follow-up.