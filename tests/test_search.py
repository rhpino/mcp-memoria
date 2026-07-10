"""tests/test_search.py — Tests para search.py (cosine + keyword + RRF)."""
from __future__ import annotations

import time

import numpy as np
import pytest

from memoria_mcp import search, db


# ── Session-scoped seed: una sola vez por sesión pytest ────────────
@pytest.fixture(scope="session")
def seed_session():
    """Inserta fixtures una vez. ON DUPLICATE KEY UPDATE → idempotente."""
    fixtures = [
        {
            "page_slug": "decisions/test-search-1",
            "chunk_index": 0,
            "heading": "Test Decision Search 1",
            "chunk_text": "This is about MariaDB and KAG knowledge graphs.",
            "entities_referenced": '[{"id": "kag", "name": "KAG"}, {"id": "mariadb", "name": "MariaDB"}]',
            "word_count": 9,
            "scope": "decisions",
            "embedding": np.array([1.0, 0.0, 0.0] + [0.0] * 381, dtype=np.float32).tobytes(),
        },
        {
            "page_slug": "decisions/test-search-2",
            "chunk_index": 0,
            "heading": "Test Decision Search 2",
            "chunk_text": "Plain text about embeddings and cosine similarity.",
            "entities_referenced": "[]",
            "word_count": 7,
            "scope": "decisions",
            "embedding": np.array([0.0, 1.0, 0.0] + [0.0] * 381, dtype=np.float32).tobytes(),
        },
        {
            "page_slug": "lessons/test-search-1",
            "chunk_index": 0,
            "heading": "Test Lesson Search",
            "chunk_text": "Lesson about MariaDB KAG with auto-chunk and RRF.",
            "entities_referenced": '[{"id": "kag", "name": "KAG"}]',
            "word_count": 9,
            "scope": "lessons",
            "embedding": np.array([0.7, 0.7, 0.0] + [0.0] * 381, dtype=np.float32).tobytes(),
        },
    ]
    for f in fixtures:
        # ON DUPLICATE KEY UPDATE: si ya existe, actualiza
        db.write_one(
            "INSERT INTO mm_entity_chunks "
            "(page_slug, chunk_index, heading, chunk_text, entities_referenced, word_count, embedding, scope) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s) "
            "ON DUPLICATE KEY UPDATE heading=VALUES(heading), chunk_text=VALUES(chunk_text), "
            "entities_referenced=VALUES(entities_referenced), word_count=VALUES(word_count), "
            "embedding=VALUES(embedding), scope=VALUES(scope)",
            (
                f["page_slug"], f["chunk_index"], f["heading"],
                f["chunk_text"], f["entities_referenced"], f["word_count"],
                f["embedding"], f["scope"],
            ),
        )
    yield
    # Cleanup: borrar fixtures al final de sesión
    db.write_one(
        "DELETE FROM mm_entity_chunks WHERE page_slug IN (%s, %s, %s)",
        ("decisions/test-search-1", "decisions/test-search-2", "lessons/test-search-1"),
    )


@pytest.fixture
def seeded_db(seed_session):
    """Cada test usa la sesión seed (idempotente)."""
    yield


def test_cosine_search_returns_sorted_results(seeded_db):
    q = np.array([1.0, 0.0, 0.0] + [0.0] * 381, dtype=np.float32)
    results = search.cosine_search(q, scope="decisions", limit=10)
    assert len(results) >= 1
    assert results[0].page_slug == "decisions/test-search-1"
    assert results[0].cosine == pytest.approx(1.0, abs=0.01)


def test_cosine_search_keyword_boost(seeded_db):
    q = np.array([0.0, 1.0, 0.0] + [0.0] * 381, dtype=np.float32)
    r2 = search.cosine_search(q, scope="decisions", limit=10,
                              keyword_boost_enabled=True, query_text="embeddings")
    assert r2[0].keyword_boost > 0
    assert "embeddings" in r2[0].chunk_text.lower()


def test_rrf_fuse_combines_rankings():
    from memoria_mcp.search import SearchResult

    r1 = SearchResult(chunk_id=1, page_slug="a", scope=None, chunk_index=0,
                      heading=None, chunk_text="text1", score=0.9)
    r2 = SearchResult(chunk_id=2, page_slug="b", scope=None, chunk_index=0,
                      heading=None, chunk_text="text2", score=0.8)
    r3 = SearchResult(chunk_id=3, page_slug="c", scope=None, chunk_index=0,
                      heading=None, chunk_text="text3", score=0.7)

    fused = search.rrf_fuse([[r1, r2], [r3, r1]], k=60, limit=10)
    assert fused[0].chunk_id == 1


def test_keyword_search_returns_matches(seeded_db):
    results = search.keyword_search("MariaDB", scope="decisions", limit=10)
    assert len(results) >= 1
    assert any("mariadb" in r.chunk_text.lower() for r in results)


def test_record_feedback(seeded_db):
    qtext = f"MariaDB test {int(time.time() * 1000)}"
    search.record_feedback(
        query_text=qtext,
        chunk_id=1,
        feedback="useful",
        page_slug="decisions/test-search-1",
        agent_signature="claude:test",
    )
    rows = db.read_many(
        "SELECT feedback, chunk_id FROM mm_search_feedback WHERE query_text = %s",
        (qtext,),
    )
    assert len(rows) >= 1
    assert rows[0]["feedback"] == "useful"
    # Cleanup
    db.write_one("DELETE FROM mm_search_feedback WHERE query_text = %s", (qtext,))


def test_record_feedback_rejects_invalid():
    with pytest.raises(ValueError):
        search.record_feedback(query_text="x", chunk_id=1, feedback="invalid")