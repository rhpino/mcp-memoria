#!/bin/bash
# status.sh — ¿corre mcp-memoria? ¿qué puerto? ¿qué DB está conectada?
set -euo pipefail

MEM_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PID_FILE="${MEMORIA_INSTANCE_DIR:-${MEM_DIR}/.mcp-memoria}/server.pid"

if [ -f "${MEM_DIR}/.env" ]; then
    set -a; . "${MEM_DIR}/.env"; set +a
fi

echo "── mcp-memoria status ──"
echo "port:       ${MCP_PORT:-?}"
echo "host:       ${MCP_HOST:-?}"
echo "db_host:    ${MCP_DB_HOST:-?}"
echo "db_name:    ${MCP_DB_NAME:-?}"
echo "pid_file:   $PID_FILE"

if systemctl is-active --quiet mcp-memoria.service 2>/dev/null; then
    PID=$(systemctl show mcp-memoria.service --property=MainPID --value 2>/dev/null)
    echo "state:      CORRIENDO via systemd (PID $PID)"
elif [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
    PID="$(cat "$PID_FILE")"
    echo "state:      CORRIENDO (PID $PID)"
    if [ -n "${MCP_PORT:-}" ]; then
        echo "health:     $(curl -sS --max-time 2 "http://127.0.0.1:${MCP_PORT}/health" 2>&1 | head -c 200)"
    fi
else
    echo "state:      DETENIDO"
fi
echo "─────────────────────"