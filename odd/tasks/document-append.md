# Feature: document-append — editar documentos del vault por comando

**Project**: My NotebookLM — Personal Learning & Knowledge System (`personal-knowledge-agent`).
**Driver**: user workflow 2026-09-18 — "armame un documento tutorial de X… y en otra sesión, en el documento de X agregá esta sección [pego texto]". The docs are the source of truth (vault files); this closes the edit-by-command loop that resync left open.

**Branch policy**: commits on `main`.
**Status**: done — edit-by-command loop closed (2026-09-18).

## Scope

1. `PATCH /documents/{id}/append` body `{text: str (min 1), section: str | None}`:
   - reads the document's vault file (missing `file_path` or a PDF mime → 409 with a clear message: append only applies to file-backed text/markdown documents);
   - content = existing file content + (`## {section}\n\n{text}\n` when a section is given, else `\n{text}\n`); writes the file back (VaultService), records the file mtime;
   - re-indexes the document: replace chunk rows, re-embed, replace vector points, bump `updated_at` (reusing the resync internals — refactor a shared `_reindex` path so resync and append stay consistent);
   - returns `DocumentDetail` (updated content, `stale: false`).
   - 404 when the document is missing; 422 when text is empty (schema).
2. Schema: `DocumentAppendRequest`.
3. Wire in `app/api/routes/documents.py` + `IngestionService.append_content(...)`.

## Design notes

- Same semantics as the manual Obsidian flow: edit file → resync; here the system edits the file on your behalf and re-indexes immediately.
- No new dependencies.

## Tasks

| # | Task | Status | Commit |
|---|------|--------|--------|
| 1 | `IngestionService.append_content` (read file → compose → write → re-index via shared helper) | pending | |
| 2 | `PATCH /documents/{id}/append` + schema + 404/409/422 | pending | |
| 3 | Tests: unit (compose/re-index/file-less/409) + integration (append → file + detail + retrieval) | pending | |
| 4 | Live E2E — the two-session workflow: create tutorial doc, then append a pasted section, chat answers it + README | done | a37dd5d + docs |

## Acceptance criteria

- `uv run pytest` green; `ruff` clean.
- Live: a document created earlier gets a section appended in a later call; the vault file contains the new section; the chat answers from the appended content.

## Evidence

- `a37dd5d` feat: append content to vault documents by command (tasks 1–3).

### Live E2E (task 4, real server :8000 — the two-session workflow)

- Session A: `POST /tutorials/generate` "Hacer un backup seguro y automatizado del servidor" (title "Tutorial Backup Servidor", mode do) → doc `80fb57fc…`, file `inbox/tutorial-backup-servidor.md`.
- Session B: `PATCH /documents/80fb57fc…/append {section: "Presupuesto de discos", text: "…140 USD… 280 USD…"}` → 200, stale False; the vault file now contains `## Presupuesto de discos` (verified via tail).
- Chat (OpenAI surface): “¿cuánto estimé para discos…?” → answered from the appended section (140 USD/útil estrategia dedicado + off-site). The user's described workflow works end to end.