# CHANGELOG — mcp-memoria

Formato: append-only, últimas entradas primero.

---

## [0.2.0] — 2026-07-05 — MOP-398 (Wiki Versionada, CERRADO)

### Added
- 6 tools wiki: `wiki_help`, `wiki_listar`, `wiki_leer`, `wiki_escribir`, `wiki_historial`, `wiki_export`.
- Tabla `mm_wiki_pages` con PK compuesta (slug, version), append-only, source of truth.
- Auto-archive filesystem opcional (env `MCP_ARCHIVE_ON_WRITE=1`, default ON):
  `<WORKSPACE>/wiki_archive/<scope>/<slug>-v<N>.md`. Filename inmutable por versión → cero race.
- Path helpers `wiki_archive_path(slug, scope, version)` y `wiki_archive_dir(scope)` con validación regex `^[a-zA-Z0-9][a-zA-Z0-9_-]{0,198}$` (acepta MAYUSC para kb/ legacy).
- Módulo `wiki_io.py` con `parse_frontmatter` / `render_with_frontmatter` (YAML via pyyaml).
- Reindex automático post-write vía `chunker.chunk_and_index()`.
- Módulo `tools/wiki.py` con sync + async wrappers.
- **Shared module `/opt/mcps/shared/mcp_test_isolation.py`** con `force_test_db()` + `make_isolate_fixture()` para tests aislados cross-MCP.

### Changed
- `server.py` registra 6 tools nuevos (16 → 22 totales).
- **Tool descriptions mejoradas**: cada wiki_* tool apunta a `wiki_help()` como entry point. Cero adivinanzas para agentes nuevos.
- `tests/conftest.py` (mcp-memoria) refactorizado para usar el patrón shared.

### Arquitectura
- **DB es live**: `wiki_listar`, `wiki_leer`, `wiki_historial`, `wiki_export` leen SOLO de `mm_wiki_pages`.
- **Filesystem es backup**: el archive NO es leído por el live. Es write-only artefact.
- `wiki_archive/` NO está en `paths.ALLOWED_DIRS` → el chunker no re-ingiere archivos archive.
- **`wiki_help` como entry point** — primer tool a llamar cuando no se conoce el sistema.

### Tests
- **84 pass, 1 skipped** totales (47 nuevos wiki/shared + cross-tracking).
- 0 regresiones en tests existentes.
- **Test isolation fixed**: prod DB intacta post-tests (55 filas constantes).
- Fleet audit: mcp-monitoreo ya tenía el patrón correcto; mcp-mop tiene riesgo latente documentado.

### Bug fixes durante MOP-398
1. **`wiki_escribir` async wrapper race condition**: doble reindex entre `loop.create_task` y `await chunker.chunk_and_index`. Fix: async wrapper hace TODO inline, sin fire-and-forget.
2. **Test suite contaminaba prod DB**: pool PyMySQL module-level con conexiones cacheadas. Fix: `tests/conftest.py` setea `MCP_DB_NAME=mcp_memoria_test` ANTES de imports + autouse fixture que cierra el pool entre tests.

### Migration aplicada (2026-07-05)
- Script `scripts/migrate-kb-to-wiki.py` corrido con `--apply`.
- Resultado: `migrated=43 skipped=0 lowercased=0 failed=0 root=3`.
- 43 .md del kb/ legacy en `mm_wiki_pages (slug, version=1, author='legacy-migration')`.
- Distribución: concepts=1, designs=7, lessons=4, papers=30, reports=1.
- Casing original preservado (CHG-*, MOP-*, RCA-*, INDEPENDENCIA, INVESTIGACION-* etc.).
- Idempotente: 2da corrida reporta `skipped=43`.

