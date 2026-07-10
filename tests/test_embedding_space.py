from __future__ import annotations

import numpy as np
import pytest

from memoria_mcp import db, search


def test_cosine_search_ignores_mismatched_embedding_space(isolate_test_db):
    db.init_schema()
    db.write_one("DELETE FROM mm_entity_chunks WHERE page_slug = %s", ("test/mixed-space",))
    db.write_one(
        "INSERT INTO mm_entity_chunks "
        "(page_slug, chunk_index, heading, chunk_text, entities_referenced, word_count, embedding, scope, "
        "embedding_provider, embedding_model, embedding_dim) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (
            "test/mixed-space",
            0,
            "Mixed",
            "Old fastembed vector",
            "[]",
            3,
            np.array([1.0, 0.0] + [0.0] * 382, dtype=np.float32).tobytes(),
            "test-space",
            "fastembed",
            "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
            384,
        ),
    )

    results = search.cosine_search(
        np.array([1.0, 0.0] + [0.0] * 382, dtype=np.float32),
        scope="test-space",
        limit=10,
        embedding_provider="vertex",
        embedding_model="text-embedding-004",
        embedding_dim=384,
    )

    assert results == []


@pytest.mark.asyncio
async def test_kag_buscar_uses_query_embedding(monkeypatch):
    from memoria_mcp.tools import kag

    calls = []

    async def fake_embed_query(text):
        calls.append(("query", text))
        return np.array([1.0, 0.0], dtype=np.float32)

    async def fake_hybrid_search(**kwargs):
        calls.append(("hybrid", kwargs["query_embedding"].tolist()))
        return []

    monkeypatch.setattr(kag.embed_mod, "embed_query", fake_embed_query)
    monkeypatch.setattr(kag.search_mod, "hybrid_search", fake_hybrid_search)

    assert await kag.kag_buscar("hola") == []
    assert calls[0] == ("query", "hola")
