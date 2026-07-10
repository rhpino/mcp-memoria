"""server.py — mcp-memoria FastAPI + FastMCP server.

Stack: FastAPI 0.139 + uvicorn 0.49 + fastmcp 3.4.
- 13 tools kb-specific.
- HTTP /mcp endpoint via FastMCP (path /mcp preserved).
- /health + /metrics.
- Tailscale WhoIs + Bearer auth middleware.
- Lazy init: db.init_schema() + tokens se carga on-first-use (no lifespan race).
"""
from __future__ import annotations

import logging
import os
import threading

from fastapi import FastAPI
from fastmcp import FastMCP

from . import config
from .observability import setup_logging
from . import auth as auth_mod, db, instance, paths
from .health import router as health_router
from .tools import decisions, lessons, adr, project, links, grafo, kag, bibliotecario as bib_tool, wiki

setup_logging()
log = logging.getLogger("memoria_server")


def _bootstrap_config() -> None:
    """Load .env and fail fast when critical runtime config is missing."""
    config.load_dotenv()
    config.validate_required_env()


_bootstrap_config()

MCP_NAME = "mcp-memoria"
MCP_PORT = int(os.environ["MCP_PORT"])


# ── Lazy init (idempotente, thread-safe) ──────────────────────────
_init_lock = threading.Lock()
_initialized = False


def _ensure_init():
    """Inicializa DB + tokens + instance la primera vez. Idempotente."""
    global _initialized
    if _initialized:
        return
    with _init_lock:
        if _initialized:
            return
        try:
            instance.get_or_create_instance()
            paths.validate_allowlist()
            db.init_schema()
            auth_mod._load_tokens()
            _initialized = True
            log.info("mcp_memoria_initialized")
        except Exception as e:
            log.error("mcp_memoria_init_failed", extra={"error": str(e)})


# ── FastMCP setup ─────────────────────────────────────────────────
mcp = FastMCP(MCP_NAME)


# ── Tools (13 kb-specific) ────────────────────────────────────────
@mcp.tool(name="decision_list", description="Lista decisiones técnicas.")
async def tool_decision_list(scope: str = "decisions", tag: str | None = None) -> list[dict]:
    _ensure_init()
    return await decisions.list_decisions(scope=scope, tag=tag)


@mcp.tool(name="decision_get", description="Devuelve el contenido de una decisión por id.")
async def tool_decision_get(id: str) -> dict:
    _ensure_init()
    return await decisions.get_decision(id=id)


@mcp.tool(name="lesson_list", description="Lista lecciones aprendidas.")
async def tool_lesson_list(topic: str | None = None) -> list[dict]:
    _ensure_init()
    return await lessons.list_lessons(topic=topic)


@mcp.tool(name="lesson_get", description="Devuelve el contenido de una lección por id.")
async def tool_lesson_get(id: str) -> dict:
    _ensure_init()
    return await lessons.get_lesson(id=id)


@mcp.tool(name="adr_get", description="Devuelve un ADR por número (0001, 0012, etc.).")
async def tool_adr_get(number: int) -> dict:
    _ensure_init()
    return await adr.get_adr(number=number)


@mcp.tool(name="project_brief", description="Resumen por proyecto.")
async def tool_project_brief(name: str) -> dict:
    _ensure_init()
    return await project.get_brief(name=name)


@mcp.tool(name="cross_links", description="Entidades que mencionan un topic.")
async def tool_cross_links(topic: str, limit: int = 20) -> list[dict]:
    _ensure_init()
    return await links.cross_links(topic=topic, limit=limit)


@mcp.tool(name="link_add", description="Crea un link entre entidades.")
async def tool_link_add(from_id: str, to_id: str, relation: str, actor: str, notes: str = "") -> dict:
    _ensure_init()
    return await links.add_link(from_id=from_id, to_id=to_id, relation=relation, actor=actor, notes=notes)


@mcp.tool(name="link_list", description="Lista las relaciones de una entidad.")
async def tool_link_list(entity_id: str) -> list[dict]:
    _ensure_init()
    return await links.list_links(entity_id=entity_id)


@mcp.tool(name="entity_añadir", description="Añade un nodo al grafo de entidades.")
async def tool_entity_añadir(id: str, name: str, type: str, attrs: dict | None = None) -> dict:
    _ensure_init()
    return await grafo.entity_añadir(id=id, name=name, type=type, attrs=attrs)


@mcp.tool(name="grafo_vecinos", description="BFS N saltos desde una entidad.")
async def tool_grafo_vecinos(entity_id: str, depth: int = 1, relation_type: str | None = None) -> list[dict]:
    _ensure_init()
    return await grafo.grafo_vecinos(entity_id=entity_id, depth=depth, relation_type=relation_type)


@mcp.tool(name="kag_buscar", description="Búsqueda KAG (vector + keyword + cross-refs + RRF).")
async def tool_kag_buscar(query: str, scope: str | None = None, cross_refs: bool = False,
                          hop_depth: int = 0, limit: int = 10) -> list[dict]:
    _ensure_init()
    return await kag.kag_buscar(query=query, scope=scope, cross_refs=cross_refs,
                                hop_depth=hop_depth, limit=limit)


@mcp.tool(name="kag_evaluar", description="Registra feedback de calidad.")
async def tool_kag_evaluar(query: str, chunk_id: int, feedback: str, page_slug: str = "") -> dict:
    _ensure_init()
    return await kag.kag_evaluar(query=query, chunk_id=chunk_id, feedback=feedback, page_slug=page_slug)


