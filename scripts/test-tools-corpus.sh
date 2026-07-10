#!/bin/bash
# test-tools-corpus.sh — Prueba las tools con corpus indexado.
set -euo pipefail

PASS=0
FAIL=0

# ── Helpers ─────────────────────────────────────────────────────
TOKEN=$(sudo grep FLOW_TOKEN_CLAUDE_CODE /etc/flow-gateway/tokens.env | cut -d= -f2)
URL="http://100.72.183.50:9092"

# Inicializa sesión MCP una vez
INIT=$(curl -sS -D - -X POST "$URL/mcp" \
    -H "Content-Type: application/json" \
    -H "Accept: application/json,text/event-stream" \
    -H "Authorization: Bearer ${TOKEN}" \
    -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"corpus-test","version":"1.0"}}}')
SID=$(echo "$INIT" | grep -i "^mcp-session-id:" | sed 's/.*: //;s/\r//' | tr -d '\r\n')

report() {
    if [[ "$1" == PASS || "$1" == *"PASS"* ]]; then
        echo "   PASS"
        PASS=$((PASS+1))
    else
        echo "   FAIL"
        FAIL=$((FAIL+1))
    fi
}

call_tool() {
    local method="$1"
    local args="$2"
    curl -sS -X POST "$URL/mcp" \
        -H "Content-Type: application/json" \
        -H "Accept: application/json,text/event-stream" \
        -H "Authorization: Bearer ${TOKEN}" \
        -H "mcp-session-id: ${SID}" \
        -d "{\"jsonrpc\":\"2.0\",\"id\":2,\"method\":\"tools/call\",\"params\":{\"name\":\"${method}\",\"arguments\":${args}}}"
}

echo "===== mcp-memoria: corpus test ====="
echo "Session: ${SID:0:16}..."
echo ""

# 1. decision_list
echo "1. decision_list(scope='designs')"
RESP=$(call_tool "decision_list" '{"scope":"designs"}')
COUNT=$(echo "$RESP" | grep -o '"id":"[^"]*"' | wc -l)
echo "   Decisions found: ${COUNT}"
[ "$COUNT" -ge 1 ] && report PASS || report FAIL

# 2. decision_get
echo ""
echo "2. decision_get(id='designs:DESIGNS')"
RESP=$(call_tool "decision_get" '{"id":"designs:DESIGNS"}')
BODY_SIZE=$(echo "$RESP" | python3 -c "import json,sys;d=json.loads(sys.stdin.read().split('data: ',1)[1].split('\n')[0]);print(len(d['result']['structuredContent'].get('body','')))" 2>/dev/null || echo "?")
echo "   body chars: $BODY_SIZE"
[ -n "$BODY_SIZE" ] && [ "$BODY_SIZE" -gt 100 ] && report PASS || report FAIL

# 3. kag_buscar (semantic search)
echo ""
echo "3. kag_buscar(query='KAG MariaDB embeddings')"
RESP=$(call_tool "kag_buscar" '{"query":"KAG MariaDB embeddings","limit":5}')
RES=$(echo "$RESP" | python3 -c "
import json, sys
data = json.loads(sys.stdin.read().split('data: ', 1)[1].split('\n')[0])
result = data['result']['structuredContent']['result']
print(f'count={len(result)} top_cosine={result[0][\"cosine\"]:.4f} top_score={result[0][\"score\"]:.4f}' if result else 'count=0')
" 2>/dev/null)
echo "   ${RES}"
[ -n "$RES" ] && echo "$RES" | grep -q 'count=5' && report PASS || report FAIL

# 4. lesson_list
echo ""
echo "4. lesson_list()"
RESP=$(call_tool "lesson_list" '{}')
COUNT=$(echo "$RESP" | grep -o '"id":"[^"]*"' | wc -l)
echo "   Lessons found: ${COUNT}"
[ "$COUNT" -ge 1 ] && report PASS || report FAIL

# 5. adr_get
echo ""
echo "5. adr_get(number=3)"
RESP=$(call_tool "adr_get" '{"number":3}')
echo "   $(echo "$RESP" | head -c 200)..."
echo "$RESP" | grep -q '"number":3' && echo "$RESP" | grep -q '"body"' && report PASS || report FAIL

# 6. project_brief (busca por 'KAG' en chunks)
echo ""
echo "6. project_brief(name='KAG')"
RESP=$(call_tool "project_brief" '{"name":"KAG"}')
TOTAL=$(echo "$RESP" | grep -o '"total_chunks":[0-9]*' | head -1)
echo "   $TOTAL"
echo "$RESP" | grep -q '"total_chunks"' && report PASS || report FAIL

# 7. cross_links
echo ""
echo "7. cross_links(topic='MariaDB')"
RESP=$(call_tool "cross_links" '{"topic":"MariaDB","limit":10}')
TOTAL=$(echo "$RESP" | grep -o '"type":"' | wc -l)
echo "   Total results: ${TOTAL}"
[ "$TOTAL" -gt 0 ] && report PASS || report FAIL

# 8. grafo: link_add + grafo_vecinos
echo ""
echo "8. grafo: link_add then grafo_vecinos"
RESP=$(call_tool "link_add" '{"from_id":"decision:test-1","to_id":"decision:test-2","relation":"implements","actor":"smoke"}')
echo "$RESP" | grep -q '"relation_id"' && report "link_add PASS" || report "link_add FAIL"
RESP=$(call_tool "grafo_vecinos" '{"entity_id":"decision:test-1","depth":1}')
NEIGHBORS=$(echo "$RESP" | grep -o '"id":"[^"]*"' | wc -l)
echo "   Neighbors: ${NEIGHBORS}"
[ "$NEIGHBORS" -ge 1 ] && report PASS || report FAIL

# 9. kag_buscar con cross_refs
echo ""
echo "9. kag_buscar(query='KAG', cross_refs=true, hop_depth=1)"
RESP=$(call_tool "kag_buscar" '{"query":"MariaDB","limit":5,"cross_refs":true,"hop_depth":1}')
echo "   $(echo "$RESP" | head -c 100)..."
echo "$RESP" | grep -q '"isError":false' && report PASS || report FAIL

# Cleanup test relation (H11 fix: source /etc/mcp-memoria/db.env)
sudo -u rodrigo env /opt/mcps/memoria/.venv/bin/python << 'PYEOF'
import os, sys
if os.path.exists('/etc/mcp-memoria/db.env'):
    for line in open('/etc/mcp-memoria/db.env').read().splitlines():
        line = line.strip()
        if '=' in line and not line.startswith('#'):
            k, _, v = line.partition('=')
            os.environ.setdefault(k.strip(), v.strip())
sys.path.insert(0, '/opt/mcps/memoria/src')
from memoria_mcp import db
n = db.write_one("DELETE FROM mm_relations WHERE from_id LIKE %s", ("decision:test%",))
print(f'   cleanup: {n} test relations removed')
PYEOF

echo ""
echo "===== RESULT: $PASS passed, $FAIL failed ====="
[ "$FAIL" -eq 0 ] || exit 1