### Wiki content MOP-398 (11 pages, designados para seguimiento cruzado)
1. `mop-398-wiki-research` — overview
2. `mop-398-architecture-decision` — DB-only + auto-archive rationale
3. `mop-398-acceptance-criteria` — 12 ACs con status
4. `mop-398-migration-runbook` — cómo migrar kb/ legacy
5. `mop-398-known-issues` (v2) — riesgos R1-R10 + R10-bis (mcp-mop latente)
6. `mop-398-future-work` — backlog out-of-scope
7. `mop-398-incident-test-isolation` — diagnosis Gemini + fix
8. `mop-398-fleet-audit-test-isolation` — audit fleet-wide
9. `mop-398-shared-test-isolation-module` — shared module docs
10. `mop-398-wiki-help-entry-point` — wiki_help tool docs

### Decisiones operacionales (Rodrigo 2026-07-05)
| # | Decisión | Resolución |
|---|---|---|
| 1 | Timing del restart | Flexible (Claude + geo, no producción) |
| 2 | ¿Migrar kb/ legacy? | SÍ |
| 3 | Toggle `MCP_ARCHIVE_ON_WRITE` | ON (default) |

### Estado de cierre
- ✅ Service `mcp-memoria` corriendo con 22 tools (16 + 6 nuevos).
- ✅ Health endpoint OK, DB conectada.
- ✅ Tests verdes en isolation (MCP_DB_NAME forzado a test).
- ✅ Shared module extraído y documentado.
- ✅ Cross-tracking wiki network activo (11 pages con `related:` cross-refs).
- ✅ Fleet audit completo con riesgo latente de mcp-mop documentado.
- MOP-398: **DISCOVERY → PLAN → APROBADO → EN_CURSO → IMPLEMENTADO → COMPLETADO** (CERRADO).

## [Unreleased] — 2026-07-05 — MOP-398 (Wiki Versionada, en curso, original)

### Added
- 5 tools nuevos: `wiki_listar`, `wiki_leer`, `wiki_escribir`, `wiki_historial`, `wiki_export`.
- Tabla `mm_wiki_pages` con PK compuesta (slug, version), append-only, source of truth.
- Auto-archive filesystem opcional (env `MCP_ARCHIVE_ON_WRITE=1`, default ON):
  `<WORKSPACE>/wiki_archive/<scope>/<slug>-v<N>.md`. Filename inmutable por versión → cero race.
- Path helpers `wiki_archive_path(slug, scope, version)` y `wiki_archive_dir(scope)` con validación regex.
- Módulo `wiki_io.py` con `parse_frontmatter` / `render_with_frontmatter` (YAML).
- Reindex automático post-write vía `chunker.chunk_and_index()`.
- Módulo `tools/wiki.py` con sync + async wrappers (5 tools + 5 sync helpers).

### Changed
- `server.py` registra 5 tools nuevos (16 → 21 totales).

### Arquitectura
- **DB es live**: `wiki_listar`, `wiki_leer`, `wiki_historial`, `wiki_export` leen SOLO de `mm_wiki_pages`.
- **Filesystem es backup**: el archive NO es leído por el live. Es write-only artefact.
- `wiki_archive/` NO está en `paths.ALLOWED_DIRS` → el chunker no re-ingiere archivos archive.

### Tests
- 37 tests wiki agregados (db + io + archive + tools + e2e). Sin regresiones en tests existentes (74 pass totales).

### Bug fix durante smoke test
- `wiki_escribir` async wrapper hacía doble reindex (race entre `loop.create_task` y `await chunker.chunk_and_index`). Fix: async wrapper ahora hace TODO inline (DB + archive + reindex awaited), eliminando el fire-and-forget.

### Migration aplicada (2026-07-05)
- Script `scripts/migrate-kb-to-wiki.py` corrido con `--apply`.
- Resultado: `migrated=43 skipped=0 lowercased=0 failed=0 root=3`.
- 43 .md del kb/ legacy en `mm_wiki_pages (slug, version=1, author='legacy-migration')`.
- Distribución: concepts=1, designs=7, lessons=4, papers=30, reports=1.
- Casing original preservado (CHG-*, MOP-*, RCA-*, INDEPENDENCIA, INVESTIGACION-* etc.).

