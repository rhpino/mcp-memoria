from __future__ import annotations


def test_adc_token_is_cached(monkeypatch):
    from memoria_mcp import vertex_client

    vertex_client.reset_adc_cache()
    calls = []

    def fake_check_output(cmd, text, timeout):
        calls.append(cmd)
        return "token-1\n"

    monkeypatch.setattr(vertex_client.subprocess, "check_output", fake_check_output)
    monkeypatch.setattr(vertex_client.time, "time", lambda: 1000.0)

    assert vertex_client.get_adc_access_token() == "token-1"
    assert vertex_client.get_adc_access_token() == "token-1"
    assert calls == [[vertex_client.GCLOUD_BIN, "auth", "application-default", "print-access-token"]]


def test_adc_token_refreshes_after_expiry(monkeypatch):
    from memoria_mcp import vertex_client

    vertex_client.reset_adc_cache()
    calls = []

    def fake_check_output(cmd, text, timeout):
        calls.append(cmd)
        return f"token-{len(calls)}\n"

    now = {"value": 1000.0}
    monkeypatch.setattr(vertex_client.subprocess, "check_output", fake_check_output)
    monkeypatch.setattr(vertex_client.time, "time", lambda: now["value"])

    assert vertex_client.get_adc_access_token() == "token-1"
    now["value"] += 51 * 60
    assert vertex_client.get_adc_access_token() == "token-2"


def test_auth_headers_use_bearer(monkeypatch):
    from memoria_mcp import vertex_client

    monkeypatch.setattr(vertex_client, "get_adc_access_token", lambda: "adc-token")

    assert vertex_client.auth_headers() == {
        "Content-Type": "application/json",
        "Authorization": "Bearer adc-token",
    }
