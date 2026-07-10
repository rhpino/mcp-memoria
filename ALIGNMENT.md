# ALIGNMENT.md — Docs ↔ MOP ↔ Realidad (snapshot v3 — 2026-07-02)

> **Status:** Snapshot post-rediseño v3 (después de auditoría omni-mcp).
> **MOP trackeador:** MOP-352 (EN_CURSO, transition_id 1012).
> **Cambio principal:** plan viejo (sqlite-vec + 9 tools) reemplazado por rediseño v3 (MariaDB local + 13 tools kb-specific + port omni-mcp).

---

## 1. Inventario: docs vs MOP-352 vs filesystem

| Doc | Path | Estado real | Drift |
|---|---|---|---|
| **PLAN.md** | `/opt/mcps/memoria/PLAN.md` | v3 rediseño (319 líneas, full Python + MariaDB local D1) | NO |
| **PLAN.md.old.bak** | `/opt/mcps/memoria/PLAN.md.old.bak` | Backup v1 (846 líneas, sqlite-vec + 9 tools) | histórico |
| **RESEARCH.md** | `/opt/mcps/memoria/RESEARCH.md` | marcado SUPERSEDED 2026-07-02; decisión original mantenida para auditoría | NO |
| **SECURITY.md** | `/opt/mcps/memoria/SECURITY.md` | Sin cambios — privacy boundaries siguen vigentes | NO |
| **OPEN_QUESTIONS.md** | `/opt/mcps/memoria/OPEN_QUESTIONS.md` | Q1-Q8 cerradas, sin cambios | NO |
| **goal.md** | `/opt/mcps/memoria/goal.md` | v2 (modo investigación libre, sin gate bloqueante) | NO |
| **README.md** | `/opt/mcps/memoria/README.md` | Sin cambios — referencia rápida | NO |
| **SECOPS-OPERATIONAL-SUMMARY.md** | `/opt/SECOPS-OPERATIONAL-SUMMARY.md` | Snapshot 2026-07-02 (Ubuntu 26.04, MariaDB 11.8.6 local, Wazuh activo) | NO |
| **MOP-352 (mcp-mop)** | `/home/rodrigo/.../MOP-352.md` (workspace mcp-mop) | v757 body; state=EN_CURSO (t1012) | NO |

## 2. Estado de rediseño v3 (verificado 2026-07-02 02:00 UTC)

- ✅ Auditoría omni-mcp (`/home/cloudops/omni-mcp/` vía SSH directo `cloudops@100.112.255.59`)
- ✅ MOP-352 actualizado: discovery + plan template + body v757
- ✅ MOP-352 transicionado: PLAN → APROBADO (t1011) → EN_CURSO (t1012)
- ✅ PLAN.md reemplazado (846 → 319 líneas, v3)
- ✅ RESEARCH.md marcado SUPERSEDED
- ✅ goal.md reemplazado (modo investigación libre)
- ⏳ Stage 1 (pendiente)
- ⏳ IDEAS.md (pendiente — esta sesión)

## 3. Cambios v1 → v3

| Campo | v1 | **v3** |
|---|---|---|
| Lenguaje | Python | **Python full** (sin Node) |
| DB | sqlite-vec | **MariaDB 11.8.6 local** (secops :3306) |
| Schema | n/a | **`mcp_memoria` DB, prefijo `mm_`** (D1 separado) |
| Tools | 9 | **13** (decisions/lessons/ADRs/projects/links/grafo/kag/bibliotecario) |
| Embeddings | paraphrase-multilingual-MiniLM-L12-v2 (384 dim) | **igual** (sigue válido) |
| Curador | no | **port bibliotecario.cjs → bibliotecario.py** |
| Grafo | no | **grafo_vecinos BFS** |
| Cross-refs | no | **kag_buscar(cross_refs, hop_depth)** |
| Feedback loop | no | **kag_evaluar** |
| Replica a otros mariadb | n/a | **fase futura** (otro MOP) |
| Tiempo total | 12-16h | **19h** |

## 4. Decisiones heredadas del plan viejo

- **Q1 — Embeddings:** SÍ, `paraphrase-multilingual-MiniLM-L12-v2` (sigue válido).
- **Q2-Q8:** sin cambios.

## 5. Stages pendientes (del MOP-352 v757)

| Stage | Output | Estado |
|---|---|---|
| 1 | pyproject + MariaDB schema + db.py + paths.py + embed.py + chunker.py + test_no_personal_leak | pendiente |
| 2 | Read tools + search.py + tests | pendiente |
| 3 | Grafo tools + grafo.py + tests | pendiente |
| 4 | KAG feedback + bibliotecario.py + tests | pendiente |
| 5 | Auth + MCP transport + tests | pendiente |
| 6 | systemd + UFW + tokens + HA | pendiente |
| 7 | E2E + restore + docs | pendiente |

## 6. Acciones para alinear (drift identificados)

1. **/opt/mcps/README.md** (en secops) — al día con mop-mcp + mcp-monitoreo, NO menciona mcp-memoria. Actualizar cuando Stage 6 deploy.
2. **IMPLEMENTED.md en workspace vps-geo-noc** — stale (7 jun), no menciona mcp-memoria. Actualizar Stage 7.
3. **Wazuh logs** — cualquier cambio de firewall/puerto queda loggeado. Stage 6 coordina con consumer.
4. **curl/libcurl CVEs** (4 críticos) — `sudo unattended-upgrades` antes de Stage 6.

## 7. Riesgos vivos

R1-R12 listados en MOP-352 §Riesgos. Top 3 ahora:
- **R5** (colisión schema omni-mcp) — mitigado con D1.
- **R12** (single point of failure MariaDB local) — mitigado con HA backup Stage 6.
- **R6** (Wazuh loggea deploy) — coordinamos Stage 6.

---

**MOP trackeador:** MOP-352 (state: EN_CURSO, transition_id 1012)
**Próxima revisión:** después de Stage 1 o cuando aparezca drift.