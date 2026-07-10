# mcp-memoria — Sistema de memoria de la organización (REDISEÑO v3 — 2026-07-02)

**MOP-352** · EN_CURSO · Risk: ALTO · P2

> **Rediseño v3 tras auditoría 2026-07-02.** El plan original (Stage 0 RESEARCH.md) propuso
> sqlite-vec + 9 tools minimalistas. **Insatisfactorio**:
> 1. No nombró MariaDB (la base real de mop-mcp y omni-mcp).
> 2. Re-inventó lo que omni-mcp ya tiene validado (KAG, auto-chunk, grafo, bibliotecario).
> 3. Subdimensionó el scope (9 tools vs ~26 que omni ya probó).
>
> **Decisión v3 (post-discusión con Rodrigo):**
> - **Full Python** (alejado de Node.js — no copy-paste, solo patrón conceptual de omni-mcp).
> - **MariaDB solo local** en secops (sin dual-pool remote+local por ahora). Replica a otros mariadb en fase futura.
> - **Schema separado** (D1): DB `mcp_memoria`, prefijo `mm_`. No comparte nada con omni-mcp.
> - **13 tools kb-specific** (no las 26 de omni, no las 9 de mi v1).

---

## Discovery (rediscubierto 2026-07-02)

### Código/config revisado (read-only, NO se reusa runtime)

**omni-mcp (`/home/cloudops/omni-mcp/` vía SSH `cloudops@100.112.255.59`):**

- `server.js` (1517 líneas) — **referencia conceptual**. Stack a replicar.
- `bibliotecario.cjs` (9.3 KB) — **referencia conceptual** del curador LLM-based.
- `embed_local.py` (380 bytes) — embeddings locales fallback.

Patrones omni-mcp que **se traducen a Python** (no se copian):
- **DDL idempotente** en `ensureTables()` → patrón `CREATE TABLE IF NOT EXISTS` en `db.py`.
- **`autoChunkAndIndex(slug, content)`** (~50 LOC) → port a Python en `chunker.py`.
- **`cosineSearch(pool, ...)` con keyword boost +0.15** → port a Python en `search.py`.
- **`grafo_vecinos` BFS 1-3 saltos** → port a SQL recursivo en `grafo.py`.
- **Bibliotecario con LLM merge** (MiniMax M3 / Gemini fallback) → port a `bibliotecario.py`.

**mop-mcp (`/home/rodrigo/mcp-inter-proyecto/mop-mcp/`):**

- `server.py` (4800+ líneas) — patrón auth + transport FastAPI + lifespan.
- `internal/auth/middleware.py` — **template a copiar** (Tailscale WhoIs + Bearer).

**Auditoría de devices/hosts:**

| Máquina | Rol | Estado | Cambio |
|---|---|---|---|
| `secops` (Tailscale 100.72.183.50) | MCP host primario | Ubuntu 26.04, MariaDB 11.8.6 local :3306, sin mcp-memoria | Deploy completo (Stage 5) |
| `vps-geo-noc` (Tailscale 100.112.255.59) | KB source (rsync) + futuro DR backup | omni-mcp + workspace + `~/.openclaw/workspace/kb/` | rsync kb → secops + (futuro) MariaDB replica |
| `vps-tars` (Tailscale 100.77.242.85) | DR backup target | sin mcp-mcp | (futuro) MariaDB replica |

**Conflict checks:** puerto 9092 libre en secops (`ss -tlnp` confirmado), grupo `mcps` creado,
`geo`+`rodrigo` miembros, MariaDB local con DB `mcp_memoria` por crear, ufw permite solo SSH
actualmente — **bloquea Stage 5 hasta agregar `100.64.0.0/10` + `10.255.255.0/24` a 9092**.

**Outputs a NO tocar (privacidad):**

- `/home/cloudops/omni-mcp/` — privado de Geo. **Solo el schema + patterns se replican conceptualmente** (no se reusa runtime).
- `~/.openclaw/workspace/MEMORY.md`, `USER.md`, `SOUL.md`, `IDENTITY.md`, `AGENTS.md` — denylist estricta.

