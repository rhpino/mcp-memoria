"""tests/test_bibliotecario.py — Tests para bibliotecario (LLM merge + conflict_queue)."""
from __future__ import annotations

import pytest

from memoria_mcp import bibliotecario, db


@pytest.fixture(scope="session", autouse=True)
def cleanup_conflicts():
    """Limpia conflicts antes y después de la sesión."""
    db.write_one(
        "DELETE FROM mm_conflict_queue WHERE entity_id LIKE %s",
        ("test-percent",),
    )
    yield
    db.write_one(
        "DELETE FROM mm_conflict_queue WHERE entity_id LIKE %s",
        ("test-percent",),
    )


@pytest.fixture
def seeded_conflicts():
    """Inserta 3 conflictos de prueba."""
    conflicts = [
        ("decision", "test-percent-merge-1", "Content A version 1", "Content A version 2"),
        ("decision", "test-percent-empty-1", "", "Only B has content"),
        ("decision", "test-percent-future-1", "Future A", "Future B"),
    ]
    ids = []
    for et, eid, a, b in conflicts:
        cid = db.write_one(
            "INSERT INTO mm_conflict_queue (entity_type, entity_id, gcp_content, node_content) "
            "VALUES (%s, %s, %s, %s)",
            (et, eid, a, b),
        )
        ids.append(cid)

    yield ids

    db.write_one(
        "DELETE FROM mm_conflict_queue WHERE entity_id LIKE %s",
        ("test-percent",),
    )


@pytest.mark.asyncio
async def test_run_no_llm_marks_skipped(seeded_conflicts, monkeypatch):
    """Sin proveedor LLM, run marca todos los pending como 'skipped'."""
    monkeypatch.setenv("MINIMAX_ENABLED", "false")
    monkeypatch.setenv("MINIMAX_KEY", "")
    monkeypatch.setenv("GEMINI_KEY", "")
    monkeypatch.setenv("VERTEX_GEMINI_ENABLED", "false")

    import importlib
    import memoria_mcp.bibliotecario as bib_mod
    importlib.reload(bib_mod)

    result = await bib_mod.run(max_conflicts=10)
    assert result["llm_available"] is False
    assert result["skipped"] >= 3


@pytest.mark.asyncio
async def test_list_conflicts_filter_by_state(seeded_conflicts):
    """list_conflicts filtra por state."""
    all_conflicts = await bibliotecario.list_conflicts()
    assert len(all_conflicts) >= 3

    pending = await bibliotecario.list_conflicts(state="pending")
    assert all(c["resolution"] == "pending" for c in pending)


@pytest.mark.asyncio
async def test_resolve_conflict_manual(seeded_conflicts):
    """resolve_conflict actualiza un conflicto manualmente."""
    conflicts = await bibliotecario.list_conflicts(state="pending")
    cid = conflicts[0]["id"]

    result = await bibliotecario.resolve_conflict(cid, "kept", "test resolved")
    assert result["id"] == cid
    assert result["action"] == "kept"

    after = await bibliotecario.list_conflicts(state="kept")
    assert any(c["id"] == cid for c in after)


@pytest.mark.asyncio
async def test_resolve_conflict_invalid_action(seeded_conflicts):
    """resolve_conflict rechaza actions inválidos."""
    with pytest.raises(ValueError):
        await bibliotecario.resolve_conflict(1, "invalid_action")


def test_llm_available_false(monkeypatch):
    """llm_available devuelve False si no hay proveedor LLM."""
    monkeypatch.setenv("MINIMAX_ENABLED", "false")
    monkeypatch.setenv("MINIMAX_KEY", "")
    monkeypatch.setenv("GEMINI_KEY", "")
    monkeypatch.setenv("VERTEX_GEMINI_ENABLED", "false")
    import importlib
    import memoria_mcp.bibliotecario as bib_mod
    importlib.reload(bib_mod)
    assert bib_mod.llm_available() is False


@pytest.mark.asyncio
async def test_minimax_call_runs_blocking_http_in_thread(monkeypatch):
    """LLM HTTP call must not run urllib directly on the event loop."""
    monkeypatch.setenv("MINIMAX_ENABLED", "true")
    monkeypatch.setenv("MINIMAX_KEY", "test-key")

    import importlib
    import memoria_mcp.bibliotecario as bib_mod
    importlib.reload(bib_mod)

    calls: list[str] = []

    async def fake_to_thread(fn):
        calls.append("to_thread")
        return "merged"

    monkeypatch.setattr(bib_mod.asyncio, "to_thread", fake_to_thread)

    assert await bib_mod._call_minimax("prompt") == "merged"
    assert calls == ["to_thread"]


def test_vertex_adc_available_without_gemini_key(monkeypatch):
    """Gemini fallback uses Vertex ADC/gcloud, not API-key auth."""
    monkeypatch.setenv("MINIMAX_ENABLED", "false")
    monkeypatch.setenv("MINIMAX_KEY", "")
    monkeypatch.setenv("GEMINI_KEY", "")
    monkeypatch.setenv("VERTEX_GEMINI_ENABLED", "true")
    monkeypatch.setenv("VERTEX_PROJECT", "test-project")
    monkeypatch.setenv("VERTEX_LOCATION", "us-central1")

    import importlib
    import memoria_mcp.bibliotecario as bib_mod
    importlib.reload(bib_mod)

    assert bib_mod.llm_available() is True


@pytest.mark.asyncio
async def test_vertex_gemini_uses_adc_bearer_and_parses_response(monkeypatch):
    """Vertex Gemini call gets ADC token and calls aiplatform with Bearer auth."""
    monkeypatch.setenv("VERTEX_GEMINI_ENABLED", "true")
    monkeypatch.setenv("VERTEX_PROJECT", "test-project")
    monkeypatch.setenv("VERTEX_LOCATION", "us-central1")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-test")

    import importlib
    import memoria_mcp.bibliotecario as bib_mod
    importlib.reload(bib_mod)

    def fake_token() -> str:
        return "adc-token"

    called = {}

    def fake_request(url: str, payload: dict, headers: dict) -> dict:
        called["url"] = url
        called["payload"] = payload
        called["headers"] = headers
        return {
            "candidates": [
                {"content": {"parts": [{"text": "merged via vertex"}]}}
            ]
        }

    async def fake_to_thread(fn):
        return fn()

    monkeypatch.setattr(bib_mod, "_get_adc_access_token", fake_token)
    monkeypatch.setattr(bib_mod, "_post_json", fake_request)
    monkeypatch.setattr(bib_mod.asyncio, "to_thread", fake_to_thread)

    assert await bib_mod._call_vertex_gemini("prompt") == "merged via vertex"
    assert called["url"] == (
        "https://us-central1-aiplatform.googleapis.com/v1/projects/"
        "test-project/locations/us-central1/publishers/google/models/"
        "gemini-test:generateContent"
    )
    assert called["headers"]["Authorization"] == "Bearer adc-token"
