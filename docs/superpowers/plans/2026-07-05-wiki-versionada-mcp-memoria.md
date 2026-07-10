# Wiki Versionada en mcp-memoria — Implementation Plan (v2: DB-only + auto-archive)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Agregar 5 tools (`wiki_escribir`, `wiki_leer`, `wiki_historial`, `wiki_listar`, `wiki_export`) al `mcp-memoria` con tabla append-only `mm_wiki_pages` y auto-archive a filesystem (`<WORKSPACE>/wiki_archive/<scope>/<slug>-v<N>.md`) como backup inmutable por versión.

**Architecture:**
- `mm_wiki_pages` (PK `slug+version`, append-only) es la **source of truth**. Los 5 tools leen/escriben acá.
- `mm_entity_chunks` (FULLTEXT + embeddings) es la vista buscable. Se reindexa post-write vía el chunker existente.
- `<WORKSPACE>/wiki_archive/<scope>/<slug>-v<N>.md` es el **artefacto/backup**. Filename inmutable por versión (append-only en filesystem, sin lock). El live NO lee de acá.
- `kb/<scope>/*.md` (legacy 45+ archivos) sigue su flujo actual: ingest al startup, indexado en `mm_entity_chunks`. No se migra.

**Tech Stack:** Python 3.12 + FastMCP 3.4 + PyMySQL + MariaDB 11.8 + fastembed + pyyaml.

**Source of truth:** IDEA-98 (mop-mcp CANDIDATE) + auditoría secops 2026-07-05 + decisión Rodrigo 2026-07-05 ("filesystem como backup, DB como live").

**Diferencias vs v1 (descartada):** sin `WikiLock`, sin atomic tmp+rename, sin dual-write race semantics. `wiki_leer`/`wiki_listar`/`wiki_historial` leen SOLO de DB. Archive .md es write-only desde la perspectiva de los tools MCP.

## Global Constraints

- **Source of truth:** `mm_wiki_pages` (MariaDB). NUNCA UPDATE/DELETE por API.
- **Backend DB:** MariaDB (no flat-file). Tabla con PK compuesta `(slug, version)`.
- **Archive filesystem:** `<WORKSPACE>/wiki_archive/<scope>/<slug>-v<N>.md`. Filename único por versión (append-only). Sin lock, sin atomic rename.
- **Archive enable:** `MCP_ARCHIVE_ON_WRITE` env (default `1` = ON). Si `0`, saltea el write a filesystem (devuelve `"archived": false` en el response).
- **Slugs:** lowercase, regex `^[a-z0-9][a-z0-9_-]{0,198}$`. Vacío/`..`/`/` → `ValueError`.
- **Scopes:** `concepts`, `designs`, `lessons`, `papers`, `reports` (los 5 dirs en `ALLOWED_DIRS`).
- **`wiki_archive/` NO está en `ALLOWED_DIRS`** de `paths.py` — el chunker no debe re-ingestar archive files.
- **Tests:** pytest en `/opt/mcps/memoria/tests/`. Cobertura: cada tool happy path + cada constraint violation + archive ON/OFF.
- **Working directory:** `/opt/mcps/memoria/` (no es git repo).
- **Service reload:** tras deploy, `sudo systemctl restart mcp-memoria` + smoke-test.

## File Structure

| File | Status | Responsibility |
|---|---|---|
| `src/memoria_mcp/db.py` | modify | Agregar CREATE TABLE `mm_wiki_pages` en `init_schema()` |
| `src/memoria_mcp/paths.py` | modify | Helper `wiki_archive_path(slug, scope, version) -> Path`. NO modificar `ALLOWED_DIRS`. |
| `src/memoria_mcp/wiki_io.py` | create | `parse_frontmatter()`, `render_with_frontmatter()` (sin `read_page_filesystem` — ya no es hot path) |
| `src/memoria_mcp/tools/wiki.py` | create | 5 funciones async |
| `src/memoria_mcp/server.py` | modify | Registrar 5 nuevos `@mcp.tool(...)` |
| `tests/test_wiki_db.py` | create | Tests del schema |
| `tests/test_wiki_io.py` | create | Tests de frontmatter |
| `tests/test_wiki_archive.py` | create | Tests del path helper + archive write (con ON/OFF) |
| `tests/test_wiki_tools.py` | create | Tests unitarios de los 5 tools |
| `tests/test_wiki_e2e.py` | create | Test integración que ejercita los 5 tools |
| `docs/DESIGN-WIKI.md` | create | Doc de diseño (reemplaza el de cloudops) |
| `CHANGELOG.md` | modify | Entrada 0.2.0 |
| `scripts/migrate-kb-to-wiki.py` | create | Script único de migración kb/ legacy → mm_wiki_pages |

---

## Task 1: Schema — agregar tabla `mm_wiki_pages`

**Files:**
- Modify: `/opt/mcps/memoria/src/memoria_mcp/db.py` (agregar CREATE TABLE)
- Create: `/opt/mcps/memoria/tests/test_wiki_db.py`

**Interfaces:**
- Produces: tabla `mm_wiki_pages(slug, version, body, frontmatter, author, scope, ts)` con PK `(slug, version)`. `init_schema()` la crea idempotente.

- [ ] **Step 1.1: Escribir el test**

Create `/opt/mcps/memoria/tests/test_wiki_db.py`:

```python
"""test_wiki_db.py — verifica que init_schema() crea mm_wiki_pages."""
from __future__ import annotations

import pytest

from memoria_mcp import db


@pytest.fixture
def fresh_db():
    db.DB_NAME = "mcp_memoria_test"
    db.init_schema()
    yield
    with db._pool().connection() as conn:
        with conn.cursor() as cur:
            for t in (
                "mm_wiki_pages", "mm_entity_chunks", "mm_relations",
                "mm_entities", "mm_search_feedback", "mm_search_log",
                "mm_conflict_queue",
            ):
                cur.execute(f"DROP TABLE IF EXISTS {t}")


def test_wiki_pages_table_created(fresh_db):
    rows = db.read_many(
        "SELECT COLUMN_NAME, DATA_TYPE FROM information_schema.COLUMNS "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'mm_wiki_pages' "
        "ORDER BY ORDINAL_POSITION"
    )
    cols = {r["COLUMN_NAME"]: r["DATA_TYPE"] for r in rows}
    assert cols["slug"] == "varchar"
    assert cols["version"] == "int"
    assert cols["body"] == "mediumtext"
    assert cols["frontmatter"] == "json"
    assert cols["author"] == "varchar"
    assert cols["scope"] == "varchar"
    assert cols["ts"] == "timestamp"

    pk_rows = db.read_many(
        "SELECT COLUMN_NAME FROM information_schema.KEY_COLUMN_USAGE "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'mm_wiki_pages' "
        "AND CONSTRAINT_NAME = 'PRIMARY'"
    )
    assert {r["COLUMN_NAME"] for r in pk_rows} == {"slug", "version"}


def test_wiki_pages_insert_and_append(fresh_db):
    db.write_one(
        "INSERT INTO mm_wiki_pages (slug, version, body, author, scope) "
        "VALUES (%s, %s, %s, %s, %s)",
        ("mi-slug", 1, "# v1", "test", "concepts"),
    )
    db.write_one(
        "INSERT INTO mm_wiki_pages (slug, version, body, author, scope) "
        "VALUES (%s, %s, %s, %s, %s)",
        ("mi-slug", 2, "# v2", "test", "concepts"),
    )
    rows = db.read_many(
        "SELECT version FROM mm_wiki_pages WHERE slug = %s ORDER BY version",
        ("mi-slug",),
    )
    assert [r["version"] for r in rows] == [1, 2]


def test_wiki_pages_pk_rejects_duplicate(fresh_db):
    db.write_one(
        "INSERT INTO mm_wiki_pages (slug, version, body, author, scope) "
        "VALUES (%s, %s, %s, %s, %s)",
        ("dup", 1, "x", "test", "concepts"),
    )
    with pytest.raises(Exception) as exc_info:
        db.write_one(
            "INSERT INTO mm_wiki_pages (slug, version, body, author, scope) "
            "VALUES (%s, %s, %s, %s, %s)",
            ("dup", 1, "y", "test", "concepts"),
        )
    assert "Duplicate" in str(exc_info.value) or "1062" in str(exc_info.value)
```

- [ ] **Step 1.2: Correr test — debe fallar**

Run:
```bash
cd /opt/mcps/memoria && .venv/bin/pytest tests/test_wiki_db.py -v
```

Expected: `FAILED` con "Table 'mcp_memoria_test.mm_wiki_pages' doesn't exist".

- [ ] **Step 1.3: Modificar `db.py` para agregar CREATE TABLE**

Edit `/opt/mcps/memoria/src/memoria_mcp/db.py`. Localizar la lista `_SCHEMA_STATEMENTS` (los CREATE TABLE como strings multiline) y agregar al final de la lista (antes del `]`):

```python
    # Wiki versionada (mm_wiki_pages) — append-only, source of truth.
    # PK compuesta (slug, version) garantiza NUNCA overwrite.
    # Backup filesystem (wiki_archive/) se escribe desde wiki_escribir
    # pero NO es leído por el live — es solo artefacto.
    """
    CREATE TABLE IF NOT EXISTS mm_wiki_pages (
      slug VARCHAR(200) NOT NULL,
      version INT NOT NULL,
      body MEDIUMTEXT NOT NULL,
      frontmatter JSON,
      author VARCHAR(64) NOT NULL,
      scope VARCHAR(50),
      ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
      PRIMARY KEY (slug, version),
      INDEX idx_slug (slug),
      INDEX idx_scope (scope),
      INDEX idx_ts (ts)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
```

- [ ] **Step 1.4: Correr test — debe pasar**

