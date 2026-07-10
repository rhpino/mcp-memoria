"""test_migrate_kb_to_wiki.py — tests del script de migración kb/ legacy."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from memoria_mcp import db


@pytest.fixture
def populated_kb(tmp_path):
    """KB temporal con archivos para migrar (varios casos)."""
    for scope in ("concepts", "designs", "lessons", "papers", "reports"):
        (tmp_path / scope).mkdir()
    # Caso normal lowercase con frontmatter
    (tmp_path / "designs" / "mi-design.md").write_text(
        "---\ntitle: Mi Diseño\n---\n# Mi Diseño\n\nBody."
    )
    # UPPERCASE → debe forzar lowercase
    (tmp_path / "lessons" / "INDEPENDENCIA.md").write_text("# Independencia")
    # Fecha prefix (slug ya lowercase)
    (tmp_path / "lessons" / "2026-06-07-foo.md").write_text("# Foo")
    # Archivo en root → debe skippear
    (tmp_path / "DESIGNS.md").write_text("# Index")
    # Subdir no permitido (privado dentro de lessons) → debe skippear
    (tmp_path / "lessons" / "private").mkdir()
    (tmp_path / "lessons" / "private" / "secreto.md").write_text("# X")

    db.DB_NAME = "mcp_memoria_test"
    db.init_schema()

    yield tmp_path

    with db.acquire() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM mm_wiki_pages WHERE author = 'legacy-migration'")


def _run_migration(kb_path: Path, *args: str) -> subprocess.CompletedProcess:
    script = Path("/opt/mcps/memoria/scripts/migrate-kb-to-wiki.py")
    env = {
        **os.environ,
        "WORKSPACE_ROOT": str(kb_path),
        "MCP_DB_NAME": "mcp_memoria_test",
        "MCP_DB_USER": os.environ.get("MCP_DB_USER", "mcp_memoria"),
        "MCP_DB_PASS": os.environ.get("MCP_DB_PASS", ""),
        "MCP_DB_HOST": os.environ.get("MCP_DB_HOST", "127.0.0.1"),
        "MCP_DB_PORT": os.environ.get("MCP_DB_PORT", "3306"),
        "PYTHONPATH": "/opt/mcps/memoria/src",
    }
    return subprocess.run(
        [sys.executable, str(script), *args],
        capture_output=True, text=True, env=env, timeout=30,
    )


def test_migrate_dry_run_does_not_write(populated_kb):
    result = _run_migration(populated_kb, "--dry-run")
    assert result.returncode == 0, f"stderr: {result.stderr}"
    assert "DRY-RUN" in result.stdout

    rows = db.read_many(
        "SELECT COUNT(*) AS c FROM mm_wiki_pages WHERE author = 'legacy-migration'"
    )
    assert rows[0]["c"] == 0


def test_migrate_apply_inserts_valid_files(populated_kb):
    result = _run_migration(populated_kb, "--apply")
    assert result.returncode == 0, f"stderr: {result.stderr}"

    rows = db.read_many(
        "SELECT slug, scope, version, author, frontmatter "
        "FROM mm_wiki_pages WHERE author = 'legacy-migration' ORDER BY slug"
    )
    by_slug = {r["slug"]: r for r in rows}

    # Solo archivos en scopes válidos, casing preservado (3 archivos: 2 lowercase + 1 UPPERCASE).
    assert len(rows) == 3
    assert "mi-design" in by_slug
    assert "INDEPENDENCIA" in by_slug  # casing original
    assert "2026-06-07-foo" in by_slug

    for r in rows:
        assert r["version"] == 1
        assert r["author"] == "legacy-migration"

    # Frontmatter parseado
    import json as _json
    assert _json.loads(by_slug["mi-design"]["frontmatter"]) == {"title": "Mi Diseño"}


def test_migrate_is_idempotent(populated_kb):
    """Segunda corrida → reporta skipped sin duplicar filas."""
    r1 = _run_migration(populated_kb, "--apply")
    assert r1.returncode == 0
    r2 = _run_migration(populated_kb, "--apply")
    assert r2.returncode == 0
    assert "skipped=3" in r2.stdout, f"stdout: {r2.stdout}"

    rows = db.read_many(
        "SELECT COUNT(*) AS c FROM mm_wiki_pages WHERE author = 'legacy-migration'"
    )
    assert rows[0]["c"] == 3  # no duplicados


def test_migrate_preserves_casing(populated_kb):
    """Migration preserva casing original del filename (no lowercase)."""
    _run_migration(populated_kb, "--apply")
    # INDEPENDENCIA.md debe quedar como slug 'INDEPENDENCIA' (no lowercase).
    upper = db.read_many(
        "SELECT slug FROM mm_wiki_pages WHERE slug = BINARY 'INDEPENDENCIA'"
    )
    assert len(upper) == 1
    # No debe existir slug lowercase 'independencia'
    lower = db.read_many(
        "SELECT slug FROM mm_wiki_pages WHERE slug = BINARY 'independencia'"
    )
    assert len(lower) == 0


def test_migrate_skips_root_files(populated_kb):
    """DESIGNS.md en root NO debe insertarse."""
    _run_migration(populated_kb, "--apply")
    rows = db.read_many("SELECT slug FROM mm_wiki_pages WHERE slug = 'DESIGNS'")
    assert len(rows) == 0


def test_migrate_output_contains_summary(populated_kb):
    result = _run_migration(populated_kb, "--apply")
    assert "migrated=" in result.stdout
    assert "skipped=" in result.stdout
    assert "lowercased=" in result.stdout
    assert "failed=" in result.stdout
