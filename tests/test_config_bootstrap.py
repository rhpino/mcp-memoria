"""Tests for startup configuration bootstrap."""
from __future__ import annotations


def test_server_bootstrap_config_calls_loader_and_validator(monkeypatch):
    """server exposes one bootstrap hook that loads .env and validates required env."""
    from memoria_mcp import server

    calls: list[str] = []

    monkeypatch.setattr(server.config, "load_dotenv", lambda: calls.append("load"))
    monkeypatch.setattr(server.config, "validate_required_env", lambda: calls.append("validate"))

    server._bootstrap_config()

    assert calls == ["load", "validate"]
