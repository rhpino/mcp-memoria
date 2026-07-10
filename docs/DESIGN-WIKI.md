# DESIGN-WIKI.md — Wiki Versionada mcp-memoria (secops deploy)

> **Versión:** 0.2.0 — 2026-07-05
> **Reemplaza:** `~/memorias_mcp/DESIGN-WIKI.md` (cloudops, paths inexistentes en secops).
> **Trazabilidad:** MOP-398 + IDEA-98 (mop-mcp CANDIDATE) + auditoría secops 2026-07-05.

## Arquitectura

```
                  ┌─────────────────────┐
   write ───────► │   mm_wiki_pages     │  ◄── source of truth
                  │ (append-only DB)    │
                  └─────────┬───────────┘
                            │ reindex post-write
                            ▼
                  ┌─────────────────────┐
                  │ mm_entity_chunks    │  ◄── searchable (FULLTEXT + embeddings)
                  └─────────────────────┘

  Side-effect opcional (MCP_ARCHIVE_ON_WRITE=1):
                            │
                  ┌─────────▼───────────┐
                  │  wiki_archive/      │  ◄── artefacto, NO leído por el live
                  │  <scope>/<slug>-vN  │      (grep/git/cp para DR)
                  └─────────────────────┘
```

## Decisiones

1. **DB es source of truth.** Filesystem es backup. NO al revés.
2. **Append-only estricto.** `mm_wiki_pages` PK `(slug, version)` — nunca UPDATE/DELETE por API.
3. **Archive filename inmutable.** `<slug>-v<N>.md` → cualquier versión se escribe UNA vez → sin race, sin lock, sin atomic rename.
4. **Archive opcional via env.** `MCP_ARCHIVE_ON_WRITE=0` desactiva el write filesystem (DB-only mode).
5. **kb/ legacy se migra.** Script único (`scripts/migrate-kb-to-wiki.py`) backfilea los 45+ .md a `mm_wiki_pages`. Decisión Rodrigo 2026-07-05.
6. **`wiki_archive/` NO en `ALLOWED_DIRS`.** El chunker NO debe re-ingerir archive files.

## Path mapping

| Operación | Path |
|---|---|
| `wiki_escribir(slug, scope, ..., version=N)` | `mm_wiki_pages(slug, N, ...)` + `wiki_archive/<scope>/<slug>-v<N>.md` |
| `wiki_leer(slug, version=N)` | `mm_wiki_pages WHERE slug=? AND version=N` |
| `wiki_listar(scope)` | `SELECT slug, MAX(version) FROM mm_wiki_pages WHERE scope=?` |
| `wiki_historial(slug)` | `SELECT version, ts, author FROM mm_wiki_pages WHERE slug=? ORDER BY version DESC` |
| `wiki_export(slug)` | SELECT todas las versiones + bundle JSON (DESC por version) |

## Acceptance criteria

- [x] 5 tools expuestas con contrato `wiki_escribir / leer / historial / listar / export`.
- [x] `mm_wiki_pages` append-only con PK compuesta.
- [x] Auto-reindex post-write (chunker existente).
- [x] Auto-archive opcional (env toggle).
- [x] Sin race conditions (archive filename único por versión).
- [x] Tests e2e verdes en `tests/test_wiki_e2e.py` (37 tests wiki total).
- [x] KB legacy migration script (`scripts/migrate-kb-to-wiki.py`).
- [x] Sin regresiones en tools existentes.

## Out of scope (futuro)

- Reconciliador multi-nodo.
- Editar .md en vim y commitear como nueva versión (round-trip git-style).
- Embedding semántico dedicado por página.
- Sync a mariadb remotos.
- UI web para el wiki.
