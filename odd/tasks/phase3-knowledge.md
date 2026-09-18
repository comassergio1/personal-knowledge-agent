# Feature: phase3-knowledge — PKA Fase 3

**Project**: Personal Knowledge Agent (PKA).
**Spec source**: `Personal Knowledge Agent.md`, sections 4, 9, 14–17.
**Branch policy**: commits on `main`.
**Status**: done — file-first vault, projects, PDF, sync (2026-09-18)

## Scope (Phase 3, user-shaped 2026-09-18)

**File-first knowledge vault (Obsidian-compatible)**:

1. **Vault storage**: ingests are written as **markdown files on disk** in a PKA-managed vault (`VAULT_PATH`, default `data/vault`, gitignored; openable with Obsidian's "Open folder as vault"). Folders per project, safe kebab-case slug filenames.
2. **Projects** (spec §17): `Project` model + CRUD routes; documents already carry `project_id`; retrieval filters by project via vector payload metadata; vault subfolder per project.
3. **PDF ingestion**: uploads are copied into the vault as `.pdf` (openable from Obsidian) and their text is extracted (`pypdf`) for chunking/RAG.
4. **Obsidian edits → memory** (user caveat): the file is the source of truth. `GET /documents/{id}` returns file content + a `stale` flag (file mtime newer than the DB row). `POST /documents/{id}/resync` re-chunks/re-embeds one edited document; `POST /vault/sync` scans the whole vault and created/updates/deletes rows+vectors to match the files on disk (manual sync, user decision).
5. **MD → PDF is the user's job**: the system never exports PDFs; the user creates their own PDFs from the markdown as they prefer.

## Decisions (user, 2026-09-18)

- Vault location: **PKA-owned `data/vault`** (env-configurable), not the user's real Obsidian vault.
- Sync model: **manual** — stale flags + `POST /vault/sync`; no filesystem watcher.

## Design notes

- Source of truth = file on disk; SQLite keeps metadata + chunks; Qdrant keeps vectors. `Document.file_path` (relative to vault) + `file_mtime` (last synced mtime) drive staleness.
- Deleting a project removes its documents (rows + vector points + vault files) — destructive by design, documented.
- Vector point payload gains `project_id`; `QdrantVectorStore.search` gains a `project_id` filter (FieldCondition).
- New dependency: `pypdf` (PDF text extraction) — the only new dep this phase.

## Tasks

| # | Task | Status | Commit |
|---|------|--------|--------|
| 1 | Config `vault_path` + `VAULT_PATH` in env.template (+ contract test sync) | done | c07f064 |
| 2 | `VaultService`: paths, safe slugs, write/read/delete/scan + folder-per-project | done | c07f064 |
| 3 | `Project` model + `Document.file_path`/`file_mtime` + migration | done | c07f064 |
| 4 | ProjectRepository + `/projects` routes + project filters (documents list, chat, vector payload) | done | c07f064 |
| 5 | Ingestion file-first: write md/txt to vault; PDF copy + text extraction (pypdf) | in_progress | |
| 6 | `GET /documents/{id}` file content + stale flag; `POST /documents/{id}/resync`; `POST /vault/sync` | in_progress | |
| 7 | Tests: vault, projects, pdf, resync/sync, filters | in_progress | |
| 8 | Live E2E (create → edit file → sync → chat reflects edit; PDF chat) + README | done | cd07640 + docs |

## Acceptance criteria

- `uv run pytest` green; `ruff` clean.
- Uploading a markdown creates a real file under `data/vault/<project>/...md`; editing it (Obsidian-style) and calling `POST /vault/sync` changes the indexed content; `GET /documents` shows `stale: true` before sync.
- PDF upload stores the file in the vault and answers grounded chat from its text.
- Chat with `project_id` only retrieves that project's chunks.

## Evidence

- `c07f064` feat: Obsidian-compatible vault base, projects, and project filters (tasks 1–4).
- `cd07640` feat: file-first ingestion and Obsidian-style vault sync (tasks 5–7).
- `(fix)` file-DB regression tests write the vault into tmp_path (real-vault pollution found in test run).

### Live verification (task 8, real stack)

- Project "Home Lab" → upload `mikrotik.md` → real file at `data/vault/home-lab/mikrotik-vlans.md`.
- Edit file (append "VLAN 60 para cámaras"): `GET /documents/{id}` → `stale: True`; `POST /resync` → `stale: False`, content includes the edit; chat answers "Se utiliza la **VLAN 60** para las cámaras" — the Obsidian-edit → memory flow works.
- PDF (real, via cupsfilter): upload → text extracted ("VLAN 70", port ether5, tag) stored in vault as `guests-vlan70.pdf`; chat cites "puerto ether5 con tag VLAN 70 [1]".
- Project filter: chat with `project_id` scopes retrieval.