from __future__ import annotations

from memoria_mcp import db


def test_count_stale_embedding_chunks(isolate_test_db):
    from memoria_mcp import embed_admin

    db.init_schema()
    db.write_one("DELETE FROM mm_entity_chunks WHERE page_slug = %s", ("test/stale",))
    db.write_one(
        "INSERT INTO mm_entity_chunks "
        "(page_slug, chunk_index, heading, chunk_text, entities_referenced, word_count, embedding, scope, "
        "embedding_provider, embedding_model, embedding_dim) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        ("test/stale", 0, "h", "body", "[]", 1, b"1234", "decisions", "fastembed", "old", 384),
    )
    try:
        assert embed_admin.count_stale_chunks("vertex", "text-embedding-004", 384) >= 1
    finally:
        db.write_one("DELETE FROM mm_entity_chunks WHERE page_slug = %s", ("test/stale",))
