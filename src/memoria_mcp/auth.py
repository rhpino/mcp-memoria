"""auth.py — Tailscale WhoIs + Bearer token auth.

Réplica conceptual del patrón mop-mcp /internal/auth/middleware.py.

Middleware FastAPI:
1. Source IP en CGNAT Tailscale (100.64.0.0/10) o VPN LAN (10.255.255.0/24)
   → pasa sin Bearer (Tailscale WhoIs prioriza).
2. Authorization: Bearer <token> contra /etc/flow-gateway/tokens.env
   → pasa con Bearer válido.
3. Si nada matchea → 401 (no 403 — no leak existencia).
"""
from __future__ import annotations

import hmac
import ipaddress
import logging
import os
import subprocess
from pathlib import Path
from typing import Optional

from fastapi import Request
from fastapi.responses import JSONResponse

log = logging.getLogger("memoria_auth")

# Defaults — leídos en runtime vía os.environ.get(...) para que tests puedan
# sobreescribir el env var sin recompilar el módulo.
TOKENS_PATH_DEFAULT = "/etc/flow-gateway/tokens.env"
TAILSCALE_BIN = os.environ.get("TAILSCALE_WHOIS_BIN", "/usr/bin/tailscale")
TAILSCALE_CIDR = ipaddress.ip_network(
    os.environ.get("TAILSCALE_CIDR", "100.64.0.0/10"), strict=False
)
LAN_VPN_CIDR = ipaddress.ip_network(
    os.environ.get("LAN_VPN_CIDR", "10.255.255.0/24"), strict=False
)

# Cache
_tokens_cache: Optional[dict[str, str]] = None


def _tokens_path() -> Path:
    """Lee el env var en runtime (no module-level) para tests."""
    return Path(os.environ.get("FLOW_GATEWAY_TOKENS", TOKENS_PATH_DEFAULT))


_tokens_cache: Optional[dict[str, str]] = None
# Audit mcp-memoria 2026-07-05 (MOP-388) C7: tokens + mtime en cache para
# auto-reload cuando el file cambia en disco. Sin esto, rotación de tokens
# requiere SIGHUP manual o restart del proceso.
_tokens_mtime: Optional[float] = None


def _load_tokens() -> dict[str, str]:
    """Lee /etc/flow-gateway/tokens.env (path via env, leída dinámicamente)."""
    global _tokens_cache, _tokens_mtime
    tokens_path = _tokens_path()
    try:
        current_mtime = tokens_path.stat().st_mtime
    except FileNotFoundError:
        current_mtime = None

    if _tokens_cache is not None and _tokens_mtime == current_mtime:
        return _tokens_cache

    tokens: dict[str, str] = {}
    if tokens_path.exists():
        for line in tokens_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                k, _, v = line.partition("=")
                tokens[k.strip()] = v.strip()
    else:
        log.warning("tokens_file_missing", extra={"path": str(tokens_path)})

    _tokens_cache = tokens
    _tokens_mtime = current_mtime
    log.info("tokens_loaded", extra={"count": len(tokens), "path": str(tokens_path)})
    return tokens


def reload_tokens() -> dict[str, str]:
    """Recarga el cache (rotación SIGHUP)."""
    global _tokens_cache
    _tokens_cache = None
    return _load_tokens()


def _get_client_ip(request: Request) -> str:
    # SECURITY (H1 audit 2026-07-02): no confiar en X-Forwarded-For.
    # El server NO está detrás de un reverse proxy local, por lo que cualquier
    # XFF es spoofing directo del cliente. Usar solo request.client.host
    # (la IP TCP real del peer).
    if request.client:
        return request.client.host
    return ""


def _is_tailscale_ip(ip_str: str) -> bool:
    """True si la IP está en Tailscale CGNAT (100.64.0.0/10)."""
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return False
    return ip in TAILSCALE_CIDR


def _is_lan_vpn_ip(ip_str: str) -> bool:
    """True si la IP está en LAN VPN (10.255.255.0/24).

    H5 audit 2026-07-02: las IPs LAN no son nodos Tailscale. El `tailscale whois`
    sobre ellas falla siempre (devuelve None), lo que rompe la spec.
    La regla correcta: LAN VPN pasa sin WhoIs pero requiere Bearer siempre
    (un cliente LAN debe ser explícitamente autorizado con token).
    """
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return False
    return ip in LAN_VPN_CIDR


def _tailscale_whois(ip: str) -> Optional[dict]:
    try:
        out = subprocess.run(
            [TAILSCALE_BIN, "whois", ip],
            capture_output=True,
            text=True,
            timeout=2,
        )
        if out.returncode == 0:
            return {"raw": out.stdout.strip(), "ip": ip}
    except (FileNotFoundError, subprocess.TimeoutExpired, Exception):
        pass
    return None


def _check_bearer(auth_header: Optional[str]) -> Optional[str]:
    if not auth_header:
        return None
    if not auth_header.startswith("Bearer "):
        return None
    token = auth_header[len("Bearer "):].strip()
    if not token:
        return None
    tokens = _load_tokens()
    # Audit mcp-memoria 2026-07-05 (MOP-388) C1+C4: hmac.compare_digest
    # previene timing attacks. Iterar con list() fijo para orden estable.
    for name, expected in list(tokens.items()):
        if hmac.compare_digest(token, expected):
            return name
    return None


async def auth_middleware(request: Request, call_next):
    """Middleware principal. 401 si nada matchea.

H1 audit 2026-07-02: removed X-Forwarded-For trust (no reverse proxy local).
H5 audit 2026-07-02: LAN VPN treated as a separate auth path (no tailscale whois).
"""
    # Health/metrics abiertos
    if request.url.path in ("/health", "/metrics"):
        return await call_next(request)

    client_ip = _get_client_ip(request)
    auth_header = request.headers.get("Authorization")

    # 1. Tailscale (CGNAT): validar con tailscale whois
    if _is_tailscale_ip(client_ip):
        whois = _tailscale_whois(client_ip)
        if whois is not None:
            log.debug("auth_ok_tailscale",
                      extra={"ip": client_ip, "path": request.url.path})
            request.state.auth = {"method": "tailscale", "ip": client_ip,
                                  "whois": whois}
            return await call_next(request)

    # 1b. LAN VPN: NO usar tailscale whois (fallaría siempre). Pasar a Bearer.
    if _is_lan_vpn_ip(client_ip):
        token_name = _check_bearer(auth_header)
        if token_name:
            log.debug("auth_ok_lan_bearer",
                      extra={"ip": client_ip, "path": request.url.path,
                             "token": token_name})
            request.state.auth = {"method": "lan_vpn_bearer", "ip": client_ip,
                                  "token": token_name}
            return await call_next(request)

    # 2. Bearer (default para todas las otras IPs, incluyendo LAN VPN sin token)
    token_name = _check_bearer(auth_header)
    if token_name:
        log.debug("auth_ok_bearer",
                  extra={"token": token_name, "path": request.url.path})
        request.state.auth = {"method": "bearer", "token": token_name}
        return await call_next(request)

    # 3. Deny
    log.warning(
        "auth_denied",
        extra={"ip": client_ip, "path": request.url.path,
               "has_auth_header": bool(auth_header)},
    )
    return JSONResponse(
        status_code=401,
        content={"error": "unauthorized", "detail": "invalid auth"},
    )