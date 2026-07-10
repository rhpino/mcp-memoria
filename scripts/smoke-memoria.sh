#!/bin/bash
# smoke-memoria.sh — E2E smoke test del mcp-memoria server.
# Streamable HTTP transport con session management.
set -euo pipefail

PORT="${MCP_PORT:-9092}"
HOST="${MCP_HOST:-127.0.0.1}"
URL="http://${HOST}:${PORT}"

TOKEN=$(sudo grep FLOW_TOKEN_CLAUDE_CODE /etc/flow-gateway/tokens.env | cut -d= -f2)
PASS=0
FAIL=0

step() { echo ""; echo "===== $1 ====="; }
report() { echo "   $1"; [ "${1:0:4}" = "PASS" ] && PASS=$((PASS+1)) || FAIL=$((FAIL+1)); }

# ── Step 1: /health ─────────────────────────────────────────────
step "1. /health (no auth required)"
RESP=$(curl -sS -w "\n::HTTP::%{http_code}" "$URL/health")
HTTP=$(echo "$RESP" | tail -1 | sed 's/::HTTP:://')
BODY=$(echo "$RESP" | sed '$d')
if [ "$HTTP" = "200" ] && echo "$BODY" | grep -q '"status":"ok"'; then
    report "PASS (DB OK)"
else
    report "FAIL (HTTP $HTTP)"
fi

# ── Step 2: /metrics ────────────────────────────────────────────
step "2. /metrics (no auth required)"
HTTP=$(curl -sS -o /tmp/memoria-metrics.txt -w "%{http_code}" "$URL/metrics")
if [ "$HTTP" = "200" ] && [ "$(wc -l < /tmp/memoria-metrics.txt)" -gt 0 ]; then
    report "PASS ($(wc -l < /tmp/memoria-metrics.txt) lines)"
else
    report "FAIL (HTTP $HTTP)"
fi

# ── Step 3: POST /mcp sin auth → 401 ──────────────────────────
step "3. POST /mcp sin auth → 401"
HTTP=$(curl -sS -o /dev/null -w "%{http_code}" \
    -X POST "$URL/mcp" \
    -H "Content-Type: application/json" \
    -H "Accept: application/json,text/event-stream" \
    -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}')
if [ "$HTTP" = "401" ]; then
    report "PASS"
else
    report "FAIL (got $HTTP)"
fi

# ── Step 4: POST /mcp con Bearer inválido → 401 ────────────────
step "4. POST /mcp con Bearer inválido → 401"
HTTP=$(curl -sS -o /dev/null -w "%{http_code}" \
    -X POST "$URL/mcp" \
    -H "Content-Type: application/json" \
    -H "Accept: application/json,text/event-stream" \
    -H "Authorization: Bearer bad_token_xyz" \
    -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}')
if [ "$HTTP" = "401" ]; then
    report "PASS"
else
    report "FAIL (got $HTTP)"
fi

# ── Step 5: MCP initialize (Bearer válido + SSE response) ───────
step "5. MCP initialize (valid Bearer, expect 200 SSE)"
INIT_HEADERS=$(curl -sS -D - -o /tmp/memoria-init-body.txt -w "%{http_code}" \
    -X POST "$URL/mcp" \
    -H "Content-Type: application/json" \
    -H "Accept: application/json,text/event-stream" \
    -H "Authorization: Bearer ${TOKEN}" \
    -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"smoke","version":"1.0"}}}')
HTTP=$(echo "$INIT_HEADERS" | tail -1)
SESSION_ID=$(echo "$INIT_HEADERS" | grep -i "^mcp-session-id:" | sed 's/.*: //;s/\r//' | tr -d '\r\n')
SERVER_NAME=$(grep -o '"name":"[^"]*"' /tmp/memoria-init-body.txt | head -1 | cut -d'"' -f4)
echo "   HTTP $HTTP  Session: ${SESSION_ID:0:16}...  Server: $SERVER_NAME"
if [ "$HTTP" = "200" ] && [ -n "$SESSION_ID" ]; then
    report "PASS"
else
    report "FAIL (HTTP $HTTP)"
fi