@mcp.tool(name="bibliotecario_run", description="Trigger curador: procesa conflictos pending.")
async def tool_bibliotecario_run(max_conflicts: int = 1) -> dict:
    _ensure_init()
    return await bib_tool.bibliotecario_run(max_conflicts=max_conflicts)


@mcp.tool(name="conflict_list", description="Lista conflictos.")
async def tool_conflict_list(state: str | None = None) -> list[dict]:
    _ensure_init()
    return await bib_tool.conflict_list(state=state)


@mcp.tool(name="conflict_resolve", description="Resuelve un conflicto manualmente.")
async def tool_conflict_resolve(conflict_id: int, action: str, notes: str = "") -> dict:
    _ensure_init()
    return await bib_tool.conflict_resolve(conflict_id=conflict_id, action=action, notes=notes)


# ── Wiki tools (MOP-398) ──────────────────────────────────────────
# 6 tools: help, listar, leer, escribir, historial, export.
# wiki_help es el ENTRY POINT — primer tool que un agente nuevo debe llamar.


@mcp.tool(
    name="wiki_help",
    description=(
        "ENTRY POINT del sistema wiki. LLAMÁ PRIMERO si no conocés mcp-memoria. "
        "Devuelve mapa de tools, scopes válidos, starter pages curadas, y tips "
        "de discovery (kag_buscar para búsqueda semántica, wiki_listar para browse). "
        "Si volvés sin saber qué hacer, llamá wiki_help() y leé la respuesta."
    ),
)
async def tool_wiki_help() -> dict:
    _ensure_init()
    return await wiki.wiki_help()


@mcp.tool(
    name="wiki_listar",
    description=(
        "Lista páginas wiki desde DB. Devuelve última versión + # chunks + "
        "path archive. ¿Primera vez? Llamá wiki_help() primero — tiene mapa "
        "completo + starter pages curadas."
    ),
)
async def tool_wiki_listar(scope: str | None = None, limit: int = 50) -> list[dict]:
    _ensure_init()
    return await wiki.wiki_listar(scope=scope, limit=limit)


@mcp.tool(
    name="wiki_leer",
    description=(
        "Lee una página wiki por slug desde DB. Append-only: cada slug tiene "
        "N versiones. Si no conocés qué leer, llamá wiki_help() — sugiere "
        "starter pages. Para búsqueda libre: kag_buscar(query='tema')."
    ),
)
async def tool_wiki_leer(slug: str, version: int | None = None, scope: str | None = None) -> dict:
    _ensure_init()
    return await wiki.wiki_leer(slug=slug, version=version, scope=scope)


@mcp.tool(
    name="wiki_escribir",
    description=(
        "Escribe nueva versión wiki (DB append-only + opcional archive .md + "
        "reindex chunks). PK (slug, version) garantiza no overwrite. "
        "Para entender el sistema antes de escribir: wiki_help()."
    ),
)
async def tool_wiki_escribir(
    slug: str,
    body: str,
    scope: str,
    author: str,
    frontmatter: dict | None = None,
) -> dict:
    _ensure_init()
    return await wiki.wiki_escribir(
        slug=slug, body=body, scope=scope, author=author, frontmatter=frontmatter,
    )


@mcp.tool(
    name="wiki_historial",
    description=(
        "Lista todas las versiones de una página (DB, append-only). Útil para "
        "ver qué cambió entre versiones. Para empezar: wiki_help()."
    ),
)
async def tool_wiki_historial(slug: str, scope: str | None = None) -> list[dict]:
    _ensure_init()
    return await wiki.wiki_historial(slug=slug, scope=scope)


@mcp.tool(
    name="wiki_export",
    description=(
        "Export bundle JSON (DB only). Sin slug = todo el wiki. Filtrá por "
        "scope o slug. Para entender primero qué es la wiki: wiki_help()."
    ),
)
async def tool_wiki_export(slug: str | None = None, scope: str | None = None) -> dict:
    _ensure_init()
    return await wiki.wiki_export(slug=slug, scope=scope)


# ── Subapp MCP ────────────────────────────────────────────────────
mcp_subapp = mcp.http_app()


# ── FastAPI app ───────────────────────────────────────────────────
# Patrón FastMCP oficial: usar mcp_subapp.lifespan directamente.
app = FastAPI(
    title="mcp-memoria",
    version="0.1.0",
    lifespan=mcp_subapp.lifespan,
)

# Health + metrics (open endpoints)
app.include_router(health_router)

# Auth middleware (skip health/metrics internamente)
app.middleware("http")(auth_mod.auth_middleware)

# Inyectar routes de la subapp MCP (preserva /mcp path sin redirect)
for route in mcp_subapp.routes:
    app.router.routes.append(route)


def main() -> None:
    import uvicorn
    # Audit mcp-memoria 2026-07-05 (MOP-388) C6: bind desde env var.
    # Default 127.0.0.1 (loopback). Para Tailscale peers: setear
    # MCP_HOST=<tailscale_ip> en .env o systemd unit.
    bind_host = os.environ.get("MCP_HOST", "127.0.0.1")
    log.info("server_starting", extra={"host": bind_host, "port": MCP_PORT})
    uvicorn.run(app, host=bind_host, port=MCP_PORT)


if __name__ == "__main__":
    main()
