from __future__ import annotations

import importlib

import numpy as np
import pytest


def _reload_embed(monkeypatch, **env):
    for key in [
        "EMBEDDING_PROVIDER",
        "EMBEDDING_MODEL",
        "EMBEDDING_DIM",
        "EMBEDDING_MAX_CHARS",
        "VERTEX_PROJECT",
        "GOOGLE_CLOUD_PROJECT",
        "VERTEX_LOCATION",
    ]:
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, str(value))

    import memoria_mcp.embed as embed_mod

    return importlib.reload(embed_mod)


def test_current_space_defaults_to_vertex_shape_384(monkeypatch):
    embed_mod = _reload_embed(monkeypatch, VERTEX_PROJECT="test-project")

    assert embed_mod.current_space() == {
        "provider": "vertex",
        "model": "text-embedding-004",
        "dim": 384,
    }


@pytest.mark.asyncio
async def test_embed_document_uses_retrieval_document(monkeypatch):
    embed_mod = _reload_embed(monkeypatch, VERTEX_PROJECT="test-project")
    calls = {}

    def fake_post_json(url, payload, headers, timeout=30):
        calls["payload"] = payload
        return {"predictions": [{"embeddings": {"values": [0.1, 0.2]}}]}

    async def fake_to_thread(fn):
        return fn()

    monkeypatch.setattr(embed_mod.vertex_client, "auth_headers", lambda: {"Authorization": "Bearer adc-token"})
    monkeypatch.setattr(embed_mod.vertex_client, "post_json", fake_post_json)
    monkeypatch.setattr(embed_mod.asyncio, "to_thread", fake_to_thread)

    result = await embed_mod.embed_document("doc text")

    assert isinstance(result, np.ndarray)
    assert result.tolist() == pytest.approx([0.1, 0.2])
    assert calls["payload"]["instances"][0]["task_type"] == "RETRIEVAL_DOCUMENT"


@pytest.mark.asyncio
async def test_embed_query_uses_retrieval_query(monkeypatch):
    embed_mod = _reload_embed(monkeypatch, VERTEX_PROJECT="test-project")
    calls = {}

    def fake_post_json(url, payload, headers, timeout=30):
        calls["payload"] = payload
        return {"predictions": [{"embeddings": {"values": [0.3, 0.4]}}]}

    async def fake_to_thread(fn):
        return fn()

    monkeypatch.setattr(embed_mod.vertex_client, "auth_headers", lambda: {"Authorization": "Bearer adc-token"})
    monkeypatch.setattr(embed_mod.vertex_client, "post_json", fake_post_json)
    monkeypatch.setattr(embed_mod.asyncio, "to_thread", fake_to_thread)

    result = await embed_mod.embed_query("query text")

    assert result.tolist() == pytest.approx([0.3, 0.4])
    assert calls["payload"]["instances"][0]["task_type"] == "RETRIEVAL_QUERY"


@pytest.mark.asyncio
async def test_embed_batch_sends_multiple_instances_once(monkeypatch):
    embed_mod = _reload_embed(monkeypatch, VERTEX_PROJECT="test-project")
    calls = []

    def fake_post_json(url, payload, headers, timeout=30):
        calls.append(payload)
        return {
            "predictions": [
                {"embeddings": {"values": [1.0, 0.0]}},
                {"embeddings": {"values": [0.0, 1.0]}},
            ]
        }

    async def fake_to_thread(fn):
        return fn()

    monkeypatch.setattr(embed_mod.vertex_client, "auth_headers", lambda: {"Authorization": "Bearer adc-token"})
    monkeypatch.setattr(embed_mod.vertex_client, "post_json", fake_post_json)
    monkeypatch.setattr(embed_mod.asyncio, "to_thread", fake_to_thread)

    result = await embed_mod.embed_batch(["a", "b"])

    assert len(calls) == 1
    assert [v.tolist() for v in result] == [[1.0, 0.0], [0.0, 1.0]]
    assert [i["content"] for i in calls[0]["instances"]] == ["a", "b"]


@pytest.mark.asyncio
async def test_malformed_vertex_response_raises(monkeypatch):
    embed_mod = _reload_embed(monkeypatch, VERTEX_PROJECT="test-project")

    def fake_post_json(url, payload, headers, timeout=30):
        return {"predictions": [{}]}

    async def fake_to_thread(fn):
        return fn()

    monkeypatch.setattr(embed_mod.vertex_client, "auth_headers", lambda: {"Authorization": "Bearer adc-token"})
    monkeypatch.setattr(embed_mod.vertex_client, "post_json", fake_post_json)
    monkeypatch.setattr(embed_mod.asyncio, "to_thread", fake_to_thread)

    with pytest.raises(RuntimeError, match="embedding"):
        await embed_mod.embed_query("x")