### Stack decidido (v3 — solo Python, solo local MariaDB)

| Capa | Decisión | Origen |
|---|---|---|
| **Lenguaje** | **Python 3.14 (full)** | igual mop-mcp (consistencia operacional). **Sin código Node.js.** |
| **HTTP framework** | FastAPI 0.139 + uvicorn 0.49 + fastmcp 3.4 | igual mop-mcp |
| **DB** | **MariaDB 11.8.6 local** (secops :3306 localhost, ya corriendo) — **SOLO LOCAL, sin dual-pool** | omni-mcp stack conceptual + secops ya tiene el servicio |
| **DB driver** | `mysql.connector` o `aiomysql` | omni-mcp usa mysql2 (Node), Python equivalente |
| **DB name** | `mcp_memoria` (separada de la DB de omni-mcp si la hubiera) | **D1**: schema separado, no comparte nada |
| **Prefijo tablas** | `mm_` (entity_chunks → `mm_entity_chunks`, etc.) | **D1**: prefijos distintos, no colisión |
| **Embeddings** | `fastembed` con `paraphrase-multilingual-MiniLM-L12-v2` (384 dim, Apache-2.0, multilingüe ES/EN) | RESEARCH.md §4 decisión (sigue válida) |
| **Auto-chunk** | port a Python de omni-mcp `autoChunkAndIndex()` (~50 LOC) | omni-mcp/server.js:376 — **port conceptual, no copy-paste** |
| **Grafo** | port a Python de `grafo_vecinos` BFS (1-3 saltos) | omni-mcp/server.js:619 |
| **Cross-refs** | port `kag_buscar(cross_refs=true, hop_depth=0-2)` | omni-mcp/server.js:698 |
| **Feedback loop** | port `kag_evaluar(useful/not_useful/partially_useful)` | omni-mcp/server.js:732 |
| **Curador** | port `bibliotecario.cjs` a Python (`bibliotecario.py`) — merge LLM de conflictos | omni-mcp/bibliotecario.cjs — **port conceptual, no copy-paste** |
| **Auth** | Tailscale WhoIs + Bearer (`/etc/flow-gateway/tokens.env`) | mop-mcp patrón |
| **Privacidad física** | allowlist de paths (NO MEMORY/USER/SOUL/IDENTITY/AGENTS/briefing/memory/contactos) | mop-mcp pattern, NO en omni |
| **Deploy** | systemd + UFW (no Docker) + HA backup tar.gz a geo + tars | mop-mcp pattern, NO en omni |
| **Puerto** | `9092` (correlativo a 9090 mop-mcp, 9080 mcp-monitoreo) | PLAN §1 |

### Fase futura (después de Stage 6 — explícitamente NO en este plan)

> **Cuando mcp-memoria esté estable en secops, se replica a otros mariadb.**
> Esa fase es un MOP aparte (futuro MOP-X), no parte de MOP-352.

- MariaDB **dual-pool** (local + remote GCP, igual omni-mcp).
- Replicación binlog a `mcp-memoria` DB en `vps-geo-noc` + `vps-tars`.
- HA con failover si secops cae.

### Schema MariaDB (`mcp_memoria` DB, prefijo `mm_`)

