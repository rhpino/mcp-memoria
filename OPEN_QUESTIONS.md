# OPEN_QUESTIONS.md — mcp-memoria

Lo que falta definir antes de implementar. Cada pregunta es **bloqueante** o **decisión posterior** según nota.

---

## Q1. ¿Embeddings en el futuro? [RESUELTO 2026-07-01]

**Estado:** **SÍ, embeddings obligatorios.**

**Razón del cambio:** Rodrigo 2026-07-01: "si lo vamos a hacer bien este sera el sistema de memoria de la organizacion, debe ser con investigacion de partida".

**Lo que se hace:**

- Research-first (Fase 0) compara vector stores + embedding models
- Output: `RESEARCH.md` con stack recomendado
- Implementación: hybrid search (graph + vector) con embeddings serios

**Lo que ya NO es válido:**

- "Sin embeddings" como decisión (era over-simplification)
- "Sumar después" — ya no es opcional, es parte del MVP
- "Búsqueda semántica no es prioridad" — sí lo es, si va a ser la memoria de la org

---

## Q2. ¿Quién popula `kb/index.json`? [BLOQUEANTE — RESUELTO 2026-07-01]

**Estado:** **D. Migración inicial de mop-mcp + auto-detect opcional.**

**Decisión Rodrigo 2026-07-01 (en sesión de plan):**

- **Stage 3 task 7b:** script `scripts/migrate-mop-links.py` corre al startup del server
- Importa TODAS las relaciones de mop-mcp a `kb/index.json` (idempotente, no duplica)
- Después mop-mcp es source of truth para relaciones MOP↔MOP/MOP↔ADR
- Auto-detect (cron opcional, Stage 5+) puede sugerir links nuevos basados en menciones cruzadas en kb/, pero requiere confirmación humana

**Por qué:** No partimos de cero. La data de mop-mcp ya está curada por Rodrigo/Geo.

---

## Q3. ¿Migración de relaciones existentes de mop-mcp? [BLOQUEANTE — RESUELTO 2026-07-01]

**Estado:** **A. Importación única al startup + sync diario.**

**Decisión Rodrigo 2026-07-01:**

- Script `scripts/migrate-mop-links.py` corre al startup, importa todas las relaciones mop-mcp
- Sync diario vía cron (Stage 5+): mop-mcp → kb-mcp es one-way, kb-mcp no escribe a mop-mcp
- Si mop-mcp schema cambia, actualizar el script de migración

**Por qué A y no B:** Live query (B) tiene latencia + acoplamiento runtime. C deja grafos separados, pero perdemos cross-links cross-domain.

---

## Q4. ¿Auth multi-tenant desde el inicio? [DECISIÓN POSTERIOR]

**Estado actual:** asumo `X-Memoria-Tenant` opcional, default `public`. ¿Vale?

**Por qué podría importar:** si en el futuro Rodrigo tiene clientes distintos (Paine, Entel, etc.) y quiere kb segregada por cliente, multi-tenancy ayuda.

**Por qué NO hacerlo hoy:** suma complejidad (tenant table, header propagation, tests). El caso de uso inmediato es single-tenant.

**Opciones:**

A. **Single-tenant ahora**, schema permite sumar tenant después (sin breaking change)
B. **Multi-tenant desde el inicio** (más complejo pero ya listo)
C. **Single-tenant forever** (decisión consciente de no sumar)

**Mi voto:** A. Schema con `tenant` opcional en cada tool, default `public`. Si se necesita, se filtra.

**Lo que necesito de Rodrigo:** OK al approach A, o decisión B/C.

---

## Q5. ¿Tailscale only o LAN? [BLOQUEANTE — RESUELTO 2026-07-01]

**Estado:** **Tailscale only.**

**Decisión Rodrigo 2026-07-01:**

- UFW: `100.64.0.0/10` (CGNAT Tailscale) + `10.255.255.0/24` (VPN)
- LAN casa `172.16.200.0/24` accede vía Tailscale (los nodos de Rodrigo están en Tailscale, conectividad ya probada)
- IP pública de secops (`192.99.247.209`) **NO se expone** para este MCP

**Endpoint final:** `http://secops:9092/mcp` (hostname Tailscale, NO IP pública)

---

## Q6. ¿Qué pasa con el campo `actor` en links? [DECISIÓN PEQUEÑA]

**Estado actual:** planeé `actor: "geo"` o `actor: "claude-code"` o `actor: "codex"`. ¿Vale o queremos otro formato?

**Opciones:**

A. `actor` = nombre del agente que creó el link (string libre)
B. `actor` = firma completa (ej: `claude:geo@vps-geo-noc:default:1.0/geo-go`)
C. `actor` = enum fijo (`geo`, `claude`, `codex`, `rodrigo`)

**Mi voto:** A con validación contra allowlist. Simple, suficiente.

**Lo que necesito de Rodrigo:** OK o ajuste.

---

## Q7. ¿Refresh automático cuando kb/ cambia? [DECISIÓN POSTERIOR]

**Estado actual:** planeé "re-read on every call" o "file watcher". ¿Cuál?

**Opciones:**

A. **Re-read cada call** — siempre fresh, costo: scan de disco en cada query. Para kb/ ~50 docs es OK.
B. **File watcher (inotify)** — watcher en `kb/`, recarga cache cuando cambia. Más complejo, pero eficiente.
C. **TTL cache** — recarga cada 60s. Balance simple.

**Mi voto:** A. Simple, kb/ es chico.

**Lo que necesito de Rodrigo:** OK o decisión B/C.

---


---

## Q8. ¿HA: copia a geo y tars vps? [BLOQUEANTE — RESUELTO 2026-07-01]

**Estado:** **SÍ, HA con replica a geo (vps-geo-noc) y tars vps.**

**Decisión Rodrigo 2026-07-01:** "si debe tener HA en base de datos (partimos con copia a geo y a tars vps)".

**Topología:**

```
        secops (primary)
            ├─ daily push ─→ geo@vps-geo-noc:/var/backups/  [DR]
            └─ daily push ─→ tars@vps-tars:/var/backups/  [DR]
```

**Restore hierarchy:** geo (~24h lag) > tars (~24h lag). **OCI descartado** por ahora (Rodrigo 2026-07-01).

**Stack:** rsync sobre SSH + systemd timer (no cron daemon).

**Estimación adicional:** +1h implementación backup script + config.

## Resumen

| # | Pregunta | Tipo | Bloqueante |
|---|---|---|---|
| Q1 | ¿Embeddings futuro? | Decisión posterior | NO |
| Q2 | ¿Quién popula `kb/index.json`? | Decisión | ✅ D (migración mop-mcp + auto-detect) |
| Q3 | ¿Migrar relaciones de mop-mcp? | Decisión | ✅ A (importar + sync diario) |
| Q4 | ¿Multi-tenant? | Decisión posterior | NO |
| Q5 | ¿Tailscale o LAN para acceso? | Conectividad | ✅ Tailscale only |
| Q6 | ¿Formato `actor`? | Detalle | NO (defaulteable) |
| Q7 | ¿Refresh strategy? | Decisión | NO (defaulteable A) |

**Bloqueantes para implementar:** Q2, Q3, Q5.

Si me confirmás esos 3 (con mis votos como default), arranco implementación.
