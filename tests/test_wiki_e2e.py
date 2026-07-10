"""test_wiki_e2e.py — secuencia completa de los 5 tools wiki."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from memoria_mcp import db, paths
from memoria_mcp.tools.wiki import (
    wiki_listar_sync, wiki_leer_sync, wiki_escribir_sync,
    wiki_historial_sync, wiki_export_sync,
)


@pytest.fixture
def kb_tmp(tmp_path):
    """KB temporal vacía + DB de test."""
    for d in ("concepts", "designs", "lessons", "papers", "reports"):
        (tmp_path / d).mkdir()
    db.DB_NAME = "mcp_memoria_test"
    db.init_schema()
    yield tmp_path
    with db.acquire() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM mm_wiki_pages WHERE slug = 'e2e' "
                        "OR slug = 'noarch'")
            cur.execute("DROP TABLE IF EXISTS mm_wiki_pages")


def test_e2e_full_sequence_archive_on(kb_tmp, monkeypatch):
    monkeypatch.setenv("MCP_ARCHIVE_ON_WRITE", "1")
    import importlib
    import memoria_mcp.tools.wiki as wmod
    importlib.reload(wmod)

    with patch("memoria_mcp.tools.wiki.chunker") as mock_chunker, \
         patch("memoria_mcp.tools.wiki.paths") as mock_paths:
        mock_paths.wiki_archive_path.side_effect = (
            lambda s, sc, v: kb_tmp / "wiki_archive" / sc / f"{s}-v{v}.md"
        )
        mock_paths.wiki_archive_dir.side_effect = (
            lambda sc: kb_tmp / "wiki_archive" / sc
        )
        mock_paths._validate_slug_scope = paths._validate_slug_scope

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

        # 2. Leer v1 específica
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

        # 7. Export → bundle con 2 versiones DESC
        bundle = wiki_export_sync(slug="e2e")
        assert len(bundle["pages"][0]["versions"]) == 2
        assert bundle["pages"][0]["versions"][0]["version"] == 2

    # 8. Verificar filesystem: 2 archivos archive, ambos existen, nombres inmutables
    a1 = kb_tmp / "wiki_archive" / "designs" / "e2e-v1.md"
    a2 = kb_tmp / "wiki_archive" / "designs" / "e2e-v2.md"
    assert a1.exists() and a2.exists()
    assert "version: 1" in a1.read_text()
    assert "version: 2" in a2.read_text()
    assert a1.read_text() != a2.read_text()  # no se pisaron


def test_e2e_archive_off_writes_nothing_to_fs(kb_tmp, monkeypatch):
    monkeypatch.setenv("MCP_ARCHIVE_ON_WRITE", "0")
    import importlib
    import memoria_mcp.tools.wiki as wmod
    importlib.reload(wmod)

    with patch("memoria_mcp.tools.wiki.chunker") as mock_chunker, \
         patch("memoria_mcp.tools.wiki.paths") as mock_paths:
        mock_paths._validate_slug_scope = paths._validate_slug_scope

        async def fake_chunk(*a, **k):
            return 0
        mock_chunker.chunk_and_index = fake_chunk

        r = wiki_escribir_sync(
            slug="noarch", body="# x", scope="concepts", author="t",
        )
        assert r["archived"] is False
        assert r["archive_path"] is None

    # No se creó directorio archive
    assert not (kb_tmp / "wiki_archive").exists()

    # Pero la fila SÍ quedó en DB
    row = db.read_one("SELECT slug, version FROM mm_wiki_pages WHERE slug = 'noarch'")
    assert row is not None
    assert row["version"] == 1