### Smoke test E2E verde
- `wiki_escribir smoke-test-page` → v1 created, archived=True, chunks=1, reindex 2s.
- `wiki_leer` → v1 body=76 chars.
- `kag_buscar "smoketest"` → 1 result, cosine=0.450 (semantic match).
- `wiki_listar` → muestra migrated + smoke page.
- Cleanup post-test (delete rows + archive file).
- Service `mcp-memoria` reiniciado, health endpoint OK.

### Estado DB prod
- `mcp_memoria.mm_wiki_pages`: 43 filas (author='legacy-migration').

## [Unreleased] — 2026-07-02

### Added (Stage 0)
- `/opt/mcps/memoria/RESEARCH.md` — comparativa de vector stores + embeddings, decisión locked: sqlite-vec (superseded) → MariaDB local + paraphrase-multilingual-MiniLM-L12-v2.

### Changed (v3 rediseño post-auditoría omni-mcp)
- Stack: Python full + MariaDB local + schema `mcp_memoria` prefijo `mm_` (D1).
- 13 tools kb-specific (no 9).
- Documentos: PLAN.md reescrito (319 líneas), RESEARCH.md marcado SUPERSEDED, ALIGNMENT.md actualizado, IDEAS.md creado (7 ideas con confianza), goal.md reemplazado.

### Added (Stage 1 — Foundation)
- `pyproject.toml` con deps: pyproject, fastapi, uvicorn, fastmcp, fastembed, sqlite-vec, numpy, mysql-connector-python, pymysql, python-frontmatter.
- `.venv/` con Python 3.14 + PyMySQL 1.2.0 + mysql-connector 9.7.0 + pytest 9.1.1.
- MariaDB DB `mcp_memoria` + `mcp_memoria_test` creadas.
- User `mcp_memoria@localhost` con permisos sobre ambas.
- `src/memoria_mcp/db.py` (336 LOC) — pool local PyMySQL + 6 tablas `mm_*` (entities, relations, entity_chunks, search_feedback, conflict_queue, search_log).
- `src/memoria_mcp/chunker.py` — port conceptual de omni-mcp `autoChunkAndIndex` (heading split, entity match, embed insert).
- `src/memoria_mcp/embed.py` — fastembed wrapper async, modelo `paraphrase-multilingual-MiniLM-L12-v2` (384 dim).
- `src/memoria_mcp/instance.py` + `paths.py` + `parsers.py` + `observability.py` (réplicas del patrón mop-mcp).

### Added (Stage 2 — Read tools + search.py)
- `src/memoria_mcp/search.py` (~270 LOC) — cosine + keyword_boost + RRF + hybrid_search.
- `src/memoria_mcp/tools/decisions.py` — decision_list + decision_get.
- `src/memoria_mcp/tools/lessons.py` — lesson_list + lesson_get.
- `src/memoria_mcp/tools/adr.py` — adr_get.
- `src/memoria_mcp/tools/project.py` — project_brief.
- `src/memoria_mcp/tools/links.py` — cross_links, link_add, link_list.

### Added (Stage 3 — Grafo)
- `src/memoria_mcp/grafo.py` — BFS recursivo SQL CTE, max depth 3, shortest_path, entity_stats.
- `src/memoria_mcp/tools/grafo.py` — entity_añadir + grafo_vecinos + entity_stats + shortest_path.

### Added (Stage 4 — KAG + Bibliotecario)
- `src/memoria_mcp/bibliotecario.py` (~140 LOC) — port conceptual de omni-mcp bibliotecario.cjs (LLM merge MiniMax → Gemini fallback, degraded mode).
- `src/memoria_mcp/tools/kag.py` — kag_buscar + kag_evaluar.
- `src/memoria_mcp/tools/bibliotecario.py` — bibliotecario_run + conflict_list + conflict_resolve + bibliotecario_status.

### Added (Stage 5 — Auth + transport)
- `src/memoria_mcp/auth.py` (~155 LOC) — Tailscale WhoIs + Bearer token auth (100.64.0.0/10 + 10.255.255.0/24).
- `src/memoria_mcp/health.py` — /health (con db.health_check) + /metrics (Prometheus text).
- `src/memoria_mcp/server.py` (~225 LOC) — FastAPI app + 13 tools FastMCP, lazy init thread-safe.

