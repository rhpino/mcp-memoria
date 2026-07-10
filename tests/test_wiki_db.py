"""test_wiki_db.py — verifica que init_schema() crea mm_wiki_pages."""
from __future__ import annotations

import pytest

from memoria_mcp import db


pytestmark = pytest.mark.db


@pytest.fixture
def fresh_db():
    """Crea schema en DB de test (mcp_memoria_test) y limpia al final."""
    db.DB_NAME = "mcp_memoria_test"
    db.init_schema()
    yield
    with db.acquire() as conn:
        with conn.cursor() as cur:
            cur.execute("DROP TABLE IF EXISTS mm_wiki_pages")
            cur.execute("DROP TABLE IF EXISTS mm_entity_chunks")
            cur.execute("DROP TABLE IF EXISTS mm_relations")
            cur.execute("DROP TABLE IF EXISTS mm_entities")
            cur.execute("DROP TABLE IF EXISTS mm_search_feedback")
            cur.execute("DROP TABLE IF EXISTS mm_search_log")
            cur.execute("DROP TABLE IF EXISTS mm_conflict_queue")


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
    # MariaDB reporta JSON como alias de LONGTEXT en information_schema
    # (mismo comportamiento que mm_entities.attributes — confirmado por schema SQL).
    assert cols["frontmatter"] in ("json", "longtext")
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