```sql
-- DB separada
CREATE DATABASE IF NOT EXISTS mcp_memoria CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- Entidades (grafo)
CREATE TABLE IF NOT EXISTS mm_entities (
  id VARCHAR(64) PRIMARY KEY,
  name VARCHAR(200) NOT NULL,
  type VARCHAR(50) NOT NULL,
  attributes JSON,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_type (type),
  FULLTEXT INDEX ft_name (name)
);

-- Relaciones (grafo)
CREATE TABLE IF NOT EXISTS mm_relations (
  relation_id BIGINT AUTO_INCREMENT PRIMARY KEY,
  from_id VARCHAR(64) NOT NULL,
  to_id VARCHAR(64) NOT NULL,
  relation_type VARCHAR(20) NOT NULL,
  notes TEXT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uniq_rel (from_id, to_id, relation_type),
  INDEX idx_from (from_id),
  INDEX idx_to (to_id)
);

-- Chunks KAG (auto-chunk + embedding)
CREATE TABLE IF NOT EXISTS mm_entity_chunks (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  page_slug VARCHAR(200) NOT NULL,
  chunk_index INT NOT NULL,
  heading VARCHAR(200),
  chunk_text MEDIUMTEXT NOT NULL,
  entities_referenced JSON,
  word_count INT,
  embedding BLOB,  -- Float32Array bytes (384 dim)
  scope VARCHAR(20),  -- decisions|lessons|jobs|concepts|wiki|adrs|clientes
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uniq_chunk (page_slug, chunk_index),
  INDEX idx_slug (page_slug),
  INDEX idx_scope (scope),
  FULLTEXT INDEX ft_chunk (chunk_text, heading)
);

-- Feedback loop (kag_evaluar)
CREATE TABLE IF NOT EXISTS mm_search_feedback (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  query_text VARCHAR(500) NOT NULL,
  chunk_id VARCHAR(100) NOT NULL,
  page_slug VARCHAR(200),
  feedback ENUM('useful','not_useful','partially_useful') NOT NULL,
  agent_signature VARCHAR(100),
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_query (query_text(100)),
  INDEX idx_chunk (chunk_id)
);

-- Conflict queue (bibliotecario)
CREATE TABLE IF NOT EXISTS mm_conflict_queue (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  entity_type VARCHAR(20) NOT NULL,
  entity_id VARCHAR(255) NOT NULL,
  gcp_content MEDIUMTEXT,
  node_content MEDIUMTEXT,
  resolution ENUM('pending','merged','kept','skipped') DEFAULT 'pending',
  resolved_content LONGTEXT,
  resolved_by VARCHAR(50),
  notes TEXT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  resolved_at TIMESTAMP NULL,
  INDEX idx_resolution (resolution)
);

-- Log de búsquedas (métricas)
CREATE TABLE IF NOT EXISTS mm_search_log (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  query_text VARCHAR(500) NOT NULL,
  method VARCHAR(20) NOT NULL,
  latency_ms INT NOT NULL,
  results_count INT NOT NULL,
  cross_refs BOOLEAN DEFAULT FALSE,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_created (created_at)
);
```

### Plan de integración

**Module layout (`/opt/mcps/memoria/src/memoria_mcp/`):**

```
├── server.py            # FastAPI + FastMCP, lifespan combinado
├── auth.py              # Tailscale WhoIs + Bearer (copia patrón mop-mcp)
├── paths.py             # allowlist físico (privacy)
├── db.py                # MariaDB LOCAL pool (aiomysql) — sin dual-pool por ahora
├── embed.py             # fastembed wrapper async
├── chunker.py           # port conceptual autoChunkAndIndex (heading split, entity match)
├── search.py            # cosine + keyword boost + cross-refs
├── grafo.py             # port grafo_vecinos BFS (SQL recursivo)
├── bibliotecario.py     # port bibliotecario (LLM merge conflictos, MiniMax/Gemini)
├── observability.py     # logging + metrics
├── health.py            # /health, /metrics
├── instance.py          # identidad persistida
└── tools/
    ├── decisions.py     # decision_list, decision_get
    ├── lessons.py       # lesson_list, lesson_get
    ├── adr.py           # adr_get (0001, 0012, etc.)
    ├── project.py       # project_brief
    ├── links.py         # cross_links, link_add, link_list
    ├── grafo.py         # entity_añadir, grafo_vecinos
    ├── kag.py           # kag_buscar, kag_evaluar
    └── bibliotecario.py # bibliotecario_run, conflict_list, conflict_resolve
```

**Tools totales (~13, kb-specific):**

