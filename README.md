# mcp-memoria

Memoria de proyectos compartida. MCP server gemelo de `mop-mcp` pero para conocimiento: decisiones, lecciones, ADRs, links entre proyectos/ideas.

## Quick reference

- **Endpoint target:** `http://secops:9092/mcp` (HTTP, JSON-RPC sobre Streamable HTTP)
- **Stack:** Python 3.12 + FastAPI + uvicorn (replica mop-mcp v3.4.2)
- **Privacidad:** allowlist de paths (NO MEMORY/USER/SOUL/IDENTITY/AGENTS/briefing)
- **HA:** backup diario a geo + tars vps (2 destinos, sin OCI por ahora)
- **Embeddings + vector store** (decisión 2026-07-01 corregida: sistema de memoria de la organización, requiere calidad)
- **Lifecycle:** 1 año (compromiso de Rodrigo)
- **Status:** PLAN — discovery completo, listo para implementación

## Docs en este directorio

- `PLAN.md` — plan completo: decisiones, stack, arquitectura, tools, tasks, riesgos, criterios de éxito
- `SECURITY.md` — privacy boundaries (qué lee y qué NO lee, test de no-leak)
- `OPEN_QUESTIONS.md` — 4 puntos pendientes antes de implementar

## Tools que va a exponer (9)

- `decision_list` / `decision_get` — decisiones técnicas
- `lesson_list` / `lesson_get` — lecciones aprendidas
- `adr_get` — ADRs (Architecture Decision Records)
- `project_brief` — resumen por proyecto
- `cross_links` — entidades que mencionan un topic
- `link_add` / `link_list` — vincular entidades (append-only log)

## Sources permitidos

- `~/.openclaw/workspace/kb/{decisions,lessons,jobs,concepts,wiki}/`
- `~/.openclaw/workspace/04-decisions/`
- `~/.openclaw/workspace/clientes/*/decisions.md`

**NO lee (denylist explícito):** MEMORY.md, USER.md, SOUL.md, IDENTITY.md, AGENTS.md, briefing/, memory/sessions/, clientes/*/contactos*

## Cómo deployar (cuando se implemente)

```bash
cd /opt/mcps/memoria
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e .
sudo systemctl mcp-memoria
curl http://secops:9092/health
```
