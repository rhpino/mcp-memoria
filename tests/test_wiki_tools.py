"""test_wiki_tools.py — tests de los 5 tools wiki."""
from __future__ import annotations

import json as _json
from unittest.mock import patch

import pytest

from memoria_mcp import db, paths
from memoria_mcp.tools.wiki import (
    wiki_listar_sync,
    wiki_leer_sync,
    wiki_escribir_sync,
    wiki_historial_sync,
    wiki_export_sync,
    wiki_help_sync,
)


@pytest.fixture
def seeded_db():
    """Sembrado mínimo: 2 slugs, uno con 2 versiones."""
    db.DB_NAME = "mcp_memoria_test"
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
    yield
    with db.acquire() as conn:
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
    assert page["version_actual"] == 2
    assert page["archive_path"].endswith("page-a-v2.md")
    assert "archive_present" in page


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


# ── wiki_escribir (Task 5) ──────────────────────────────────────────

@pytest.fixture
def isolated_test_db():
    """Usa mcp_memoria_test, dropea mm_wiki_pages al final.

    CRÍTICO: estos tests insertan en DB; deben usar DB de test, no prod.
    """
    db.DB_NAME = "mcp_memoria_test"
    db.init_schema()
    yield
    with db.acquire() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM mm_wiki_pages WHERE slug LIKE 'wiki-test-%' "
                        "OR slug IN ('nueva', 'dup', 'noarch')")
            cur.execute("DROP TABLE IF EXISTS mm_wiki_pages")


def test_wiki_escribir_creates_v1_and_archive(tmp_path, monkeypatch, isolated_test_db):
    """archive ON: escribe DB + archivo + reindex."""
    monkeypatch.setenv("MCP_ARCHIVE_ON_WRITE", "1")
    import importlib
    import memoria_mcp.tools.wiki as wmod
    importlib.reload(wmod)
    from memoria_mcp.tools.wiki import wiki_escribir_sync as _w

    with patch("memoria_mcp.tools.wiki.chunker") as mock_chunker, \
         patch("memoria_mcp.tools.wiki.paths") as mock_paths:
        mock_paths.wiki_archive_path.side_effect = (
            lambda s, sc, v: tmp_path / "wiki_archive" / sc / f"{s}-v{v}.md"
        )
        mock_paths.wiki_archive_dir.side_effect = (
            lambda sc: tmp_path / "wiki_archive" / sc
        )
        mock_paths._validate_slug_scope = paths._validate_slug_scope  # real fn
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


def test_wiki_escribir_appends_v2(tmp_path, monkeypatch, isolated_test_db):
    """Segunda escritura genera v2 (no pisa v1)."""
    monkeypatch.setenv("MCP_ARCHIVE_ON_WRITE", "1")
    import importlib
    import memoria_mcp.tools.wiki as wmod
    importlib.reload(wmod)
    from memoria_mcp.tools.wiki import wiki_escribir_sync as _w

    db.write_one(
        "INSERT INTO mm_wiki_pages (slug, version, body, author, scope) "
        "VALUES (%s, 1, %s, %s, %s)",
        ("dup", "# v1", "test", "lessons"),
    )

    with patch("memoria_mcp.tools.wiki.chunker") as mock_chunker, \
         patch("memoria_mcp.tools.wiki.paths") as mock_paths:
        mock_paths.wiki_archive_path.side_effect = (
            lambda s, sc, v: tmp_path / "wiki_archive" / sc / f"{s}-v{v}.md"
        )
        mock_paths.wiki_archive_dir.side_effect = (
            lambda sc: tmp_path / "wiki_archive" / sc
        )
        mock_paths._validate_slug_scope = paths._validate_slug_scope
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


