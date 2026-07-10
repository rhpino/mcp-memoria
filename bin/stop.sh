#!/bin/bash
# stop.sh — mcp-memoria stop (secops deploy / Docker-adapted)
# SIGTERM con timeout; SIGKILL fallback. Si systemd está activo, prefiere
# `systemctl stop`; si no, mata el proceso del PID file.

set -euo pipefail

MEM_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PID_FILE="${MEMORIA_INSTANCE_DIR:-${MEM_DIR}/.mcp-memoria}/server.pid"

# Si systemd tiene la unit, delegate.
if systemctl is-active --quiet mcp-memoria.service 2>/dev/null; then
    sudo systemctl stop mcp-memoria.service
    exit $?
fi

if [ ! -f "$PID_FILE" ]; then
    echo "mcp-memoria: no PID file ($PID_FILE) → no está corriendo"
    exit 0
fi

PID="$(cat "$PID_FILE")"
if ! kill -0 "$PID" 2>/dev/null; then
    echo "mcp-memoria: PID $PID no existe → limpiando PID file stale"
    rm -f "$PID_FILE"
    exit 0
fi

kill -TERM "$PID"
for i in {1..10}; do
    sleep 0.5
    if ! kill -0 "$PID" 2>/dev/null; then
        rm -f "$PID_FILE"
        echo "mcp-memoria detenido (PID $PID, SIGTERM)"
        exit 0
    fi
done

echo "mcp-memoria: PID $PID no respondió SIGTERM en 5s, enviando SIGKILL"
kill -KILL "$PID" 2>/dev/null || true
rm -f "$PID_FILE"
exit 0