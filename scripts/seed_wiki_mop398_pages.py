"""Seed cross-referenced wiki pages for MOP-398 follow-up tracking.

Creates 5 pages scoped to designs/reports, each linking via `related` frontmatter
to the overview + each other.
"""
import asyncio

from memoria_mcp.tools.wiki import wiki_escribir, wiki_listar

OVERVIEW = "mop-398-wiki-research"
AUTHOR = "claude:minimax-m3@secops:v1"

PAGES = [
    {
        "slug": "mop-398-architecture-decision",
        "scope": "designs",
        "frontmatter": {
            "title": "MOP-398 — Architecture Decision Record",
            "related": ["mop-398-wiki-research", "mop-398-known-issues"],
        },
        "body": """# MOP-398 — Architecture Decision Record

> Página cruzada via wiki_escribir. Source of truth: `mm_wiki_pages`.
> Related: [[mop-398-wiki-research]] [[mop-398-known-issues]]

## Decisión principal: DB-only + auto-archive

### Contexto
IDEA-98 v1 proponía dual-write (DB + filesystem) con WikiLock + atomic tmp+rename
+ rollback semantics DB-first-then-fs.

### Decisión tomada
**DB es source of truth, filesystem es backup artefact (write-only).**
**Filename único por versión (`<slug>-v<N>.md`) → sin race, sin lock.**

### Alternativas consideradas
- **Dual-write con WikiLock** (descartado): añade complejidad innecesaria porque
  el live read NO depende del filesystem. Chunker ya ingesta al startup.
- **Flat-file como primary** (descartado): rompe queryability y atomicidad.
- **Embeddings dedicados por página** (fuera de scope): se reuse el chunker
  existente que ya embebe por chunk.

### Consecuencias

| Pro | Con |
|---|---|
| Sin race conditions (filename único por versión) | Archivo `.md` no se pisa (cada versión vive aparte) |
| Sin lock files / fcntl | Si se quiere "latest" hay que mirar DB |
| Código ~50% menos | Necesidad de correr `index-real.py` separado para KB legacy |
| Rollback trivial (drop tabla) | El "filesystem backup" requiere reparsear |

### Decisiones subordinadas

1. **Auto-archive toggle**: `MCP_ARCHIVE_ON_WRITE` env (default ON). Permite DB-only
   sin tocar filesystem si el espacio es problema.
2. **Regex de slug `^[a-zA-Z0-9][a-zA-Z0-9_-]{0,198}$`**: acepta MAYUSC para no
   romper los 7 archivos del KB legacy con casing preserved (CHG-*, MOP-*, RCA-*).
3. **Idempotency en migration**: keyed por `(slug, version=1)`. Re-correr = skipped.
4. **Casing preservation en migration**: lowercase rompería `mm_entity_chunks.page_slug`.

## Verificación

- 44 tests pasan (37 wiki + 6 migration + 1 preexistente).
- Smoke E2E: write → read → kag_buscar (cosine 0.45) ✓.
- Migration: 43 .md legacy → `mm_wiki_pages`, idempotente.

## Referencias cruzadas

- Overview: ver [[mop-398-wiki-research]]
- Riesgos abiertos: ver [[mop-398-known-issues]]
- Backlog: ver [[mop-398-future-work]]
""",
    },
    {
        "slug": "mop-398-acceptance-criteria",
        "scope": "designs",
        "frontmatter": {
            "title": "MOP-398 — Acceptance Criteria checklist",
            "related": ["mop-398-wiki-research"],
        },
        "body": """# MOP-398 — Acceptance Criteria checklist

> Estado de cada criterion del IDEA-98 refinado + AC operacionales.
> Related: [[mop-398-wiki-research]]

## AC originales (IDEA-98)

| # | Criterion | Status | Evidence |
|---|---|---|---|
| 1 | 5 tools: wiki_escribir/leer/historial/listar/export | ✅ DONE | `src/memoria_mcp/tools/wiki.py` + `tests/test_wiki_tools.py` (18 tests) |
| 2 | `mm_wiki_pages` PK compuesta (slug, version) append-only | ✅ DONE | `tests/test_wiki_db.py::test_wiki_pages_table_created` |
| 3 | Auto-chunk post-write (≥50 chars) | ✅ DONE | `chunker.chunk_and_index()` reusado (tests muestran chunks_indexed) |
| 4 | Búsqueda full-text funcionando | ✅ DONE | `mm_entity_chunks` con FULLTEXT pre-existente |
| 5 | E2E test verde | ✅ DONE | `tests/test_wiki_e2e.py` (2 tests) |
| 6 | DESIGN-WIKI.md actualizado | ✅ DONE | `docs/DESIGN-WIKI.md` (reemplaza el de cloudops) |

## AC nuevos (decisión DB-only + auto-archive)

| # | Criterion | Status | Evidence |
|---|---|---|---|
| 7 | Auto-archive con env toggle | ✅ DONE | `MCP_ARCHIVE_ON_WRITE=0` testeado en `test_wiki_escribir_archive_disabled` |
| 8 | Sin race conditions (filename único por versión) | ✅ DONE | Filename `<slug>-v<N>.md` collision-free |
| 9 | Sin WikiLock / atomic rename / rollback semantics | ✅ DONE | Eliminados del plan v2 (Tasks redujeron de 10 → 9) |
| 10 | Migración kb/ legacy → mm_wiki_pages | ✅ DONE | 43 .md migrados, idempotente |
| 11 | Sin regresiones en tools existentes | ✅ DONE | 74 tests originales + 44 nuevos = 118 (algunos shared) |
| 12 | Service mcp-memoria reiniciado con 21 tools | ✅ DONE | `health` OK, `mcp.list_tools()` = 21 |

## AC operacionales (decisiones Rodrigo 2026-07-05)

| # | Decisión | Resolución |
|---|---|---|
| OP-1 | Restart flexible | ✅ Aceptado (solo Claude + geo) |
| OP-2 | Migrar kb/ legacy | ✅ DONE (43 páginas) |
| OP-3 | MCP_ARCHIVE_ON_WRITE default ON | ✅ DONE (default = "1") |

## AC diferidos (out of scope MOP-398)

Ver [[mop-398-future-work]].

## Cómo verificar

```bash
# DB tiene 43+ filas en mm_wiki_pages
mariadb mcp_memoria -e 'SELECT COUNT(*) FROM mm_wiki_pages;'
# >= 44 (43 migración + 1 overview page)

# Tools registrados = 21
PYTHONPATH=/opt/mcps/memoria/src python -c "
import asyncio
from memoria_mcp import server
async def main():
    tools = await server.mcp.list_tools()
    print(len(tools), 'tools total')
asyncio.run(main())"

# Tests pasan
.venv/bin/pytest tests/ -q
```
""",
    },
    {
        "slug": "mop-398-migration-runbook",
        "scope": "designs",
        "frontmatter": {
            "title": "MOP-398 — Migration Runbook (kb/ legacy → mm_wiki_pages)",
            "related": ["mop-398-wiki-research", "mop-398-architecture-decision"],
        },
        "body": """# MOP-398 — Migration Runbook

> Cómo correr la migración de kb/ legacy a `mm_wiki_pages`.
> Related: [[mop-398-wiki-research]] [[mop-398-architecture-decision]]

## Script

`/opt/mcps/memoria/scripts/migrate-kb-to-wiki.py`

## Prerequisitos

- DB `mcp_memoria` con `mm_wiki_pages` creada (Task 1 del MOP-398 — idempotente).
- Credenciales MCP_DB_USER/PASS/HOST en env.
- WORKSPACE_ROOT apuntando al kb/.
- pyyaml disponible en venv.

## Dry-run

```bash
set -a; source /etc/mcp-memoria/db.env; source /opt/mcps/memoria/.env; set +a
/opt/mcps/memoria/.venv/bin/python /opt/mcps/memoria/scripts/migrate-kb-to-wiki.py --dry-run
```

Output esperado:
```
[DRY-RUN] summary: migrated=43 skipped=0 lowercased=0 failed=0 root=3
```

## Apply

```bash
/opt/mcps/memoria/.venv/bin/python /opt/mcps/memoria/scripts/migrate-kb-to-wiki.py --apply
```

Output esperado:
```
summary: migrated=43 skipped=0 lowercased=0 failed=0 root=3
```

## Idempotencia

Re-correr `--apply` después de una migración exitosa:
```
summary: migrated=0 skipped=43 lowercased=0 failed=0 root=3
```

Si esto pasa, la migración es estable. Si reporta `migrated=N` con N>0, hay duplicados.

## Edge cases manejados

| Caso | Comportamiento |
|---|---|
| Slug UPPERCASE (INDEPENDENCIA.md) | **Preserva casing**, no lowercase |
| Archivo en root (DESIGNS.md) | Skippeado (no en scope dir) |
| Subdir no permitido (lessons/private/) | Skippeado (no es scope válido) |
| Archivo con frontmatter YAML | Frontmatter parseado y guardado como JSON |
| Archivo con YAML malformado | Frontmatter = `{}`, body = texto crudo |
| `author` en archivo legacy | Forzado a "legacy-migration" |
| Version | Siempre = 1 (migración crea la primera versión) |

## Verificación post-migration

```bash
# Conteo por scope
mariadb mcp_memoria -e 'SELECT scope, COUNT(*) FROM mm_wiki_pages WHERE author = "legacy-migration" GROUP BY scope;'

# Esperado (2026-07-05 baseline):
# concepts=1, designs=7, lessons=4, papers=30, reports=1

# Sample row
mariadb mcp_memoria -e 'SELECT slug, version, author, LENGTH(body) AS bytes FROM mm_wiki_pages WHERE slug = "INDEPENDENCIA";'
# Esperado: slug=INDEPENDENCIA version=1 author=legacy-migration bytes=~1400
```

## Re-indexar para que `kag_buscar` vea las páginas migradas

La migración NO corre el chunker. Para que `kag_buscar` encuentre el contenido:

```bash
/opt/mcps/memoria/.venv/bin/python /opt/mcps/memoria/scripts/index-real.py
```

Esto llena `mm_entity_chunks` con embeddings. Sin esto, las páginas existen en DB
pero no son buscables semánticamente.

> Pendiente: correr después de la migración inicial. Ver [[mop-398-future-work]].

## Rollback

```bash
# Borrar filas migradas (preserva tablas nuevas + filas nuevas)
mariadb mcp_memoria -e 'DELETE FROM mm_wiki_pages WHERE author = "legacy-migration";'

# Drop archive filesystem si quedó algo (no debería, migration no escribe archive)
ls /opt/mcp-memoria/snapshot/kb/wiki_archive/
# Si hay archivos de migración (no debería), el script no los crea. No-op.
```

## Logs

`journalctl -u mcp-memoria -n 100` muestra output estructurado del script
(`migrate-kb` logger).

## Próximos pasos

- Correr `index-real.py` post-migración. Ver [[mop-398-future-work]].
""",
    },
    {
        "slug": "mop-398-known-issues",
        "scope": "designs",
        "frontmatter": {
            "title": "MOP-398 — Known Issues & Risks Register",
            "related": ["mop-398-wiki-research", "mop-398-future-work", "mop-398-architecture-decision"],
        },
        "body": """# MOP-398 — Known Issues & Risks Register

> Estado de los 10 riesgos identificados en la sección Discovery del MOP.
> Related: [[mop-398-wiki-research]] [[mop-398-future-work]] [[mop-398-architecture-decision]]

## Riesgos cerrados / mitigados

| ID | Riesgo | Severidad | Status | Mitigación |
|---|---|---|---|---|
| R1 | Migration toca 45+ filas, podría duplicar | BAJA | ✅ MITIGADO | Script chequea `(slug, 1)` antes de INSERT; tests idempotencia |
| R2 | Schema migration podría fallar en DB con datos | BAJA | ✅ MITIGADO | `CREATE TABLE IF NOT EXISTS`, idempotente |
| R6 | Bug en `wiki_escribir` async wrapper (race doble reindex) | BAJA | ✅ FIXED | Async wrapper hace todo inline (DB + archive + reindex awaited) |
| R8 | MariaDB read-only por default | BAJA | ✅ MITIGADO | `_ensure_init()` loggea + raise (no swallow) |
| R9 | pyyaml no estaba en venv | BAJA | ✅ MITIGADO | `pip install pyyaml` (idempotente) |

## Riesgos activos / watching

| ID | Riesgo | Severidad | Status | Acción recomendada |
|---|---|---|---|---|
| R3 | Auto-archive crea archivos por cada write — uso de filesystem | BAJA | ⏳ WATCHING | `MCP_ARCHIVE_ON_WRITE=0` disponible si crece mucho |
| R4 | Slugs UPPERCASE no cumplían regex original | BAJA | ✅ MITIGADO | Regex actualizado a `[a-zA-Z0-9]` + migration preserva casing |
| R5 | PyMySQL OperationalError intermitente | BAJA | ⏳ WATCHING | Pool con ping/reconnect, monitorear logs |
| R7 | `wiki_escribir` con body < 50 chars no crea chunks | BAJA | ✅ POR DISEÑO | Chunker filtra chunks vacíos. Si body entero < 50, warning log |
| R10 | Tests usan DB `mcp_memoria_test` con permisos limitados | BAJA | ⏳ WATCHING | Solo `mcp_memoria` y `mcp_memoria_test` están grantadas al user |

## Riesgos NO mitigados (out of scope)

Ver [[mop-398-future-work]] para:
- Reconciliador multi-nodo (Riesgo: nodos divergentes sin arbitraje).
- Sync a mariadb remotos (Riesgo: latencia + consistencia eventual).
- Editar .md en vim y commitear como nueva versión (Riesgo: race con wiki_escribir).

## Procedimiento para reportar nuevo riesgo

1. Crear página cruzada con slug `mop-398-issue-NNN-<desc>` en scope=`designs`.
2. Frontmatter: `related: [mop-398-known-issues, ...]`.
3. Cuerpo: descripción, severidad, mitigación propuesta, status.
4. Anunciar en briefing.

## Monitoreo

- `journalctl -u mcp-memoria -f` para errores live.
- `mcp_analyze` para auditorías periódicas del MOP.
- `mcp_metricas` para ver counts/transitions.
""",
    },
    {
        "slug": "mop-398-future-work",
        "scope": "designs",
        "frontmatter": {
            "title": "MOP-398 — Future Work backlog",
            "related": ["mop-398-wiki-research", "mop-398-known-issues"],
        },
        "body": """# MOP-398 — Future Work backlog

> Items out of scope del MOP-398 + ideas derivadas para futuros MOPs.
> Related: [[mop-398-wiki-research]] [[mop-398-known-issues]]

## Items P0 (bloquean funcionalidad core)

### REINDEX post-migration
- **Estado**: pendiente
- **Impacto**: `kag_buscar` no ve el contenido de las 43 páginas migradas porque
  `mm_entity_chunks` no se llena automáticamente.
- **Fix**: correr `scripts/index-real.py` (5-30 min para corpus de 1975 chunks).
- **Esfuerzo**: < 30 min, 1 solo comando.
- **Prioridad**: P0 (sin esto, la wiki es "invisible" semánticamente).

## Items P1 (mejoras de UX)

### Round-trip edit (vim → nueva versión)
- **Estado**: concept
- **Hipótesis**: agregar `wiki_checkout(slug, version) → escribe .md a /tmp` y
  `wiki_commit(file_path, message) → lee .md, crea nueva versión`.
- **Beneficio**: humanos pueden editar .md en su editor favorito.
- **Esfuerzo**: ~2-3 días (incluye tests + smoke).
- **Riesgo**: race con `wiki_escribir` MCP si ambos modifican mismo slug.

### `wiki_diff(slug, v1, v2)`
- **Estado**: concept
- **Hipótesis**: mostrar diff markdown entre versiones (similar a `git diff`).
- **Beneficio**: entender qué cambió entre versiones sin leer 2 archivos.
- **Esfuerzo**: ~1 día (usar library `difflib` o `unidiff`).

### `wiki_rename(slug, new_slug)`
- **Estado**: concept
- **Bloqueado por**: append-only + filesystem archive. Rename requeriría mover
  los archivos archive + actualizar `mm_entity_chunks.page_slug`.

## Items P2 (escalabilidad)

### Reconciliador multi-nodo
- **Estado**: concept (estilo `bibliotecario.cjs` de omni-mcp).
- **Hipótesis**: port del reconciliador para resolver conflictos entre versiones
  de distintas fuentes (no aplica todavía — single-node).

### Sync a mariadb remotos
- **Estado**: concept
- **Hipótesis**: replicación eventual de `mm_wiki_pages` a otros nodos.
- **Esfuerzo**: open ended.

### Embedding dedicado por página
- **Estado**: concept
- **Hipótesis**: 1 vector por página (no por chunk) — útil para similarity a nivel
  página completa.
- **Trade-off**: doble almacenamiento (chunk embeddings + page embeddings).

## Items P3 (nice-to-have)

### UI web para el wiki
- **Estado**: concept
- **Hipótesis**: SPA simple (Vite + React) que llame los tools MCP via WebSocket.
- **Esfuerzo**: ~1-2 semanas.

### `wiki_search(query)` con UI-friendly format
- **Estado**: concept
- **Hipótesis**: subset de `kag_buscar` con highlight de matches.

### Auto-tag con LLM
- **Estado**: concept
- **Hipótesis**: al escribir un page, sugerir tags vía LLM basado en contenido.

## Ideas derivadas (sesiones futuras)

- **MOP indexado por tags**: actualmente los tools no exponen tags de `mm_wiki_pages.frontmatter`.
- **Audit log**: quién escribió qué (ya está via `agent_signature`, falta exponer).
- **Garbage collection**: políticas para podar archive filesystem si crece mucho.

## Cómo priorizar

Cuando se abra un nuevo MOP, verificar este page primero (cross-ref a
[[mop-398-known-issues]] para dependencias).
""",
    },
]


async def main():
    print(f"Seeding {len(PAGES)} wiki pages for MOP-398 cross-tracking...\n")
    results = []
    for page in PAGES:
        r = await wiki_escribir(
            slug=page["slug"],
            body=page["body"],
            scope=page["scope"],
            author=AUTHOR,
            frontmatter=page["frontmatter"],
        )
        results.append(r)
        print(f"  ✓ {page['slug']} v{r['version']} chunks={r['chunks_indexed']}")

    print(f"\nVerifying via wiki_listar(scope='designs'):")
    listed = await wiki_listar(scope="designs", limit=100)
    mop_pages = [p for p in listed if p["slug"].startswith("mop-398-")]
    print(f"  Found {len(mop_pages)} MOP-398 pages in designs scope:")
    for p in mop_pages:
        print(f"    - {p['slug']} v{p['version_actual']} chunks={p['chunks_count']}")


if __name__ == "__main__":
    asyncio.run(main())