def test_wiki_escribir_archive_disabled(tmp_path, monkeypatch, isolated_test_db):
    """archive OFF: escribe DB + reindex, NO toca filesystem."""
    monkeypatch.setenv("MCP_ARCHIVE_ON_WRITE", "0")
    import importlib
    import memoria_mcp.tools.wiki as wmod
    importlib.reload(wmod)
    from memoria_mcp.tools.wiki import wiki_escribir_sync as _w

    with patch("memoria_mcp.tools.wiki.chunker") as mock_chunker, \
         patch("memoria_mcp.tools.wiki.paths") as mock_paths:
        mock_paths._validate_slug_scope = paths._validate_slug_scope
        async def fake_chunk(*a, **k):
            return 0
        mock_chunker.chunk_and_index = fake_chunk
        result = _w(slug="noarch", body="x", scope="concepts", author="t")

    assert result["archived"] is False
    assert result.get("archive_path") is None
    assert not (tmp_path / "wiki_archive").exists()


def test_wiki_escribir_rejects_invalid_slug(isolated_test_db):
    """Slug con caracteres no permitidos → ValueError antes de tocar DB."""
    from memoria_mcp.tools.wiki import wiki_escribir_sync as _w
    with pytest.raises(ValueError, match="slug inválido"):
        _w(slug="../escape", body="x", scope="designs", author="t")
    # Verificar que NO se insertó nada en DB
    rows = db.read_many("SELECT slug FROM mm_wiki_pages")
    assert not any(r["slug"] == "../escape" for r in rows)


def test_wiki_escribir_rejects_invalid_scope(isolated_test_db):
    from memoria_mcp.tools.wiki import wiki_escribir_sync as _w
    with pytest.raises(ValueError, match="scope inválido"):
        _w(slug="ok", body="x", scope="not-real", author="t")


# ── wiki_historial + wiki_export (Task 6) ──────────────────────────

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


# ── wiki_help (entry point) ────────────────────────────────────────

def test_wiki_help_returns_documented_shape(seeded_db):
    """wiki_help_sync debe devolver shape completo para onboarding."""
    help_data = wiki_help_sync()

    assert "welcome" in help_data
    assert "mcp-memoria" in help_data["welcome"]

    # Tools dict cubre los 5 wiki_* (+ wiki_help)
    assert "tools" in help_data
    tool_names = set(help_data["tools"].keys())
    assert {"wiki_help", "wiki_listar", "wiki_leer", "wiki_escribir",
            "wiki_historial", "wiki_export"}.issubset(tool_names)

    # Scopes válidos
    for s in ("concepts", "designs", "lessons", "papers", "reports"):
        assert s in help_data["scopes"]

    # Starter pages curadas
    assert "starter_pages" in help_data
    assert len(help_data["starter_pages"]) >= 3
    for p in help_data["starter_pages"]:
        assert "slug" in p and "scope" in p and "topic" in p

    # Discovery tips
    assert "discovery_tips" in help_data
    assert "search_semantic" in help_data["discovery_tips"]
    assert "kag_buscar" in help_data["discovery_tips"]["search_semantic"]

    # Stats
    assert "by_scope_stats" in help_data
    assert "total_rows_in_db" in help_data
    assert help_data["total_rows_in_db"] == 3  # page-a v1+v2 + page-b v1

    # Shared module reference
    assert "shared_module_for_tests" in help_data
    assert "mcp_test_isolation" in help_data["shared_module_for_tests"]

    # Env vars
    assert "env_vars" in help_data
    assert "MCP_ARCHIVE_ON_WRITE" in help_data["env_vars"]


def test_wiki_help_self_references_entry_point(seeded_db):
    """wiki_help se autodescribe como entry point."""
    help_data = wiki_help_sync()
    assert help_data["your_entry_point"] == "wiki_help() (esta función)"
    assert "wiki_help" in help_data["tools"]
    assert "Esta" in help_data["tools"]["wiki_help"]


def test_wiki_help_by_scope_counts_match_db(seeded_db):
    """by_scope_stats debe reflejar exactamente el contenido de la DB."""
    help_data = wiki_help_sync()
    by_scope = {x["scope"]: x for x in help_data["by_scope_stats"]}
    assert by_scope["designs"]["pages"] == 1   # page-a
    assert by_scope["designs"]["versions"] == 2  # v1 + v2
    assert by_scope["lessons"]["pages"] == 1   # page-b
    assert by_scope["lessons"]["versions"] == 1