Run:
```bash
cd /opt/mcps/memoria && .venv/bin/pytest tests/test_wiki_db.py -v
```

Expected: `3 passed`.

- [ ] **Step 1.5: Verificar contra DB real + CHANGELOG**

Run:
```bash
sudo -u rodrigo mariadb -u mcp_memoria -p"$MCP_DB_PASS" mcp_memoria \
  -e "DESCRIBE mm_wiki_pages;" 2>&1 | grep -v Warning
```

Append a `/opt/mcps/memoria/CHANGELOG.md`:

```markdown
### Added (Task 1 — schema wiki)
- Tabla `mm_wiki_pages` con PK compuesta (slug, version), append-only.
- Migration idempotente via `init_schema()`.
```

---

## Task 2: Path helper — `wiki_archive_path`

**Files:**
- Modify: `/opt/mcps/memoria/src/memoria_mcp/paths.py`
- Create: `/opt/mcps/memoria/tests/test_wiki_archive.py`

**Interfaces:**
- Consumes: `WORKSPACE` (línea 18)
- Produces:
  - `wiki_archive_path(slug: str, scope: str, version: int) -> Path` → `<WORKSPACE>/wiki_archive/<scope>/<slug>-v<N>.md`. Valida slug y scope.
  - `wiki_archive_dir(scope: str) -> Path` → `<WORKSPACE>/wiki_archive/<scope>/`. Usado por `wiki_escribir` para `mkdir(parents=True, exist_ok=True)`.

- [ ] **Step 2.1: Tests**

Create `/opt/mcps/memoria/tests/test_wiki_archive.py`:

```python
"""test_wiki_archive.py — tests del path helper archive."""
from __future__ import annotations

from pathlib import Path

import pytest

from memoria_mcp import paths


def test_wiki_archive_path_happy():
    p = paths.wiki_archive_path("mi-design", "designs", 3)
    assert p == paths.WORKSPACE / "wiki_archive" / "designs" / "mi-design-v3.md"


def test_wiki_archive_path_unique_per_version():
    p1 = paths.wiki_archive_path("foo", "concepts", 1)
    p2 = paths.wiki_archive_path("foo", "concepts", 2)
    assert p1 != p2
    assert p1.name == "foo-v1.md"
    assert p2.name == "foo-v2.md"


def test_wiki_archive_path_rejects_invalid_slug():
    with pytest.raises(ValueError, match="slug inválido"):
        paths.wiki_archive_path("../etc/passwd", "concepts", 1)
    with pytest.raises(ValueError, match="slug inválido"):
        paths.wiki_archive_path("MAYUSC", "concepts", 1)
    with pytest.raises(ValueError, match="slug inválido"):
        paths.wiki_archive_path("", "concepts", 1)


def test_wiki_archive_path_rejects_invalid_scope():
    with pytest.raises(ValueError, match="scope inválido"):
        paths.wiki_archive_path("ok", "../escape", 1)
    with pytest.raises(ValueError, match="scope inválido"):
        paths.wiki_archive_path("ok", "not-a-scope", 1)


def test_wiki_archive_dir_creates_per_scope():
    d = paths.wiki_archive_dir("lessons")
    assert d == paths.WORKSPACE / "wiki_archive" / "lessons"
```

- [ ] **Step 2.2: Correr test — debe fallar**

Run:
```bash
cd /opt/mcps/memoria && .venv/bin/pytest tests/test_wiki_archive.py::test_wiki_archive_path_happy -v
```

Expected: `FAILED` con `AttributeError`.

- [ ] **Step 2.3: Implementar los helpers**

Append al final de `/opt/mcps/memoria/src/memoria_mcp/paths.py` (después de la lógica existente):

```python
# ── Wiki archive (filesystem como backup, NO live) ────────────────
import re as _re

_VALID_SCOPE_NAMES = {"concepts", "designs", "lessons", "papers", "reports"}
_SLUG_RE = _re.compile(r"^[a-z0-9][a-z0-9_-]{0,198}$")

ARCHIVE_ROOT = WORKSPACE / "wiki_archive"


def _validate_slug_scope(slug: str, scope: str) -> None:
    if not _SLUG_RE.match(slug or ""):
        raise ValueError(
            f"slug inválido: {slug!r}. Debe coincidir ^[a-z0-9][a-z0-9_-]{{0,198}}$"
        )
    if scope not in _VALID_SCOPE_NAMES:
        raise ValueError(
            f"scope inválido: {scope!r}. Debe ser uno de {sorted(_VALID_SCOPE_NAMES)}"
        )


def wiki_archive_path(slug: str, scope: str, version: int) -> Path:
    """Path inmutable por versión: <WORKSPACE>/wiki_archive/<scope>/<slug>-v<N>.md.

    Filename único por versión → no hay race entre writes (cualquier v<N> solo
    se escribe UNA vez). El chunker NO debe leer este dir (no está en ALLOWED_DIRS).
    """
    _validate_slug_scope(slug, scope)
    if not isinstance(version, int) or version < 1:
        raise ValueError(f"version inválida: {version!r}. Debe ser int >= 1")
    return ARCHIVE_ROOT / scope / f"{slug}-v{version}.md"


def wiki_archive_dir(scope: str) -> Path:
    """<WORKSPACE>/wiki_archive/<scope>/. Usado para mkdir pre-write."""
    if scope not in _VALID_SCOPE_NAMES:
        raise ValueError(f"scope inválido: {scope!r}")
    return ARCHIVE_ROOT / scope
```

- [ ] **Step 2.4: Correr test — debe pasar**

Run:
```bash
cd /opt/mcps/memoria && .venv/bin/pytest tests/test_wiki_archive.py -v
```

Expected: `5 passed`.

- [ ] **Step 2.5: Smoke test**

Run:
```bash
cd /opt/mcps/memoria && .venv/bin/python -c "
from memoria_mcp.paths import wiki_archive_path
print(wiki_archive_path('test', 'designs', 1))
print(wiki_archive_path('test', 'designs', 99))
"
```

Expected:
```
/opt/mcp-memoria/snapshot/kb/wiki_archive/designs/test-v1.md
/opt/mcp-memoria/snapshot/kb/wiki_archive/designs/test-v99.md
```

---

## Task 3: Frontmatter I/O — `wiki_io.py`

**Files:**
- Create: `/opt/mcps/memoria/src/memoria_mcp/wiki_io.py`
- Create: `/opt/mcps/memoria/tests/test_wiki_io.py`

**Interfaces:**
- `parse_frontmatter(text: str) -> tuple[dict, str]`
- `render_with_frontmatter(fm: dict, body: str) -> str`

(No `read_page_filesystem` — los tools leen SOLO de DB. El archive es write-only desde MCP.)

- [ ] **Step 3.1: Tests**

Create `/opt/mcps/memoria/tests/test_wiki_io.py`:

```python
"""test_wiki_io.py — tests de parse/render frontmatter."""
from __future__ import annotations

from memoria_mcp.wiki_io import parse_frontmatter, render_with_frontmatter


def test_parse_frontmatter_with_yaml():
    text = (
        "---\ntitle: Mi Diseño\ntags: [a, b]\nversion: 3\n---\n"
        "# Heading\n\nBody."
    )
    fm, body = parse_frontmatter(text)
    assert fm["title"] == "Mi Diseño"
    assert fm["tags"] == ["a", "b"]
    assert fm["version"] == 3
    assert body.strip() == "# Heading\n\nBody."


def test_parse_frontmatter_no_yaml():
    fm, body = parse_frontmatter("# Solo markdown")
    assert fm == {}
    assert body == "# Solo markdown"


def test_parse_frontmatter_empty():
    fm, body = parse_frontmatter("")
    assert fm == {}
    assert body == ""


def test_render_with_frontmatter():
    out = render_with_frontmatter({"title": "X", "version": 1}, "# X\n\nFoo.")
    assert out.startswith("---\n")
    assert "title: X" in out
    assert "version: 1" in out
    assert out.endswith("# X\n\nFoo.")


def test_render_roundtrip():
    fm_in = {"title": "Y", "tags": ["c"]}
    body_in = "Body content"
    fm_out, body_out = parse_frontmatter(render_with_frontmatter(fm_in, body_in))
    assert fm_out == fm_in
    assert body_out == body_in
```

- [ ] **Step 3.2: Correr test — debe fallar**

Run:
```bash
cd /opt/mcps/memoria && .venv/bin/pytest tests/test_wiki_io.py -v
```

Expected: `ModuleNotFoundError`.

- [ ] **Step 3.3: Implementar `wiki_io.py`**

Create `/opt/mcps/memoria/src/memoria_mcp/wiki_io.py`:

```python
"""wiki_io.py — parse y render de frontmatter YAML.

Patrón (réplica conceptual de omni-mcp wiki subsystem):
- Frontmatter entre dos líneas `---` al inicio.
- YAML real (no JSON) para flexibilidad humana.
"""
from __future__ import annotations

import logging
import re

import yaml

log = logging.getLogger("memoria_wiki_io")

_FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?\n)---\s*\n?(.*)\Z", re.DOTALL)


def parse_frontmatter(text: str) -> tuple[dict, str]:
    if not text:
        return {}, ""
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return {}, text
    try:
        fm = yaml.safe_load(m.group(1)) or {}
        if not isinstance(fm, dict):
            log.warning("frontmatter_not_dict", extra={"type": type(fm).__name__})
            fm = {}
    except yaml.YAMLError as e:
        log.warning("frontmatter_yaml_error", extra={"error": str(e)})
        fm = {}
    return fm, m.group(2)


def render_with_frontmatter(fm: dict, body: str) -> str:
    if not fm:
        return body
    yaml_str = yaml.safe_dump(
        fm, allow_unicode=True, sort_keys=False, default_flow_style=False,
    ).rstrip()
    return f"---\n{yaml_str}\n---\n{body}"
```

