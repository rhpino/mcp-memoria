from __future__ import annotations

import json
import urllib.request

import google.auth
import google.auth.transport.requests

_adc_creds = None
_request = None


def reset_adc_cache() -> None:
    global _adc_creds
    _adc_creds = None


def _get_request():
    global _request
    if _request is None:
        _request = google.auth.transport.requests.Request()
    return _request


def get_adc_access_token() -> str:
    global _adc_creds
    if _adc_creds is None:
        _adc_creds, _ = google.auth.default(
            scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )
    if not _adc_creds.valid or _adc_creds.expired:
        _adc_creds.refresh(_get_request())
    token = _adc_creds.token
    if not token:
        raise RuntimeError("ADC credentials returned an empty token after refresh")
    return token


def auth_headers() -> dict[str, str]:
    return {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {get_adc_access_token()}",
    }


def post_json(url: str, payload: dict, headers: dict, timeout: int = 30) -> dict:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))
