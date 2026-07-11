from __future__ import annotations


class _FakeCreds:
    """Minimal stand-in for google.auth credentials."""

    def __init__(self):
        self.token: str | None = None
        self.valid = False
        self.expired = True
        self.refresh_count = 0

    def refresh(self, request):
        self.refresh_count += 1
        self.token = f"token-{self.refresh_count}"
        self.valid = True
        self.expired = False


def test_adc_token_is_cached(monkeypatch):
    from memoria_mcp import vertex_client

    creds = _FakeCreds()
    monkeypatch.setattr(
        vertex_client.google.auth, "default", lambda **kw: (creds, "proj")
    )

    vertex_client.reset_adc_cache()
    assert vertex_client.get_adc_access_token() == "token-1"
    assert vertex_client.get_adc_access_token() == "token-1"
    assert creds.refresh_count == 1


def test_adc_token_refreshes_when_expired(monkeypatch):
    from memoria_mcp import vertex_client

    creds = _FakeCreds()
    monkeypatch.setattr(
        vertex_client.google.auth, "default", lambda **kw: (creds, "proj")
    )

    vertex_client.reset_adc_cache()
    assert vertex_client.get_adc_access_token() == "token-1"

    creds.valid = False
    creds.expired = True

    assert vertex_client.get_adc_access_token() == "token-2"
    assert creds.refresh_count == 2


def test_reset_adc_cache_reloads_creds(monkeypatch):
    from memoria_mcp import vertex_client

    creds_a = _FakeCreds()
    creds_b = _FakeCreds()
    current = {"i": 0}

    def fake_default(**kw):
        current["i"] += 1
        return ([creds_a, creds_b][current["i"] - 1], "proj")

    monkeypatch.setattr(vertex_client.google.auth, "default", fake_default)

    vertex_client.reset_adc_cache()
    assert vertex_client.get_adc_access_token() == "token-1"

    vertex_client.reset_adc_cache()
    assert vertex_client.get_adc_access_token() == "token-1"
    assert current["i"] == 2


def test_auth_headers_use_bearer(monkeypatch):
    from memoria_mcp import vertex_client

    monkeypatch.setattr(vertex_client, "get_adc_access_token", lambda: "adc-token")

    assert vertex_client.auth_headers() == {
        "Content-Type": "application/json",
        "Authorization": "Bearer adc-token",
    }