Si `pyyaml` no está en el venv:

Run:
```bash
cd /opt/mcps/memoria && .venv/bin/pip install pyyaml
```

- [ ] **Step 3.4: Correr test — debe pasar**

Run:
```bash
cd /opt/mcps/memoria && .venv/bin/pytest tests/test_wiki_io.py -v
```

Expected: `5 passed`.

---

## Task 4: Tools `wiki_listar` y `wiki_leer` (DB-only)

**Files:**
- Create: `/opt/mcps/memoria/src/memoria_mcp/tools/wiki.py`
- Modify: `/opt/mcps/memoria/src/memoria_mcp/server.py` (registrar 2 tools)
- Create: `/opt/mcps/memoria/tests/test_wiki_tools.py`

**Interfaces:**
- `wiki_listar_sync(scope=None, limit=50) -> list[dict]` — DB only. Devuelve `[{slug, scope, version_actual, ts, chunks_count, archive_path}]`.
- `wiki_leer_sync(slug, version=None, scope=None) -> dict` — DB only. Devuelve `{slug, scope, version, body, frontmatter, author, ts, archive_path}`.

- [ ] **Step 4.1: Tests**

Create `/opt/mcps/memoria/tests/test_wiki_tools.py`:

```python
"""test_wiki_tools.py — tests de los 5 tools wiki."""
from __future__ import annotations

import json as _json
from unittest.mock import patch

import pytest

from memoria_mcp import db
from memoria_mcp.tools.wiki import (
    wiki_listar_sync,
    wiki_leer_sync,
    wiki_escribir_sync,
    wiki_historial_sync,
    wiki_export_sync,
)


@pytest.fixture
def seeded_db(tmp_path):
    db.DB_NAME = "mcp_memoria_test_wiki"
    db.init_schema()
    db.write_one(
        "INSERT INTO mm_wiki_pages (slug, version, body, frontmatter, author, scope) "
        "VALUES (%s, 1, %s, %s, %s, %s)",
        ("page-a", "# A v1", _json.dumps({"title": "A"}), "test", "designs"),
    )
    db.write_one(
        "INSERT INTO mm_wiki_pages (slug, version, body, frontmatter, author, scope) "
        "VALUES (%s, 2, %s, %s, %s, %s)",
        ("page-a", "# A v2", _json.dumps({"title": "A"}), "test", "designs"),
    )
    db.write_one(
        "INSERT INTO mm_wiki_pages (slug, version, body, author, scope) "
        "VALUES (%s, 1, %s, %s, %s)",
        ("page-b", "# B v1", "test", "lessons"),
    )
    yield tmp_path
    with db._pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DROP TABLE IF EXISTS mm_wiki_pages")


def test_wiki_listar_returns_db_pages(seeded_db):
    result = wiki_listar_sync()
    slugs = sorted(p["slug"] for p in result)
    assert slugs == ["page-a", "page-b"]


def test_wiki_listar_filters_by_scope(seeded_db):
    result = wiki_listar_sync(scope="lessons")
    assert len(result) == 1
    assert result[0]["slug"] == "page-b"


def test_wiki_listar_includes_archive_path(seeded_db):
    result = wiki_listar_sync(scope="designs")
    page = next(p for p in result if p["slug"] == "page-a")
    assert page["archive_path"].endswith("page-a-v2.md")


def test_wiki_leer_latest_version(seeded_db):
    result = wiki_leer_sync(slug="page-a")
    assert result["version"] == 2
    assert result["body"] == "# A v2"


def test_wiki_leer_specific_version(seeded_db):
    result = wiki_leer_sync(slug="page-a", version=1)
    assert result["version"] == 1
    assert result["body"] == "# A v1"


def test_wiki_leer_with_scope_filter(seeded_db):
    result = wiki_leer_sync(slug="page-a", scope="designs")
    assert result["scope"] == "designs"
    assert result["version"] == 2


def test_wiki_leer_not_found_raises(seeded_db):
    with pytest.raises(LookupError, match="no existe"):
        wiki_leer_sync(slug="page-zzz")
```

- [ ] **Step 4.2: Correr test — debe fallar**

Run:
```bash
cd /opt/mcps/memoria && .venv/bin/pytest tests/test_wiki_tools.py::test_wiki_listar_returns_db_pages -v
```

Expected: `ModuleNotFoundError`.

- [ ] **Step 4.3: Implementar `tools/wiki.py` (primera parte: listar + leer)**

Create `/opt/mcps/memoria/src/memoria_mcp/tools/wiki.py`:

```python
"""tools/wiki.py — 5 tools para wiki versionada.

Source of truth: mm_wiki_pages (DB). Filesystem archive es write-only artefact.

- wiki_listar(scope?, limit?)    : lista páginas (DB only).
- wiki_leer(slug, version?, scope?): lee página específica (DB only).
- wiki_escribir(slug, body, scope, author, frontmatter?): INSERT nueva versión + archive.
- wiki_historial(slug, scope?)   : todas las versiones (DB only).
- wiki_export(slug?, scope?)     : bundle markdown (DB only).
"""
from __future__ import annotations

import json as _json
import logging
import os
from datetime import datetime, timezone
from typing import Optional

from .. import db, paths
from ..wiki_io import render_with_frontmatter

log = logging.getLogger("memoria_wiki_tool")

ARCHIVE_ON_WRITE = os.environ.get("MCP_ARCHIVE_ON_WRITE", "1") == "1"


# ── Helpers ────────────────────────────────────────────────────────

def _archive_path(slug: str, scope: str, version: int):
    """Devuelve el path archive esperado (no verifica existencia)."""
    return paths.wiki_archive_path(slug, scope, version)


def _latest_version(slug: str, scope: Optional[str]) -> Optional[int]:
    """Lee la última versión de un slug (scope opcional). None si no existe."""
    if scope:
        row = db.read_one(
            "SELECT MAX(version) AS v FROM mm_wiki_pages WHERE slug = %s AND scope = %s",
            (slug, scope),
        )
    else:
        row = db.read_one(
            "SELECT MAX(version) AS v FROM mm_wiki_pages WHERE slug = %s",
            (slug,),
        )
    return row["v"] if row and row["v"] is not None else None


# ── wiki_listar ────────────────────────────────────────────────────

def wiki_listar_sync(scope: Optional[str] = None, limit: int = 50) -> list[dict]:
    if scope:
        rows = db.read_many(
            "SELECT slug, scope, MAX(version) AS version, MAX(ts) AS ts "
            "FROM mm_wiki_pages WHERE scope = %s "
            "GROUP BY slug, scope ORDER BY ts DESC LIMIT %s",
            (scope, limit),
        )
    else:
        rows = db.read_many(
            "SELECT slug, scope, MAX(version) AS version, MAX(ts) AS ts "
            "FROM mm_wiki_pages GROUP BY slug, scope ORDER BY ts DESC LIMIT %s",
            (limit,),
        )
    out = []
    for r in rows:
        slug, sc, ver = r["slug"], r["scope"], r["version"]
        cc = db.read_one(
            "SELECT COUNT(*) AS c FROM mm_entity_chunks WHERE page_slug = %s",
            (slug,),
        )
        archive_p = _archive_path(slug, sc, ver)
        out.append({
            "slug": slug,
            "scope": sc,
            "version_actual": ver,
            "ts": r["ts"].isoformat() if r["ts"] else None,
            "chunks_count": cc["c"] if cc else 0,
            "archive_path": str(archive_p),
            "archive_present": archive_p.exists(),
        })
    return out


# ── wiki_leer ──────────────────────────────────────────────────────

def wiki_leer_sync(
    slug: str,
    version: Optional[int] = None,
    scope: Optional[str] = None,
) -> dict:
    if version is not None:
        # Versión específica
        if scope:
            row = db.read_one(
                "SELECT version, body, frontmatter, author, ts, scope "
                "FROM mm_wiki_pages WHERE slug = %s AND scope = %s AND version = %s",
                (slug, scope, version),
            )
        else:
            row = db.read_one(
                "SELECT version, body, frontmatter, author, ts, scope "
                "FROM mm_wiki_pages WHERE slug = %s AND version = %s",
                (slug, version),
            )
        if not row:
            raise LookupError(f"no existe {slug} v{version}")
        sc = row["scope"]
    else:
        # Última versión
        if scope:
            row = db.read_one(
                "SELECT version, body, frontmatter, author, ts, scope "
                "FROM mm_wiki_pages WHERE slug = %s AND scope = %s "
                "ORDER BY version DESC LIMIT 1",
                (slug, scope),
            )
        else:
            row = db.read_one(
                "SELECT version, body, frontmatter, author, ts, scope "
                "FROM mm_wiki_pages WHERE slug = %s ORDER BY version DESC LIMIT 1",
                (slug,),
            )
        if not row:
            raise LookupError(f"no existe {slug}")
        version = row["version"]
        sc = row["scope"]

    return {
        "slug": slug,
        "scope": sc,
        "version": version,
        "body": row["body"],
        "frontmatter": _json.loads(row["frontmatter"]) if row["frontmatter"] else {},
        "author": row["author"],
        "ts": row["ts"].isoformat() if row["ts"] else None,
        "archive_path": str(_archive_path(slug, sc, version)),
    }


# ── Async wrappers ─────────────────────────────────────────────────

async def wiki_listar(scope: Optional[str] = None, limit: int = 50) -> list[dict]:
    return wiki_listar_sync(scope=scope, limit=limit)


async def wiki_leer(
    slug: str,
    version: Optional[int] = None,
    scope: Optional[str] = None,
) -> dict:
    return wiki_leer_sync(slug=slug, version=version, scope=scope)
```