1. `decision_list(scope)` / `decision_get(id)` — kb/decisions
2. `lesson_list(topic)` / `lesson_get(id)` — kb/lessons
3. `adr_get(number)` — 04-decisions/NNNN
4. `project_brief(name)` — agrega decisiones+lessons+ADRs+MOPs por proyecto
5. `cross_links(topic)` — entidades que mencionan topic
6. `link_add(from, to, relation)` / `link_list(entity_id)` — graph edges
7. `entity_añadir(id, name, type, attrs)` — añade nodo al grafo
8. `grafo_vecinos(entity_id, depth)` — BFS 1-3 saltos
9. `kag_buscar(query, scope, cross_refs, hop_depth)` — búsqueda semántica + cross-refs
10. `kag_evaluar(query, chunk_id, feedback)` — feedback loop
11. `bibliotecario_run(max_conflicts)` — trigger curador
12. `conflict_list(state)` / `conflict_resolve(id, action, notes)` — gestión de conflictos

### Riesgos identificados

| # | Riesgo | Mitigación |
|---|---|---|
| R1 | Path traversal expone archivos privados | allowlist + symlink check + `test_no_personal_leak` gate de CI |
| R2 | Token leak = acceso lectura/escritura a toda la kb | Tokens por scope; rotación SIGHUP; audit log |
| R3 | Cambios en kb/ no se reflejan inmediatamente | Re-read on every call (Q7 approach A) — kb/ chica |
| R4 | MariaDB local se corrompe | Backup rsync tar.gz + restore desde geo (Stage 5 task 12) |
| R5 | MariaDB schema entra en colisión con omni-mcp | Schema separado `mm_` prefix + DB `mcp_memoria` (D1) |
| R6 | Wazuh HIDS activo loggea deploys | Avisar al consumer antes de Stage 5; documentar en CHANGELOG |
| R7 | curl/libcurl CVEs sin parchear (21 paquetes upgradable, 4 críticos) | `sudo unattended-upgrades` antes de Stage 5 |
| R8 | Auto-chunk falla con headings mal formados | Tolerante: chunks con heading "general" fallback; warnings loggeados |
| R9 | Grafo crece sin bound (entidades huerfanas) | Garbage collector weekly via systemd timer |
| R10 | Bibliotecario sin LLM key activo (MiniMax/Gemini) | Degraded mode: marca conflictos como `skipped` con reason |
| R11 | Embeddings cambian de versión | Pin `paraphrase-multilingual-MiniLM-L12-v2` exacto en pyproject.toml |
| R12 | Solo local MariaDB → single point of failure | HA backup tar.gz diario a geo + tars (Stage 5 task 12) |

---

## Goal

Construir el MCP server `mcp-memoria` en secops. Output final:
- 13 tools funcionales (decisions/lessons/ADRs/projects/links/grafo/kag/bibliotecario)
- Stack full Python con MariaDB local (sin dual-pool, sin Node.js)
- Schema separado `mcp_memoria` con prefijo `mm_` (D1)
- **Plus** lo que omni NO tiene: HTTP Streamable + allowlist físico + auth Tailscale + HA
- Tests pasando, especialmente `test_no_personal_leak`
- 12 acceptance criteria cumplidos

---

## Stages con gates (rediseño v3)

| Stage | Output | Tiempo | Depende de |
|---|---|---|---|
| 0 | RESEARCH.md (viejo, ahora superseded) | done | — |
| **0.5** | **Auditoría de omni-mcp + MOP-352 update** | **done** (2026-07-02) | — |
| 1 | pyproject.toml + MariaDB schema `mcp_memoria` + `db.py` (local pool) + `paths.py` + `embed.py` + `chunker.py` + `test_no_personal_leak` | 4h | 0.5 |
| 2 | Read tools (decisions/lessons/ADRs/project_brief/cross_links) + `search.py` (cosine + keyword boost) + tests | 3h | 1 |
| 3 | Grafo tools (entity_añadir/grafo_vecinos/link_add/link_list) + `grafo.py` + tests | 2h | 2 |
| 4 | KAG feedback (`kag_evaluar`) + `bibliotecario.py` + tests | 3h | 3 |
| 5 | Auth middleware (`auth.py`) + MCP transport (FastMCP HTTP) + tests | 2h | 4 |
| 6 | systemd + UFW + tokens + HA backup a geo + tars | 3h | 5 |
| 7 | E2E smoke + restore test + CHANGELOG + IMPLEMENTED | 2h | 6 |

