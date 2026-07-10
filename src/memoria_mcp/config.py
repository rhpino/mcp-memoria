"""
config.py — Cargador centralizado de configuración para mcp-memoria.

Principios:
  - NO defaults hardcodeados en código para vars críticas. Si falta una crítica,
    el server falla al arranque con RuntimeError explícito.
  - Las variables viven en `<package>/.env` (portable, junto al código).
  - `load_dotenv()` se llama al inicio de server.py, ANTES de cualquier
    `os.environ[...]` que use vars críticas.
  - El .env NO sobrescribe variables ya seteadas en el ambiente
    (permite override por systemd EnvironmentFile=, Docker --env-file=, etc.).

Uso:
    # Al arranque de server.py:
    from config import load_dotenv, validate_required_env
    load_dotenv()
    validate_required_env()

    # En cualquier módulo:
    import os
    port = int(os.environ["MCP_PORT"])  # KeyError si falta — fail-fast.

Roadmap:
    - Dockerfile que use `COPY . /app` + `--env-file .env` en runtime.
    - systemd unit con `EnvironmentFile=/opt/mcps/memoria/.env`.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


# Ruta al project root (donde vive pyproject.toml, .env, bin/, etc.).
# memoria usa layout src/ — el código está en src/memoria_mcp/, pero la config
# vive junto al repo root (Docker convention: .env en /app, source en /app/src).
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
ENV_FILE = _PROJECT_ROOT / ".env"


def load_dotenv(path: Path | None = None) -> int:
    """
    Carga variables desde `path` (default = .env del package) en os.environ.

    - No sobrescribe si la variable ya está seteada en el ambiente.
    - Líneas vacías o que empiezan con # son ignoradas.
    - Formato: `KEY=value` (sin comillas necesarias; value puede tener espacios).

    Returns: cantidad de variables nuevas seteadas.
    """
    target = path or ENV_FILE
    if not target.exists():
        return 0

    loaded = 0
    for raw_line in target.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        # Strip surrounding quotes si las tiene.
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
            value = value[1:-1]
        if not key:
            continue
        # setdefault: respeta lo que el ambiente / systemd ya haya seteado.
        if key not in os.environ:
            os.environ[key] = value
            loaded += 1
    return loaded


# Lista de variables REQUERIDAS (sin default posible en código).
# Si alguna de estas falta al arranque, el server no inicia.
REQUIRED_ENV_VARS: tuple[str, ...] = (
    # Server
    "MCP_PORT",
    "MCP_HOST",
    # DB externa unificada (MariaDB en Tailscale reachable)
    "MCP_DB_HOST",
    "MCP_DB_PORT",
    "MCP_DB_USER",
    "MCP_DB_PASS",
    "MCP_DB_NAME",
    # Auth (tokens via env var)
    "FLOW_GATEWAY_TOKENS",
    # Paths
    "MCP_INSTANCE_DIR",
    "WORKSPACE_ROOT",
    "MCP_VEC_DB",
    "MCP_INDEX_PATH",
)


def validate_required_env() -> None:
    """
    Verifica que las env vars críticas estén seteadas.
    Si falta alguna, raise RuntimeError con la lista completa.
    """
    missing = [k for k in REQUIRED_ENV_VARS if not os.environ.get(k)]
    if not missing:
        return

    msg = (
        "mcp-memoria refuses to start: faltan variables de entorno requeridas.\n"
        f"  Faltan: {', '.join(missing)}\n"
        f"  Definilas en: {ENV_FILE}\n"
        f"  (o como override vía systemd EnvironmentFile= / Docker --env-file).\n"
        "  Referencia: .env.example."
    )
    print(msg, file=sys.stderr)
    raise RuntimeError(msg)


def require_env(key: str) -> str:
    """Helper para módulos: obtiene env var o falla con mensaje claro."""
    val = os.environ.get(key)
    if not val:
        raise RuntimeError(
            f"mcp-memoria: env var requerida {key!r} no seteada. "
            f"Probá cargar .env o revisar {ENV_FILE}."
        )
    return val


def require_env_int(key: str) -> int:
    """Igual a require_env pero parsea a int."""
    raw = require_env(key)
    try:
        return int(raw)
    except ValueError as e:
        raise RuntimeError(
            f"mcp-memoria: env var {key}={raw!r} no es un entero válido"
        ) from e


__all__ = [
    "ENV_FILE",
    "REQUIRED_ENV_VARS",
    "load_dotenv",
    "validate_required_env",
    "require_env",
    "require_env_int",
]