- [ ] **Step 4.4: Correr tests**

Run:
```bash
cd /opt/mcps/memoria && .venv/bin/pytest tests/test_wiki_tools.py -v -k "listar or leer"
```

Expected: `7 passed`.

- [ ] **Step 4.5: Registrar los 2 tools en `server.py`**

Edit `/opt/mcps/memoria/src/memoria_mcp/server.py` línea 22, cambiar:

```python
from .tools import decisions, lessons, adr, project, links, grafo, kag, bibliotecario as bib_tool
```

a:

```python
from .tools import decisions, lessons, adr, project, links, grafo, kag, bibliotecario as bib_tool, wiki
```

Append después de `tool_conflict_resolve`:

```python


@mcp.tool(name="wiki_listar", description="Lista páginas wiki (DB). Devuelve última versión + # chunks + path archive.")
async def tool_wiki_listar(scope: str | None = None, limit: int = 50) -> list[dict]:
    _ensure_init()
    return await wiki.wiki_listar(scope=scope, limit=limit)


@mcp.tool(name="wiki_leer", description="Lee una página wiki por slug (DB). Acepta version opcional.")
async def tool_wiki_leer(slug: str, version: int | None = None, scope: str | None = None) -> dict:
    _ensure_init()
    return await wiki.wiki_leer(slug=slug, version=version, scope=scope)
```

---

## Task 5: Tool `wiki_escribir` (DB + auto-archive)

**Files:**
- Modify: `/opt/mcps/memoria/src/memoria_mcp/tools/wiki.py`
- Modify: `/opt/mcps/memoria/src/memoria_mcp/server.py`
- Modify: `/opt/mcps/memoria/tests/test_wiki_tools.py`

**Interfaces:**
- `wiki_escribir_sync(slug, body, scope, author, frontmatter=None) -> dict`
  1. Validar slug + scope.
  2. `next_version = MAX(version) + 1` en DB.
  3. INSERT en `mm_wiki_pages` (append-only). Si falla, raise sin tocar filesystem.
  4. Si `MCP_ARCHIVE_ON_WRITE=1`: escribir `<WORKSPACE>/wiki_archive/<scope>/<slug>-v<N>.md` con frontmatter. Sin lock — filename único.
  5. Reindex async vía `chunker.chunk_and_index()`.
  6. Devolver `{slug, scope, version, ts, chunks_indexed, archived, archive_path}`.

- [ ] **Step 5.1: Tests**

Append a `/opt/mcps/memoria/tests/test_wiki_tools.py`:

```python
def test_wiki_escribir_creates_v1_and_archive(tmp_path, monkeypatch):
    monkeypatch.setenv("MCP_ARCHIVE_ON_WRITE", "1")
    from memoria_mcp import wiki_io
    import importlib
    import memoria_mcp.tools.wiki as wmod
    importlib.reload(wmod)  # re-leer ARCHIVE_ON_WRITE

    from memoria_mcp.tools.wiki import wiki_escribir_sync as _w
    with patch("memoria_mcp.tools.wiki.chunker") as mock_chunker, \
         patch("memoria_mcp.tools.wiki.paths") as mock_paths:
        mock_paths.wiki_archive_path.side_effect = (
            lambda s, sc, v: tmp_path / "wiki_archive" / sc / f"{s}-v{v}.md"
        )
        mock_paths.wiki_archive_dir.side_effect = (
            lambda sc: tmp_path / "wiki_archive" / sc
        )
        async def fake_chunk(page_slug, content, scope, title, embed_text_fn):
            return 3
        mock_chunker.chunk_and_index = fake_chunk

        result = _w(
            slug="nueva", body="# Nueva\n\nContenido.",
            scope="designs", author="test",
            frontmatter={"title": "Nueva"},
        )

    assert result["version"] == 1
    assert result["archived"] is True
    assert result["chunks_indexed"] == 3
    archive = tmp_path / "wiki_archive" / "designs" / "nueva-v1.md"
    assert archive.exists()
    content = archive.read_text()
    assert "version: 1" in content
    assert "title: Nueva" in content
    assert "# Nueva" in content


def test_wiki_escribir_appends_v2(tmp_path):
    db.write_one(
        "INSERT INTO mm_wiki_pages (slug, version, body, author, scope) "
        "VALUES (%s, 1, %s, %s, %s)",
        ("dup", "# v1", "test", "lessons"),
    )
    from memoria_mcp.tools.wiki import wiki_escribir_sync as _w
    with patch("memoria_mcp.tools.wiki.chunker") as mock_chunker, \
         patch("memoria_mcp.tools.wiki.paths") as mock_paths:
        mock_paths.wiki_archive_path.side_effect = (
            lambda s, sc, v: tmp_path / "wiki_archive" / sc / f"{s}-v{v}.md"
        )
        mock_paths.wiki_archive_dir.side_effect = (
            lambda sc: tmp_path / "wiki_archive" / sc
        )
        async def fake_chunk(*a, **k):
            return 1
        mock_chunker.chunk_and_index = fake_chunk
        result = _w(slug="dup", body="# v2", scope="lessons", author="t")

    assert result["version"] == 2
    rows = db.read_many(
        "SELECT version FROM mm_wiki_pages WHERE slug = %s ORDER BY version",
        ("dup",),
    )
    assert [r["version"] for r in rows] == [1, 2]
    assert (tmp_path / "wiki_archive" / "lessons" / "dup-v2.md").exists()


def test_wiki_escribir_archive_disabled(tmp_path, monkeypatch):
    monkeypatch.setenv("MCP_ARCHIVE_ON_WRITE", "0")
    import importlib, memoria_mcp.tools.wiki as wmod
    importlib.reload(wmod)
    from memoria_mcp.tools.wiki import wiki_escribir_sync as _w

    with patch("memoria_mcp.tools.wiki.chunker") as mock_chunker:
        async def fake_chunk(*a, **k):
            return 0
        mock_chunker.chunk_and_index = fake_chunk
        result = _w(slug="noarch", body="x", scope="concepts", author="t")

    assert result["archived"] is False
    assert "archive_path" not in result or result.get("archive_path") is None
    assert not (tmp_path / "wiki_archive").exists()


def test_wiki_escribir_rejects_invalid_slug(tmp_path):
    from memoria_mcp.tools.wiki import wiki_escribir_sync as _w
    with patch("memoria_mcp.tools.wiki.paths") as mock_paths:
        mock_paths.wiki_archive_path.side_effect = (
            lambda s, sc, v: tmp_path / "wiki_archive" / sc / f"{s}-v{v}.md"
        )
        with pytest.raises(ValueError, match="slug inválido"):
            _w(slug="../escape", body="x", scope="designs", author="t")


def test_wiki_escribir_rejects_invalid_scope(tmp_path):
    from memoria_mcp.tools.wiki import wiki_escribir_sync as _w
    with pytest.raises(ValueError, match="scope inválido"):
        _w(slug="ok", body="x", scope="not-real", author="t")
```

- [ ] **Step 5.2: Correr test — debe fallar**

Run:
```bash
cd /opt/mcps/memoria && .venv/bin/pytest tests/test_wiki_tools.py::test_wiki_escribir_creates_v1_and_archive -v
```

Expected: `ImportError: cannot import name 'wiki_escribir_sync'`.

- [ ] **Step 5.3: Implementar `wiki_escribir_sync`**

Append a `/opt/mcps/memoria/src/memoria_mcp/tools/wiki.py`:

```python
import asyncio
import time as _time


def wiki_escribir_sync(
    slug: str,
    body: str,
    scope: str,
    author: str,
    frontmatter: Optional[dict] = None,
) -> dict:
    """Escribe nueva versión en DB + (opcional) archive filesystem + reindex."""
    # 1. Validación vía path helper (raise antes de tocar nada)
    # El helper valida slug + scope; también devuelve el path archive esperado.
    next_version_row = db.read_one(
        "SELECT COALESCE(MAX(version), 0) AS v FROM mm_wiki_pages WHERE slug = %s",
        (slug,),
    )
    next_version = (next_version_row["v"] if next_version_row else 0) + 1
    # Construimos el path para forzar validación de slug/scope ahora
    archive_p = paths.wiki_archive_path(slug, scope, next_version)

    # 2. INSERT (append-only). Si falla, raise sin tocar filesystem.
    fm_json = _json.dumps(frontmatter or {}, ensure_ascii=False)
    db.write_one(
        "INSERT INTO mm_wiki_pages (slug, version, body, frontmatter, author, scope) "
        "VALUES (%s, %s, %s, %s, %s, %s)",
        (slug, next_version, body, fm_json, author, scope),
    )
    ts_row = db.read_one(
        "SELECT ts FROM mm_wiki_pages WHERE slug = %s AND version = %s",
        (slug, next_version),
    )

    # 3. Archive (si enabled). Filename único por versión → no race.
    archived = False
    if ARCHIVE_ON_WRITE:
        archive_dir = paths.wiki_archive_dir(scope)
        archive_dir.mkdir(parents=True, exist_ok=True)
        fm_to_write = dict(frontmatter or {})
        fm_to_write["version"] = next_version
        fm_to_write["author"] = author
        fm_to_write["scope"] = scope
        archive_p.write_text(
            render_with_frontmatter(fm_to_write, body), encoding="utf-8",
        )
        archived = True

    # 4. Reindex async
    async def _reindex():
        from ..chunker import chunk_and_index as _ci
        from ..embed import embed_text
        return await _ci(
            page_slug=slug, content=body, scope=scope,
            title=(frontmatter or {}).get("title", slug),
            embed_text_fn=embed_text,
        )

    start = _time.monotonic()
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_reindex())
        chunks_indexed = -1
    except RuntimeError:
        chunks_indexed = asyncio.run(_reindex())

    return {
        "slug": slug,
        "scope": scope,
        "version": next_version,
        "ts": ts_row["ts"].isoformat() if ts_row and ts_row["ts"] else None,
        "chunks_indexed": chunks_indexed,
        "archived": archived,
        "archive_path": str(archive_p) if archived else None,
        "reindex_ms": int((_time.monotonic() - start) * 1000),
    }


async def wiki_escribir(
    slug: str,
    body: str,
    scope: str,
    author: str,
    frontmatter: Optional[dict] = None,
) -> dict:
    """Async wrapper: delega a sync helper + fuerza reindex await."""
    import time as _time
    start = _time.monotonic()
    result = wiki_escribir_sync(
        slug=slug, body=body, scope=scope, author=author, frontmatter=frontmatter,
    )
    # Si sync helper scheduleó fire-and-forget, garantizar que el test
    # vea el chunks_indexed final (no -1).
    if result["chunks_indexed"] == -1:
        from ..chunker import chunk_and_index as _ci
        from ..embed import embed_text
        n = await _ci(
            page_slug=slug, content=body, scope=scope,
            title=(frontmatter or {}).get("title", slug),
            embed_text_fn=embed_text,
        )
        result["chunks_indexed"] = n
    result["reindex_ms"] = int((_time.monotonic() - start) * 1000)
    return result
```