### Added (Stage 6 — Deploy)
- `/etc/systemd/system/mcp-memoria.service` — unit con hardening (NoNewPrivileges, ProtectSystem, etc.).
- `/etc/systemd/system/mcp-memoria-backup.timer` + `.service` — daily 03:00 UTC.
- `/etc/flow-gateway/tokens.env` — `FLOW_TOKEN_GEO`, `FLOW_TOKEN_CLAUDE_CODE`, `FLOW_TOKEN_CODEX` (random hex 32, 600 root:mcps).
- UFW rules: `9092/tcp ALLOW FROM 100.64.0.0/10` + `10.255.255.0/24`.
- `/var/lib/mcp-memoria/` (2775 geo:mcps) — state directory.
- `/opt/mcps/memoria/scripts/backup-memoria.sh` — daily mariadb-dump + tar.gz + rsync a geo (100.112.255.59) + tars (100.77.242.85).
- `/opt/mcps/memoria/scripts/smoke-memoria.sh` — E2E smoke test (health/metrics/bearer).

### Tests
- `tests/test_no_personal_leak.py` — 10 tests, gate crítico. **0 leaks en keywords personales.**
- `tests/test_search.py` — 6 tests (cosine, keyword, RRF, feedback).
- `tests/test_grafo.py` — 8 tests (BFS, filters, stats).
- `tests/test_bibliotecario.py` — 5 tests (degraded mode, conflicts, manual resolve).
- `tests/test_auth_health.py` — 7 pass + 1 skip (FastMCP TestClient incompat).
- **Total: 36/36 passing + 1 skip.**

### Notas operacionales
- `SET GLOBAL read_only=OFF` requirió ejecución manual (MariaDB estaba en read-only por default).
- Wazuh loggea cada restart — avisar antes de futuros deploys.
- SSH key (no password) requerido para backup remoto funcional — TODO Stage 6 task `backup ssh key setup`.

---

## Tipado de versiones

- **Versión actual:** 0.1.0
- **Próxima estable:** 0.2.0 cuando se valide con kb/ real de vps-geo-noc.

### Added (post-deploy 2026-07-02 — kb/ real)
- Pulled kb/ real desde `cloudops@vps-geo-noc:/.openclaw/workspace/kb/` (SSH ya tenía acceso directo). 46 archivos, 736 KB.
- `paths.py` actualizado con `ALLOWED_DIRS` para `concepts/designs/lessons/papers/reports/` + root `DESIGNS.md` + `INDEX.md`. Compatible con la estructura real del kb/.
- `chunker.py` extendido con `_add_by_paragraphs()` y `_add_by_sentences()` para files grandes sin headings (40K+ chars). Ahora usa MAX_CHUNK_CHARS=1500 + sentence split + 100-char overlap.
- `scripts/index-real.py` — script para indexar el kb/ real.
- `scripts/load-test.py` — concurrent load test con httpx.
- `scripts/test-tools-corpus.sh` — 10 tests E2E sobre corpus indexado.

### Performance re-benchmark (kb/ real 1975 chunks)
- Chunk index time: 5.6s warmup / 30-80ms chunk posterior.
- Query latency: 14.7ms avg (vs 5.7ms con seed).
- Load test: ~50 req/s con 5 concurrent. CPU-bound single-thread (cuello de botella = embedding).
- Top cosine scores validados: 0.85/0.84/0.82 para queries semánticas en español.

### Known limitations
- Wazuh HIDS activo loggea deploys futuros — avisar antes de redeploy.
- fastembed 0.8 cambió pooling (mean vs CLS). Pin a fastembed==0.5.1 si se requiere paridad exacta.
- SSH key para backup automatizado **requiere acción de Rodrigo** en vps-geo-noc.
- Bibliotecario en degraded mode (sin MiniMax key).
