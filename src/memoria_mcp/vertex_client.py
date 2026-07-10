from __future__ import annotations

import json
import os
import subprocess
import time
import urllib.request

GCLOUD_BIN = os.environ.get("GCLOUD_BIN", "/snap/bin/gcloud")

_adc_token: str | None = None
_adc_token_expires_at = 0.0


def reset_adc_cache() -> None:
    global _adc_token, _adc_token_expires_at
    _adc_token = None
    _adc_token_expires_at = 0.0


def get_adc_access_token() -> str:
    global _adc_token, _adc_token_expires_at
    now = time.time()
    if _adc_token and now < _adc_token_expires_at:
        return _adc_token

    out = subprocess.check_output(
        [GCLOUD_BIN, "auth", "application-default", "print-access-token"],
        text=True,
        timeout=10,
    )
    token = out.strip()
    if not token:
        raise RuntimeError("gcloud returned empty ADC token")

    _adc_token = token
    _adc_token_expires_at = now + 50 * 60
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