**Total:** ~19h. 2 sesiones Claude Code 12h auto-mode.

---

## Acceptance criteria (12)

- [ ] `pip install -e .` exit 0 limpio
- [ ] `pytest tests/` exit 0 con `test_no_personal_leak` incluido (gate crítico)
- [ ] MariaDB DB `mcp_memoria` creada con 6 tablas `mm_*` + indexes
- [ ] `systemctl status mcp-memoria` muestra `active (running)`
- [ ] `curl http://secops:9092/health` retorna `{"status":"ok","db":"ok",...}`
- [ ] `decision_list(scope="decisions")` devuelve ≥10 entries
- [ ] `kag_buscar("Fase 1")` devuelve al menos 2 entidades con score
- [ ] `grafo_vecinos("decision:foo", depth=2)` devuelve ≥1 entidad vecina
- [ ] `link_add` appendea con ID único a `mm_relations`
- [ ] Sin Bearer token → 401; con Bearer válido → 200
- [ ] Test `test_no_personal_leak` pasa (0 leaks en keywords sensibles)
- [ ] Backup diario a geo + tars verificado (2 destinos)
- [ ] CHANGELOG.md actualizado; `kb/IMPLEMENTED.md` en workspace vps-geo-noc actualizado

---

## Path

- **Repo/server:** `/opt/mcps/memoria/`
- **PLAN (reescribir):** `/opt/mcps/memoria/PLAN.md` (reemplaza versión vieja)
- **Research (superseded):** `/opt/mcps/memoria/RESEARCH.md` (mantener como histórico)
- **ALIGNMENT:** `/opt/mcps/memoria/ALIGNMENT.md` (actualizar con MOP-352 v3 + nuevo plan)
- **Source of truth omni-mcp (read-only conceptual, NO runtime):** `/home/cloudops/omni-mcp/` vía SSH
- **Resumen operativo secops:** `/opt/SECOPS-OPERATIONAL-SUMMARY.md` (snapshot 2026-07-02)

---

## Cambios vs versiones anteriores

| Campo | v1 (research viejo) | v2 (propuesta inicial v3) | **v3 (final)** |
|---|---|---|---|
| Lenguaje | Python | Python + pattern Node | **Python (full, sin Node)** |
| DB | sqlite-vec | MariaDB local + remote dual-pool | **MariaDB local solo (D1)** |
| Schema | n/a | prefijo `mm_` | **prefijo `mm_` (D1)** |
| Tools | 9 | 13 | **13** |
| Curador | no | port bibliotecario | **port bibliotecario (full Python)** |
| Grafo | no | grafo_vecinos BFS | **grafo_vecinos BFS** |
| Cross-refs | no | sí | **sí** |
| Feedback loop | no | sí | **sí** |
| Replica otros mariadb | n/a | implícito en dual-pool | **fase futura (otro MOP)** |
| Tiempo total | 12-16h | 17h | **19h** |

---

## Justificación del rediseño v3

- **v1** subestimó el problema: inventó 9 tools y sqlite-vec cuando omni ya tenía 26 tools + MariaDB + KAG validados.
- **v2** replicaba el patrón omni-mcp muy de cerca, incluyendo dual-pool con remote GCP — **fuera de scope** para esta primera versión local.
- **v3** mantiene la riqueza del patrón omni-mcp (KAG, grafo, curador, feedback) pero **sin el acoplamiento runtime** ni el dual-pool remoto. Es la versión "local-first" — la replica a otros mariadb es trabajo futuro.