- [ ] **Step 5.4: Correr tests**

Run:
```bash
cd /opt/mcps/memoria && .venv/bin/pytest tests/test_wiki_tools.py -v -k escribir
```

Expected: `5 passed`.

- [ ] **Step 5.5: Registrar en `server.py`**

Append a `/opt/mcps/memoria/src/memoria_mcp/server.py`:

```python


@mcp.tool(name="wiki_escribir", description="Escribe nueva versión de página wiki (DB append-only + opcional archive filesystem + reindex).")
async def tool_wiki_escribir(
    slug: str,
    body: str,
    scope: str,
    author: str,
    frontmatter: dict | None = None,
) -> dict:
    _ensure_init()
    return await wiki.wiki_escribir(
        slug=slug, body=body, scope=scope, author=author, frontmatter=frontmatter,
    )
```

---

## Task 6: Tools `wiki_historial` y `wiki_export` (DB-only)

**Files:**
- Modify: `/opt/mcps/memoria/src/memoria_mcp/tools/wiki.py`
- Modify: `/opt/mcps/memoria/src/memoria_mcp/server.py`
- Modify: `/opt/mcps/memoria/tests/test_wiki_tools.py`

**Interfaces:**
- `wiki_historial_sync(slug, scope=None) -> list[dict]` — DB only. Devuelve `[{version, ts, author, scope, body_len, frontmatter, archive_present}]`.
- `wiki_export_sync(slug=None, scope=None) -> dict` — DB only. Bundle `{generated_at, pages: [{slug, scope, versions: [...]}]}`.

- [ ] **Step 6.1: Tests**

Append a `/opt/mcps/memoria/tests/test_wiki_tools.py`:

```python
def test_wiki_historial_returns_all_versions(seeded_db):
    result = wiki_historial_sync(slug="page-a")
    assert len(result) == 2
    assert [r["version"] for r in result] == [2, 1]
    assert all("body_len" in r for r in result)
    assert all("archive_present" in r for r in result)


def test_wiki_historial_filters_by_scope(seeded_db):
    result = wiki_historial_sync(slug="page-a", scope="designs")
    assert all(r["scope"] == "designs" for r in result)


def test_wiki_historial_empty_raises(seeded_db):
    with pytest.raises(LookupError, match="sin historial"):
        wiki_historial_sync(slug="nonexistent")


def test_wiki_export_single_page(seeded_db):
    result = wiki_export_sync(slug="page-a")
    assert len(result["pages"]) == 1
    page = result["pages"][0]
    assert page["slug"] == "page-a"
    assert len(page["versions"]) == 2
    assert page["versions"][0]["version"] == 2


def test_wiki_export_full_bundle(seeded_db):
    result = wiki_export_sync()
    slugs = sorted(p["slug"] for p in result["pages"])
    assert slugs == ["page-a", "page-b"]


def test_wiki_export_filters_by_scope(seeded_db):
    result = wiki_export_sync(scope="lessons")
    assert len(result["pages"]) == 1
    assert result["pages"][0]["slug"] == "page-b"
```

- [ ] **Step 6.2: Correr test — debe fallar**

Run:
```bash
cd /opt/mcps/memoria && .venv/bin/pytest tests/test_wiki_tools.py::test_wiki_historial_returns_all_versions -v
```

Expected: `ImportError`.

- [ ] **Step 6.3: Implementar `wiki_historial` y `wiki_export`**

Append a `/opt/mcps/memoria/src/memoria_mcp/tools/wiki.py`:

```python
def wiki_historial_sync(slug: str, scope: Optional[str] = None) -> list[dict]:
    if scope:
        rows = db.read_many(
            "SELECT version, ts, author, scope, body, frontmatter "
            "FROM mm_wiki_pages WHERE slug = %s AND scope = %s "
            "ORDER BY version DESC",
            (slug, scope),
        )
    else:
        rows = db.read_many(
            "SELECT version, ts, author, scope, body, frontmatter "
            "FROM mm_wiki_pages WHERE slug = %s ORDER BY version DESC",
            (slug,),
        )
    if not rows:
        raise LookupError(f"{slug} sin historial en DB")
    out = []
    for r in rows:
        ap = _archive_path(slug, r["scope"], r["version"])
        out.append({
            "version": r["version"],
            "ts": r["ts"].isoformat() if r["ts"] else None,
            "author": r["author"],
            "scope": r["scope"],
            "body_len": len(r["body"]),
            "frontmatter": _json.loads(r["frontmatter"]) if r["frontmatter"] else {},
            "archive_path": str(ap),
            "archive_present": ap.exists(),
        })
    return out


def wiki_export_sync(slug: Optional[str] = None, scope: Optional[str] = None) -> dict:
    where = []
    params: list = []
    if slug:
        where.append("slug = %s")
        params.append(slug)
    if scope:
        where.append("scope = %s")
        params.append(scope)
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""
    rows = db.read_many(
        f"SELECT slug, scope, version, body, frontmatter, author, ts "
        f"FROM mm_wiki_pages {where_sql} ORDER BY slug, scope, version",
        tuple(params),
    )
    by_key: dict[tuple[str, str], dict] = {}
    for r in rows:
        key = (r["slug"], r["scope"])
        if key not in by_key:
            by_key[key] = {
                "slug": r["slug"], "scope": r["scope"], "versions": [],
            }
        ap = _archive_path(r["slug"], r["scope"], r["version"])
        by_key[key]["versions"].append({
            "version": r["version"],
            "body": r["body"],
            "frontmatter": _json.loads(r["frontmatter"]) if r["frontmatter"] else {},
            "author": r["author"],
            "ts": r["ts"].isoformat() if r["ts"] else None,
            "archive_path": str(ap),
            "archive_present": ap.exists(),
        })
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "pages": list(by_key.values()),
    }


async def wiki_historial(slug: str, scope: Optional[str] = None) -> list[dict]:
    return wiki_historial_sync(slug=slug, scope=scope)


async def wiki_export(slug: Optional[str] = None, scope: Optional[str] = None) -> dict:
    return wiki_export_sync(slug=slug, scope=scope)
```

- [ ] **Step 6.4: Correr tests**

Run:
```bash
cd /opt/mcps/memoria && .venv/bin/pytest tests/test_wiki_tools.py -v -k "historial or export"
```

Expected: `6 passed`.

- [ ] **Step 6.5: Registrar en `server.py`**

Append a `/opt/mcps/memoria/src/memoria_mcp/server.py`:

```python


@mcp.tool(name="wiki_historial", description="Lista todas las versiones de una página (append-only DB).")
async def tool_wiki_historial(slug: str, scope: str | None = None) -> list[dict]:
    _ensure_init()
    return await wiki.wiki_historial(slug=slug, scope=scope)


@mcp.tool(name="wiki_export", description="Export bundle JSON (DB). Sin slug = todo el wiki.")
async def tool_wiki_export(slug: str | None = None, scope: str | None = None) -> dict:
    _ensure_init()
    return await wiki.wiki_export(slug=slug, scope=scope)
```

---

## Task 7: E2E test — los 5 tools en secuencia

**Files:**
- Create: `/opt/mcps/memoria/tests/test_wiki_e2e.py`

- [ ] **Step 7.1: Escribir el test**

Create `/opt/mcps/memoria/tests/test_wiki_e2e.py`:

```python
"""test_wiki_e2e.py — secuencia completa de los 5 tools wiki."""
from __future__ import annotations

import json as _json
from unittest.mock import patch

import pytest

from memoria_mcp import db
from memoria_mcp.tools.wiki import (
    wiki_listar_sync, wiki_leer_sync, wiki_escribir_sync,
    wiki_historial_sync, wiki_export_sync,
)


@pytest.fixture
def kb_tmp(tmp_path):
    db.DB_NAME = "mcp_memoria_test_e2e"
    db.init_schema()
    yield tmp_path
    with db._pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DROP TABLE IF EXISTS mm_wiki_pages")
            cur.execute("DROP TABLE IF EXISTS mm_entity_chunks")


def test_e2e_full_sequence_archive_on(kb_tmp, monkeypatch):
    monkeypatch.setenv("MCP_ARCHIVE_ON_WRITE", "1")
    import importlib, memoria_mcp.tools.wiki as wmod
    importlib.reload(wmod)

    with patch("memoria_mcp.tools.wiki.chunker") as mock_chunker, \
         patch("memoria_mcp.tools.wiki.paths") as mock_paths:
        mock_paths.wiki_archive_path.side_effect = (
            lambda s, sc, v: kb_tmp / "wiki_archive" / sc / f"{s}-v{v}.md"
        )
        mock_paths.wiki_archive_dir.side_effect = (
            lambda sc: kb_tmp / "wiki_archive" / sc
        )
        async def fake_chunk(page_slug, content, scope, title, embed_text_fn):
            return 2
        mock_chunker.chunk_and_index = fake_chunk

        # 1. Escribir v1
        r1 = wiki_escribir_sync(
            slug="e2e", body="# E2E v1\n\nFoo.", scope="designs",
            author="e2e", frontmatter={"title": "E2E Test"},
        )
        assert r1["version"] == 1
        assert r1["archived"] is True

        # 2. Leer v1 (específica)
        read1 = wiki_leer_sync(slug="e2e", version=1)
        assert "Foo." in read1["body"]

        # 3. Escribir v2
        r2 = wiki_escribir_sync(
            slug="e2e", body="# E2E v2\n\nBar.", scope="designs", author="e2e",
        )
        assert r2["version"] == 2

        # 4. Leer latest → debe ser v2
        latest = wiki_leer_sync(slug="e2e")
        assert latest["version"] == 2
        assert "Bar." in latest["body"]

        # 5. Historial → 2 versiones, orden DESC
        hist = wiki_historial_sync(slug="e2e")
        assert [h["version"] for h in hist] == [2, 1]
        assert all(h["archive_present"] for h in hist)

        # 6. Listar → debe aparecer
        listed = wiki_listar_sync(scope="designs")
        assert any(p["slug"] == "e2e" for p in listed)

        # 7. Export → bundle con 2 versiones
        bundle = wiki_export_sync(slug="e2e")
        assert len(bundle["pages"][0]["versions"]) == 2

    # 8. Verificar filesystem: 2 archivos archive, ambos existen, nombres inmutables
    a1 = kb_tmp / "wiki_archive" / "designs" / "e2e-v1.md"
    a2 = kb_tmp / "wiki_archive" / "designs" / "e2e-v2.md"
    assert a1.exists() and a2.exists()
    assert "version: 1" in a1.read_text()
    assert "version: 2" in a2.read_text()
    # Filename único: ningún archivo pisó al otro
    assert a1.read_text() != a2.read_text()


def test_e2e_archive_off_writes_nothing_to_fs(kb_tmp, monkeypatch):
    monkeypatch.setenv("MCP_ARCHIVE_ON_WRITE", "0")
    import importlib, memoria_mcp.tools.wiki as wmod
    importlib.reload(wmod)

    with patch("memoria_mcp.tools.wiki.chunker") as mock_chunker:
        async def fake_chunk(*a, **k):
            return 0
        mock_chunker.chunk_and_index = fake_chunk

        r = wiki_escribir_sync(
            slug="noarch", body="# x", scope="concepts", author="t",
        )
        assert r["archived"] is False
        assert r["archive_path"] is None

    assert not (kb_tmp / "wiki_archive").exists()
```

- [ ] **Step 7.2: Correr e2e**

Run:
```bash
cd /opt/mcps/memoria && .venv/bin/pytest tests/test_wiki_e2e.py -v
```

Expected: `2 passed`.

- [ ] **Step 7.3: Correr TODOS los tests wiki**

Run:
```bash
cd /opt/mcps/memoria && .venv/bin/pytest tests/ -v -k wiki
```

Expected: ~25 passed, 0 failed.

---

## Task 8: Docs — CHANGELOG + DESIGN-WIKI.md

**Files:**
- Modify: `/opt/mcps/memoria/CHANGELOG.md`
- Create: `/opt/mcps/memoria/docs/DESIGN-WIKI.md`

- [ ] **Step 8.1: CHANGELOG**

Append a `/opt/mcps/memoria/CHANGELOG.md`:

```markdown
## [0.2.0] — 2026-07-05 — Wiki Versionada (5 tools)

### Added
- 5 tools nuevos: `wiki_listar`, `wiki_leer`, `wiki_escribir`, `wiki_historial`, `wiki_export`.
- Tabla `mm_wiki_pages` con PK compuesta (slug, version), append-only, source of truth.
- Auto-archive filesystem opcional (env `MCP_ARCHIVE_ON_WRITE=1`, default ON):
  `<WORKSPACE>/wiki_archive/<scope>/<slug>-v<N>.md`. Filename inmutable por versión → cero race.
- Path helpers `wiki_archive_path(slug, scope, version)` y `wiki_archive_dir(scope)` con validación regex.
- Módulo `wiki_io.py` con `parse_frontmatter` / `render_with_frontmatter` (YAML).
- Reindex automático post-write vía `chunker.chunk_and_index()`.

### Arquitectura
- **DB es live**: `wiki_listar`, `wiki_leer`, `wiki_historial`, `wiki_export` leen SOLO de `mm_wiki_pages`.
- **Filesystem es backup**: el archive NO es leído por el live. Es write-only artefact.
- `wiki_archive/` NO está en `paths.ALLOWED_DIRS` → el chunker no re-ingiere archivos archive.

### Diferencias vs v1 (descartada)
- ❌ Sin `WikiLock` (filename único por versión → no race).
- ❌ Sin atomic tmp+rename (idempotencia por versión).
- ❌ Sin dual-write rollback semantics (DB-first, archive es side-effect opcional).

### Out of scope (futuro)
- Reconciliador multi-nodo.
- Embedding dedicado por página.
- Sync a otros mariadb remotos.
```

- [ ] **Step 8.2: DESIGN-WIKI.md secops-context**

Create `/opt/mcps/memoria/docs/DESIGN-WIKI.md`:

```markdown
# DESIGN-WIKI.md — Wiki Versionada mcp-memoria (secops deploy)

> **Versión:** 0.2.0 — 2026-07-05
> **Reemplaza:** `~/memorias_mcp/DESIGN-WIKI.md` (cloudops, paths inexistentes en secops).
> **Trazabilidad:** IDEA-98 (mop-mcp CANDIDATE) + auditoría secops 2026-07-05 + decisión Rodrigo 2026-07-05.

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
3. **Archive filename inmutable.** `<slug>-v<N>.md` (no `<slug>.md`) → cualquier versión se escribe UNA sola vez → sin race, sin lock, sin atomic rename.
4. **Archive opcional via env.** `MCP_ARCHIVE_ON_WRITE=0` desactiva el write filesystem (DB-only mode).
5. **kb/ legacy sigue su flujo.** Chunker lee `kb/<scope>/*.md` al startup, indexa en `mm_entity_chunks`. No se migra a `mm_wiki_pages` (es seed data).
6. **`wiki_archive/` NO en `ALLOWED_DIRS`.** El chunker NO debe re-ingerir archive files (causaría doble indexación).

## Path mapping

| Operación | Path |
|---|---|
| `wiki_escribir(slug, scope, ..., version=N)` | `mm_wiki_pages(slug, N, ...)` + `wiki_archive/<scope>/<slug>-v<N>.md` |
| `wiki_leer(slug, version=N)` | `mm_wiki_pages WHERE slug=? AND version=N` |
| `wiki_listar(scope)` | `SELECT slug, MAX(version) FROM mm_wiki_pages WHERE scope=?` |
| `wiki_historial(slug)` | `SELECT version, ts, author FROM mm_wiki_pages WHERE slug=? ORDER BY version DESC` |
| `wiki_export(slug)` | SELECT todas las versiones + bundle JSON |

## Acceptance criteria

- [x] 5 tools expuestas con contrato `wiki_escribir / leer / historial / listar / export`.
- [x] `mm_wiki_pages` append-only con PK compuesta.
- [x] Auto-reindex post-write (chunker existente).
- [x] Auto-archive opcional (env toggle).
- [x] Sin race conditions (archive filename único por versión).
- [x] Tests e2e verdes en `tests/test_wiki_e2e.py`.
- [x] KB legacy no afectado (sigue su flujo actual).

## Out of scope (futuro)

- Reconciliador multi-nodo.
- Editar .md en vim y commitear como nueva versión (sería un workflow git-style con round-trip; hoy es write-direct-from-MCP).
- Embedding semántico dedicado por página.
- Sync a mariadb remotos.
```

---

## Task 9: Verificación final — restart service + smoke test

- [ ] **Step 9.1: Correr TODOS los tests del package**

Run:
```bash
cd /opt/mcps/memoria && .venv/bin/pytest tests/ -v
```

Expected: tests previos (auth, search, grafo, bibliotecario, no_personal_leak) + nuevos wiki tests, todos pasan.

- [ ] **Step 9.2: Restart del servicio**

Run:
```bash
sudo systemctl restart mcp-memoria && sleep 2 && \
  sudo systemctl status mcp-memoria --no-pager | head -10
```

Expected: `Active: active (running)`.

- [ ] **Step 9.3: Smoke test via curl — los 5 tools**

Run (asumiendo `$TOKEN` está exportado):

```bash
# 1. wiki_listar (debería devolver [] porque ninguna página escrita via MCP aún)
curl -s -H "Authorization: Bearer $TOKEN" \
  http://127.0.0.1:9092/mcp/tools/call \
  -d '{"name":"wiki_listar","arguments":{}}' | jq 'length'

# 2. wiki_escribir — crear smoke test
curl -s -H "Authorization: Bearer $TOKEN" \
  http://127.0.0.1:9092/mcp/tools/call \
  -d '{"name":"wiki_escribir","arguments":{
    "slug":"smoke-test","body":"# Smoke\n\nTest desde curl.",
    "scope":"concepts","author":"smoke"
  }}' | jq

# 3. Verificar archive filesystem
ls -la /opt/mcp-memoria/snapshot/kb/wiki_archive/concepts/smoke-test-v1.md

# 4. wiki_leer (latest)
curl -s -H "Authorization: Bearer $TOKEN" \
  http://127.0.0.1:9092/mcp/tools/call \
  -d '{"name":"wiki_leer","arguments":{"slug":"smoke-test"}}' | jq

# 5. wiki_historial
curl -s -H "Authorization: Bearer $TOKEN" \
  http://127.0.0.1:9092/mcp/tools/call \
  -d '{"name":"wiki_historial","arguments":{"slug":"smoke-test"}}' | jq

# 6. wiki_export
curl -s -H "Authorization: Bearer $TOKEN" \
  http://127.0.0.1:9092/mcp/tools/call \
  -d '{"name":"wiki_export","arguments":{"slug":"smoke-test"}}' | jq '.pages[0].versions | length'

# 7. Escribir v2 → verificar que aparece v2 en archive (sin tocar v1)
curl -s -H "Authorization: Bearer $TOKEN" \
  http://127.0.0.1:9092/mcp/tools/call \
  -d '{"name":"wiki_escribir","arguments":{
    "slug":"smoke-test","body":"# Smoke v2\n\nOtra versión.",
    "scope":"concepts","author":"smoke"
  }}' | jq

ls /opt/mcp-memoria/snapshot/kb/wiki_archive/concepts/  # debe mostrar v1 y v2
```

Expected: cada curl devuelve JSON coherente; `ls` muestra `smoke-test-v1.md` y `smoke-test-v2.md` (ambos, sin pisarse).

- [ ] **Step 9.4: Verificar kag_buscar ve la nueva página**

```bash
curl -s -H "Authorization: Bearer $TOKEN" \
  http://127.0.0.1:9092/mcp/tools/call \
  -d '{"name":"kag_buscar","arguments":{"query":"smoke test desde curl"}}' | \
  jq '.[].page_slug' | head -3
```

Expected: `"smoke-test"` aparece.

- [ ] **Step 9.5: Cleanup**

```bash
rm -rf /opt/mcp-memoria/snapshot/kb/wiki_archive/concepts/smoke-test-*.md
sudo -u rodrigo mariadb -u mcp_memoria -p"$MCP_DB_PASS" mcp_memoria \
  -e "DELETE FROM mm_wiki_pages WHERE slug='smoke-test'; \
      DELETE FROM mm_entity_chunks WHERE page_slug='smoke-test';" 2>&1 | grep -v Warning
sudo systemctl restart mcp-memoria
```

- [ ] **Step 9.6: CHANGELOG final**

Append a `/opt/mcps/memoria/CHANGELOG.md`:

```markdown
### Deployed (2026-07-05)
- 5 tools wiki desplegados. 21 tools totales (16 previos + 5 nuevos).
- Smoke test verde via curl.
- Archive filesystem funcionando (v1, v2 coexisten sin pisarse).
- Sin regresiones en tools existentes.
```

---

## Task 10: Migration script — kb/ legacy → mm_wiki_pages

**Files:**
- Create: `/opt/mcps/memoria/scripts/migrate-kb-to-wiki.py`
- Create: `/opt/mcps/memoria/tests/test_migrate_kb_to_wiki.py`

**Goal:** Backfill único desde los 45+ `.md` en `kb/<scope>/*.md` a `mm_wiki_pages (slug, version=1, ...)`. Idempotente, dry-run por default.

**Interfaces:**
- Input: WORKSPACE_ROOT (env), el dir `kb/{concepts,designs,lessons,papers,reports}/*.md`.
- Output: INSERT en `mm_wiki_pages`. Log: `migrated=N, skipped=M, lowercased=K, failed=L`.
- Modos: `--dry-run` (no escribe, solo reporta) / `--apply` (escribe).
- Slug = filename sin `.md`, **lowercase forzado**. Si difiere del filename original, se loggea en `lowercased=K`.
- Author = `"legacy-migration"` (sin autor humano en los .md originales).
- Version siempre = 1.
- Si `(slug, 1)` ya existe, skip + log en `skipped=M`.

- [ ] **Step 10.1: Tests del script de migración**

Create `/opt/mcps/memoria/tests/test_migrate_kb_to_wiki.py`:

```python
"""test_migrate_kb_to_wiki.py — tests del script de migración kb/ legacy."""
from __future__ import annotations

import json as _json
import subprocess
import sys
from pathlib import Path

import pytest

from memoria_mcp import db


@pytest.fixture
def populated_kb(tmp_path):
    """KB temporal con archivos para migrar."""
    for scope in ("concepts", "designs", "lessons", "papers", "reports"):
        (tmp_path / scope).mkdir()
    # Caso 1: archivo normal lowercase
    (tmp_path / "designs" / "mi-design.md").write_text(
        "---\ntitle: Mi Diseño\n---\n# Mi Diseño\n\nBody."
    )
    # Caso 2: archivo UPPERCASE → debe forzar lowercase
    (tmp_path / "lessons" / "INDEPENDENCIA.md").write_text("# Independencia")
    # Caso 3: archivo con fecha prefix (slug ya lowercase)
    (tmp_path / "lessons" / "2026-06-07-foo.md").write_text("# Foo")
    # Caso 4: archivo en directorio raíz (fuera de scopes, debe skip)
    (tmp_path / "DESIGNS.md").write_text("# Index")
    # Caso 5: archivo en subdir no permitido
    (tmp_path / "lessons" / "private" / "secreto.md").write_text("# X")
    (tmp_path / "lessons" / "private").mkdir()
    (tmp_path / "lessons" / "private" / "secreto.md").write_text("# X")

    db.DB_NAME = "mcp_memoria_test_migrate"
    db.init_schema()

    yield tmp_path

    with db._pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DROP TABLE IF EXISTS mm_wiki_pages")
            cur.execute("DROP TABLE IF EXISTS mm_entity_chunks")


def _run_migration(kb_path: Path, *args: str) -> subprocess.CompletedProcess:
    """Ejecuta el script como subprocess para test e2e."""
    script = Path("/opt/mcps/memoria/scripts/migrate-kb-to-wiki.py")
    env = {
        **__import__("os").environ,
        "WORKSPACE_ROOT": str(kb_path),
        "MCP_DB_NAME": "mcp_memoria_test_migrate",
        "PYTHONPATH": "/opt/mcps/memoria/src",
    }
    return subprocess.run(
        [sys.executable, str(script), *args],
        capture_output=True, text=True, env=env, timeout=30,
    )


def test_migrate_dry_run_does_not_write(populated_kb):
    """--dry-run no debe escribir nada en la DB."""
    result = _run_migration(populated_kb, "--dry-run")
    assert result.returncode == 0
    assert "DRY-RUN" in result.stdout

    rows = db.read_many("SELECT COUNT(*) AS c FROM mm_wiki_pages")
    assert rows[0]["c"] == 0


def test_migrate_apply_inserts_with_version_1(populated_kb):
    """--apply inserta los archivos de los 5 scopes válidos, version=1."""
    result = _run_migration(populated_kb, "--apply")
    assert result.returncode == 0, f"stderr: {result.stderr}"

    rows = db.read_many(
        "SELECT slug, scope, version, author, frontmatter "
        "FROM mm_wiki_pages ORDER BY slug"
    )
    by_slug = {r["slug"]: r for r in rows}

    # 3 inserts: mi-design, independencia (lowercased), 2026-06-07-foo
    assert len(rows) == 3
    assert "mi-design" in by_slug
    assert "independencia" in by_slug
    assert "2026-06-07-foo" in by_slug

    for r in rows:
        assert r["version"] == 1
        assert r["author"] == "legacy-migration"

    # Frontmatter parseado
    assert _json.loads(by_slug["mi-design"]["frontmatter"]) == {"title": "Mi Diseño"}


def test_migrate_is_idempotent(populated_kb):
    """Segunda corrida debe skippear los ya migrados."""
    _run_migration(populated_kb, "--apply")
    result = _run_migration(populated_kb, "--apply")
    assert result.returncode == 0
    assert "skipped=3" in result.stdout
    rows = db.read_many("SELECT COUNT(*) AS c FROM mm_wiki_pages")
    assert rows[0]["c"] == 3  # no duplicados


def test_migrate_lowercases_uppercase_slugs(populated_kb):
    """INDEPENDENCIA.md → slug 'independencia', no 'INDEPENDENCIA'."""
    _run_migration(populated_kb, "--apply")
    row = db.read_one(
        "SELECT slug FROM mm_wiki_pages WHERE slug IN ('independencia', 'INDEPENDENCIA')"
    )
    assert row is not None
    assert row["slug"] == "independencia"


def test_migrate_skips_root_files(populated_kb):
    """DESIGNS.md (root, no en subdir scope) NO debe migrarse."""
    result = _run_migration(populated_kb, "--apply")
    assert "skipped root files: 1" in result.stdout or "root=1" in result.stdout
    rows = db.read_many("SELECT slug FROM mm_wiki_pages WHERE slug = 'DESIGNS'")
    assert len(rows) == 0
```

- [ ] **Step 10.2: Correr test — debe fallar**

Run:
```bash
cd /opt/mcps/memoria && .venv/bin/pytest tests/test_migrate_kb_to_wiki.py -v
```

Expected: `FAILED` con `FileNotFoundError` (script no existe).

- [ ] **Step 10.3: Implementar el script**

Create `/opt/mcps/memoria/scripts/migrate-kb-to-wiki.py`:

```python
#!/usr/bin/env python3
"""migrate-kb-to-wiki.py — Backfill único desde kb/ legacy a mm_wiki_pages.

Uso:
    python scripts/migrate-kb-to-wiki.py --dry-run   # default, no escribe
    python scripts/migrate-kb-to-wiki.py --apply      # INSERT en DB

Idempotente: si (slug, 1) ya existe, skip.
"""
from __future__ import annotations

import argparse
import json as _json
import logging
import os
import sys
from pathlib import Path

# Permitir import de memoria_mcp desde /opt/mcps/memoria/src
sys.path.insert(0, "/opt/mcps/memoria/src")

from memoria_mcp import db, paths as paths_mod  # noqa: E402
from memoria_mcp.wiki_io import parse_frontmatter  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("migrate-kb")

VALID_SCOPES = ("concepts", "designs", "lessons", "papers", "reports")


def _workspace_root() -> Path:
    env = os.environ.get("WORKSPACE_ROOT")
    if env:
        return Path(env)
    return paths_mod.WORKSPACE


def _scan_files(workspace: Path) -> tuple[list[Path], list[Path]]:
    """Devuelve (files_en_scopes, files_en_root) excluyendo subdirs no-scope."""
    in_scope: list[Path] = []
    in_root: list[Path] = []
    for scope in VALID_SCOPES:
        scope_dir = workspace / scope
        if not scope_dir.is_dir():
            continue
        for p in sorted(scope_dir.glob("*.md")):
            if p.is_file():
                in_scope.append(p)
    for p in sorted(workspace.glob("*.md")):
        if p.is_file():
            in_root.append(p)
    return in_scope, in_root


def _insert_page(slug: str, scope: str, body: str, frontmatter: dict) -> bool:
    """INSERT (slug, version=1) si no existe. Devuelve True si insertó."""
    existing = db.read_one(
        "SELECT version FROM mm_wiki_pages WHERE slug = %s AND version = 1",
        (slug,),
    )
    if existing:
        return False
    db.write_one(
        "INSERT INTO mm_wiki_pages (slug, version, body, frontmatter, author, scope) "
        "VALUES (%s, 1, %s, %s, %s, %s)",
        (
            slug,
            body,
            _json.dumps(frontmatter, ensure_ascii=False) if frontmatter else None,
            "legacy-migration",
            scope,
        ),
    )
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--dry-run", action="store_true", default=True,
                        help="Solo reportar, no escribir (default).")
    group.add_argument("--apply", action="store_true",
                        help="Escribir INSERTs en mm_wiki_pages.")
    args = parser.parse_args()
    apply = args.apply

    workspace = _workspace_root()
    log.info("workspace_root=%s apply=%s", workspace, apply)

    in_scope, in_root = _scan_files(workspace)
    log.info("found in_scope=%d root=%d (skipped)", len(in_scope), len(in_root))

    counts = {"migrated": 0, "skipped": 0, "lowercased": 0, "failed": 0, "root": len(in_root)}

    for path in in_scope:
        scope = path.parent.name
        if scope not in VALID_SCOPES:
            counts["failed"] += 1
            continue
        original_slug = path.stem
        slug = original_slug.lower()
        if slug != original_slug:
            counts["lowercased"] += 1
            log.info("lowercased slug: %s → %s", original_slug, slug)

        try:
            text = path.read_text(encoding="utf-8")
            frontmatter, body = parse_frontmatter(text)
        except Exception as e:
            log.error("read_failed slug=%s err=%s", slug, e)
            counts["failed"] += 1
            continue

        if apply:
            try:
                inserted = _insert_page(slug, scope, body, frontmatter)
                if inserted:
                    counts["migrated"] += 1
                else:
                    counts["skipped"] += 1
            except Exception as e:
                log.error("insert_failed slug=%s err=%s", slug, e)
                counts["failed"] += 1
        else:
            counts["migrated"] += 1
            log.info("[DRY-RUN] would insert slug=%s scope=%s", slug, scope)

    # Resumen final
    summary = (
        f"summary: migrated={counts['migrated']} skipped={counts['skipped']} "
        f"lowercased={counts['lowercased']} failed={counts['failed']} root={counts['root']}"
    )
    if apply:
        log.info(summary)
    else:
        log.info(f"[DRY-RUN] {summary}")
    print(summary)

    return 0 if counts["failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
```

Make executable:
```bash
chmod +x /opt/mcps/memoria/scripts/migrate-kb-to-wiki.py
```

- [ ] **Step 10.4: Correr test — debe pasar**

Run:
```bash
cd /opt/mcps/memoria && .venv/bin/pytest tests/test_migrate_kb_to_wiki.py -v
```

Expected: `5 passed`.

- [ ] **Step 10.5: Smoke test dry-run contra el kb/ real**

Run:
```bash
cd /opt/mcps/memoria && \
  WORKSPACE_ROOT=/opt/mcp-memoria/snapshot/kb \
  MCP_DB_NAME=mcp_memoria \
  PYTHONPATH=/opt/mcps/memoria/src \
  .venv/bin/python scripts/migrate-kb-to-wiki.py --dry-run
```

Expected: log de DRY-RUN con conteo de archivos en cada scope + summary.

- [ ] **Step 10.6: Ejecutar migrate real**

Run:
```bash
cd /opt/mcps/memoria && \
  WORKSPACE_ROOT=/opt/mcp-memoria/snapshot/kb \
  MCP_DB_NAME=mcp_memoria \
  PYTHONPATH=/opt/mcps/memoria/src \
  .venv/bin/python scripts/migrate-kb-to-wiki.py --apply
```

Expected: summary `migrated=N skipped=0 lowercased=K failed=0 root=R`.

Verificar count:
```bash
sudo -u rodrigo mariadb -u mcp_memoria -p"$MCP_DB_PASS" mcp_memoria \
  -e "SELECT COUNT(*) AS total, COUNT(DISTINCT scope) AS scopes FROM mm_wiki_pages;" 2>&1 | grep -v Warning
```

Expected: `total = N` (donde N = archivos en scopes, no incluye root) + scopes cubiertos.

- [ ] **Step 10.7: Verificar que `kag_buscar` y los nuevos tools ven las páginas migradas**

Run:
```bash
# kag_buscar sobre un título conocido
curl -s -H "Authorization: Bearer $TOKEN" \
  http://127.0.0.1:9092/mcp/tools/call \
  -d '{"name":"kag_buscar","arguments":{"query":"subagent supervisor pattern"}}' | \
  jq '.[0:3] | .[].page_slug'

# wiki_listar (pre-deploy, no existirán los CRUD tools aún — correr después de Tasks 4-7)
```

Expected: slugs como `subagent-supervisor-pattern` aparecen en los resultados.

---

## Self-Review

### 1. Spec coverage (IDEA-98 acceptance criteria)

| IDEA-98 criterion | Task |
|---|---|
| 5 tools con contrato omni-mcp | Tasks 4, 5, 6 |
| Versionado append-only (PK slug+version) | Task 1 |
| Auto-chunk post-write | Task 5 (reuse chunker existente) |
| Búsqueda full-text | Pre-existente (verificado en Task 9.4) |
| Test e2e verde | Task 7 |
| Doc DESIGN-WIKI.md actualizado | Task 8 |

### 2. Placeholder scan

- ❌ Sin "TBD" / "TODO" — todas las funciones tienen cuerpo.
- ❌ Sin "Add error handling" — ValueError, LookupError, TimeoutError explícitos donde corresponde.
- ❌ Sin "Similar to Task N" — cada step tiene código propio.
- ✅ Comandos exactos con expected output.

### 3. Type consistency

| Nombre | Definido en | Usado en |
|---|---|---|
| `wiki_archive_path(slug, scope, version) -> Path` | Task 2 | Tasks 4, 5, 6, 7 |
| `wiki_archive_dir(scope) -> Path` | Task 2 | Task 5 |
| `parse_frontmatter(text) -> (dict, str)` | Task 3 | Task 5 |
| `render_with_frontmatter(fm, body) -> str` | Task 3 | Task 5 |
| `wiki_listar_sync(scope, limit) -> list[dict]` | Task 4 | Task 7 |
| `wiki_leer_sync(slug, version, scope) -> dict` | Task 4 | Task 7 |
| `wiki_escribir_sync(slug, body, scope, author, frontmatter) -> dict` | Task 5 | Task 7 |
| `wiki_historial_sync(slug, scope) -> list[dict]` | Task 6 | Task 7 |
| `wiki_export_sync(slug, scope) -> dict` | Task 6 | Task 7 |

Todos consistentes.

### 4. Cambios vs v1

- ❌ Task 3 (WikiLock) eliminado.
- ❌ Lógica atómica tmp+rename eliminada.
- ❌ Dual-write rollback semantics eliminada.
- ✅ `wiki_escribir` pasó de ~90 líneas (sync+async+lock+atomic) a ~50 líneas (sync+async simple).
- ✅ Plan pasó de 10 tasks a 9 tasks.
- ✅ Tests reducidos en complejidad pero misma cobertura.

---

## Execution Handoff

Plan v2 completo en `/opt/mcps/memoria/docs/superpowers/plans/2026-07-05-wiki-versionada-mcp-memoria.md`.

**Cambios clave vs v1:**
1. **No más `WikiLock`** — filename único por versión hace el lock innecesario.
2. **No más atomic write** — `v<N>.md` se escribe una sola vez, no se pisa.
3. **`wiki_leer`/`wiki_listar`/`wiki_historial` leen SOLO de DB** — el filesystem no es hot path.
4. **Archive es opcional via env** — `MCP_ARCHIVE_ON_WRITE=0` para modo DB-only.

**¿Cómo ejecutamos?**
1. **Subagent-Driven** (recomendado) — subagente fresco por task, reviso entre tasks.
2. **Inline Execution** — ejecuto en esta sesión con checkpoints cada 2-3 tasks.
3. **Manual** — vos lo corrés (código completo + tests + comandos listos).

¿Cuál preferís?