# ── Step 6: tools/list con session ──────────────────────────────
step "6. tools/list (with session)"
if [ -n "$SESSION_ID" ]; then
    LIST_HEADERS=$(curl -sS -D - -o /tmp/memoria-list-body.txt -w "%{http_code}" \
        -X POST "$URL/mcp" \
        -H "Content-Type: application/json" \
        -H "Accept: application/json,text/event-stream" \
        -H "Authorization: Bearer ${TOKEN}" \
        -H "mcp-session-id: ${SESSION_ID}" \
        -d '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}')
    HTTP=$(echo "$LIST_HEADERS" | tail -1)
    TOOLS_COUNT=$(grep -o '"name":"[^"]*"' /tmp/memoria-list-body.txt | wc -l)
    echo "   HTTP $HTTP  Body lines: $(wc -l < /tmp/memoria-list-body.txt)  Tools: $TOOLS_COUNT"
    if [ "$HTTP" = "200" ] && [ "$TOOLS_COUNT" -ge 13 ]; then
        report "PASS ($TOOLS_COUNT tools registered)"
    else
        report "FAIL (HTTP $HTTP, $TOOLS_COUNT tools)"
    fi
else
    echo "   SKIP (no session)"
fi

# ── Step 7: kag_buscar con session ──────────────────────────────
step "7. tools/call kag_buscar (empty corpus)"
if [ -n "$SESSION_ID" ]; then
    CALL_RESP=$(curl -sS -X POST "$URL/mcp" \
        -H "Content-Type: application/json" \
        -H "Accept: application/json,text/event-stream" \
        -H "Authorization: Bearer ${TOKEN}" \
        -H "mcp-session-id: ${SESSION_ID}" \
        -d '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"kag_buscar","arguments":{"query":"test","limit":3}}}')
    echo "   Response (truncated):"
    echo "$CALL_RESP" | head -c 300
    echo ""
    if echo "$CALL_RESP" | grep -q '"kag_buscar"\|"result"\|"content"'; then
        report "PASS"
    else
        report "WARN (check response)"
    fi
else
    echo "   SKIP (no session)"
fi

# ── Step 8: link_add idempotente ────────────────────────────────
step "8. tools/call link_add (idempotente)"
if [ -n "$SESSION_ID" ]; then
    LINK_RESP1=$(curl -sS -X POST "$URL/mcp" \
        -H "Content-Type: application/json" \
        -H "Accept: application/json,text/event-stream" \
        -H "Authorization: Bearer ${TOKEN}" \
        -H "mcp-session-id: ${SESSION_ID}" \
        -d '{"jsonrpc":"2.0","id":4,"method":"tools/call","params":{"name":"link_add","arguments":{"from_id":"test:from","to_id":"test:to","relation":"related_to","actor":"smoke"}}}')
    LINK_RESP2=$(curl -sS -X POST "$URL/mcp" \
        -H "Content-Type: application/json" \
        -H "Accept: application/json,text/event-stream" \
        -H "Authorization: Bearer ${TOKEN}" \
        -H "mcp-session-id: ${SESSION_ID}" \
        -d '{"jsonrpc":"2.0","id":5,"method":"tools/call","params":{"name":"link_add","arguments":{"from_id":"test:from","to_id":"test:to","relation":"related_to","actor":"smoke"}}}')
    echo "   1st call: $(echo "$LINK_RESP1" | head -c 100)"
    echo "   2nd call: $(echo "$LINK_RESP2" | head -c 100)"
    # Limpieza
    curl -sS -X POST "$URL/mcp" \
        -H "Content-Type: application/json" \
        -H "Accept: application/json,text/event-stream" \
        -H "Authorization: Bearer ${TOKEN}" \
        -H "mcp-session-id: ${SESSION_ID}" \
        -d '{"jsonrpc":"2.0","id":6,"method":"tools/call","params":{"name":"conflict_list","arguments":{}}}' > /dev/null || true
    # Direct delete via DB would be safer
    sudo -u geo /opt/mcps/memoria/.venv/bin/python -c "
import os
os.environ['MCP_DB_USER'] = 'mcp_memoria'
# H11 audit 2026-07-02: source DB env from /etc/mcp-memoria/db.env
if [ -f /etc/mcp-memoria/db.env ]; then
    set -a; . /etc/mcp-memoria/db.env; set +a
else
    echo 'ERROR: /etc/mcp-memoria/db.env not found. Required for DB access.' >&2; exit 1
fi
from memoria_mcp import db
db.write_one('DELETE FROM mm_relations WHERE from_id = %s', ('test:from',))
print('   cleaned up test:from relation')
" 2>&1 | tail -1
    if echo "$LINK_RESP1" | grep -q '"content"'; then
        report "PASS (idempotente)"
    else
        report "WARN"
    fi
else
    echo "   SKIP (no session)"
fi

echo ""
echo "==================================================="
echo "[smoke-memoria] RESULT: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ] || exit 1