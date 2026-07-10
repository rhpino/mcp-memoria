#!/bin/bash
# start.sh — mcp-memoria launcher (secops deploy / Docker-adapted)
# Levanta el MCP server en background. Si systemd está activo, prefiere
# `systemctl start mcp-memoria.service` (integration con journald, restart
# policy, etc.). Si no, lanza directo desde PATH del venv.
#
# Docker-ready: usa paths relativos (`$(dirname "$0")/..`), no absolutos.

set -euo pipefail

# Calcula MEM_DIR desde el path del script (Docker-portable; no hardcoded).
MEM_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PID_FILE="${MEMORIA_INSTANCE_DIR:-${MEM_DIR}/.mcp-memoria}/server.pid"
VENV_PY="${MEM_DIR}/.venv/bin/python"

# Cargar .env si existe (Docker-friendly: single source of truth).
if [ -f "${MEM_DIR}/.env" ]; then
    set -a
    . "${MEM_DIR}/.env"
    set +a
fi

# Si systemd tiene la unit y está activa, delegate.
if systemctl is-active --quiet mcp-memoria.service 2>/dev/null; then
    echo "mcp-memoria ya corriendo via systemd (PID file: ${PID_FILE:-unknown})"
    exit 0
fi

# Si hay PID file con proceso vivo, no hacer nada.
if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
    echo "mcp-memoria ya corriendo (PID $(cat "$PID_FILE"))"
    exit 0
fi

# Validar mínimo (sin systemd, las env vars DEBEN estar seteadas).
if [ -z "${MCP_PORT:-}" ] || [ -z "${MCP_DB_HOST:-}" ]; then
    echo "ERROR: faltan env vars críticas (MCP_PORT, MCP_DB_HOST)." >&2
    echo "  Definelas en ${MEM_DIR}/.env o como override del ambiente." >&2
    exit 2
fi

# Lanzar desde el venv. PATH solo tiene lo del venv + essentials.
cd "$MEM_DIR"
mkdir -p "$(dirname "$PID_FILE")"
nohup "$VENV_PY" -u -m memoria_mcp.server \
    >> "${MEMORIA_LOG_DIR:-/tmp}/memoria.log" 2>&1 &
PID=$!
echo "$PID" > "$PID_FILE"

# Esperar health hasta 10s.
for i in {1..20}; do
    sleep 0.5
    if curl -sS --max-time 1 "http://127.0.0.1:${MCP_PORT}/health" >/dev/null 2>&1; then
        echo "mcp-memoria arrancado (PID $PID, puerto $MCP_PORT)"
        exit 0
    fi
done

echo "ERROR: mcp-memoria no respondió /health en 10s. Ver logs."
exit 1