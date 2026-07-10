# mcp-memoria — Modo desarrollo activo (2026-07-02)

> **Audience:** agente Claude Code en secops, sesión autónoma con freepass de Rodrigo.
> **Owner:** Rodrigo (aprobó todas las ideas de IDEAS.md).
> **Modo:** desarrollo Stage 1 → Stage 7. Gate formal en [MOP-352](file:///home/rodrigo/mcp-inter-proyecto/mop-mcp/workspace/workspace/MOP-352.md) (state: EN_CURSO, transition_id 1012).

---

## Stack target locked (v3)

- **Lenguaje:** Python 3.14 full (sin Node.js).
- **HTTP framework:** FastAPI 0.139 + uvicorn 0.49 + fastmcp 3.4.
- **DB:** MariaDB 11.8.6 LOCAL (secops :3306), schema `mcp_memoria` con prefijo `mm_` (D1).
- **Embeddings:** `paraphrase-multilingual-MiniLM-L12-v2` (384 dim, multilingüe ES/EN, Apache-2.0).
- **Auth:** Tailscale WhoIs + Bearer.
- **Puerto:** 9092.
- **Privacidad física:** allowlist de paths (NO MEMORY/USER/SOUL/IDENTITY/AGENTS/briefing).
- **HA:** rsync tar.gz a geo + tars (Stage 6).

## Patrón omni-mcp a replicar (conceptualmente, no copy-paste)

- KAG (auto-chunk + cross-refs + feedback loop) → `chunker.py` + `search.py` Stage 2.
- Grafo BFS 1-3 saltos → `grafo.py` Stage 3.
- Bibliotecario LLM merge → `bibliotecario.py` Stage 4.
- Cosine + keyword boost + RRF → `search.py` Stage 2.
- BLOB storage + Python cosine → `db.py` + `search.py` Stage 1-2.

## Estado gate

✅ **Goal activo.** Gate formal en MOP-352 (state EN_CURSO, t1012). Rodrigo aprueba todas las ideas de [IDEAS.md](file:///opt/mcps/memoria/IDEAS.md). Sin criterios pendientes en goal.md — el hook no interrumpe.

## Reglas duras (siguen vigentes)

- NO leer MEMORY/USER/SOUL/IDENTITY/AGENTS/briefing/contactos/memory/sessions.
- Wazuh loggea deploys — coordinamos Stage 6 con consumer.
- Permisos 2775 setgid grupo `mcps` para archivos nuevos en `/opt/mcps/memoria/`.
- Backups innegociables (Stage 6 task).
- Test `test_no_personal_leak` es gate crítico — si falla, NO deployar.

## Pendiente de Stage 1 (esta sesión)

1. Limpiar código viejo incompatible (vec.py v1 era sqlite-vec → wipe).
2. `db.py` con mysql.connector / aiomysql pool local.
3. `init_schema.py` que crea DB `mcp_memoria` + 6 tablas `mm_*`.
4. `embed.py` ajustado para guardar embedding en MariaDB BLOB (no sqlite-vec).
5. `chunker.py` port conceptual de autoChunkAndIndex.
6. `tests/test_no_personal_leak.py` con 5 tests.
7. `pip install -e .` + `pytest tests/test_no_personal_leak.py` → exit 0.
8. Reportar Stage 1 done vía `mop_set_body` MOP-352.