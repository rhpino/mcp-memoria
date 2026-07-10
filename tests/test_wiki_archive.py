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
        paths.wiki_archive_path("", "concepts", 1)
    with pytest.raises(ValueError, match="slug inválido"):
        paths.wiki_archive_path("a/b", "concepts", 1)
    with pytest.raises(ValueError, match="slug inválido"):
        paths.wiki_archive_path(".dotstart", "concepts", 1)  # debe empezar con alfanum


def test_wiki_archive_path_accepts_uppercase():
    """UPPERCASE válido (legacy kb/ tiene CHG-*, MOP-*, RCA-*, etc.)."""
    p = paths.wiki_archive_path("INDEPENDENCIA", "lessons", 1)
    assert p.name == "INDEPENDENCIA-v1.md"
    p2 = paths.wiki_archive_path("CHG-INCIDENTE-FIX-001", "papers", 3)
    assert p2.name == "CHG-INCIDENTE-FIX-001-v3.md"


def test_wiki_archive_path_rejects_invalid_scope():
    with pytest.raises(ValueError, match="scope inválido"):
        paths.wiki_archive_path("ok", "../escape", 1)
    with pytest.raises(ValueError, match="scope inválido"):
        paths.wiki_archive_path("ok", "not-a-scope", 1)


def test_wiki_archive_path_rejects_invalid_version():
    with pytest.raises(ValueError, match="version inválida"):
        paths.wiki_archive_path("ok", "designs", 0)
    with pytest.raises(ValueError, match="version inválida"):
        paths.wiki_archive_path("ok", "designs", -1)
    with pytest.raises(ValueError, match="version inválida"):
        paths.wiki_archive_path("ok", "designs", "1")


def test_wiki_archive_dir_per_scope():
    d = paths.wiki_archive_dir("lessons")
    assert d == paths.WORKSPACE / "wiki_archive" / "lessons"


def test_wiki_archive_dir_rejects_invalid_scope():
    with pytest.raises(ValueError, match="scope inválido"):
        paths.wiki_archive_dir("not-a-scope")