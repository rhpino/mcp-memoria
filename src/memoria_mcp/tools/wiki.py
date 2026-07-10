"""tools/wiki.py — 5 tools para wiki versionada (MOP-398).

Source of truth: mm_wiki_pages (DB). Filesystem archive es write-only artefact.

- wiki_listar(scope?, limit?)    : lista páginas (DB only).
- wiki_leer(slug, version?, scope?): lee página específica (DB only).
- wiki_escribir(slug, body, scope, author, frontmatter?): INSERT nueva versión + archive.
- wiki_historial(slug, scope?)   : todas las versiones (DB only).
- wiki_export(slug?, scope?)     : bundle markdown (DB only).
"""
from __future__ import annotations

import json as _json
import logging
import os
from datetime import datetime, timezone
from typing import Optional

from .. import db, paths
from .. import chunker
from ..wiki_io import render_with_frontmatter
from ..paths import _VALID_SCOPE_NAMES

log = logging.getLogger("memoria_wiki_tool")

ARCHIVE_ON_WRITE = os.environ.get("MCP_ARCHIVE_ON_WRITE", "1") == "1"


# ── Helpers ────────────────────────────────────────────────────────

def _archive_path(slug: str, scope: str, version: int):
    """Devuelve el path archive esperado (no verifica existencia)."""
    return paths.wiki_archive_path(slug, scope, version)


# ── wiki_listar ────────────────────────────────────────────────────

def wiki_listar_sync(scope: Optional[str] = None, limit: int = 50) -> list[dict]:
    """Lista páginas wiki con su última versión + # chunks + path archive."""
    if scope:
        rows = db.read_many(
            "SELECT slug, scope, MAX(version) AS version, MAX(ts) AS ts "
            "FROM mm_wiki_pages WHERE scope = %s "
            "GROUP BY slug, scope ORDER BY ts DESC LIMIT %s",
            (scope, limit),
        )
    else:
        rows = db.read_many(
            "SELECT slug, scope, MAX(version) AS version, MAX(ts) AS ts "
            "FROM mm_wiki_pages GROUP BY slug, scope ORDER BY ts DESC LIMIT %s",
            (limit,),
        )
    out = []
    for r in rows:
        slug, sc, ver = r["slug"], r["scope"], r["version"]
        cc = db.read_one(
            "SELECT COUNT(*) AS c FROM mm_entity_chunks WHERE page_slug = %s",
            (slug,),
        )
        archive_p = _archive_path(slug, sc, ver)
        out.append({
            "slug": slug,
            "scope": sc,
            "version_actual": ver,
            "ts": r["ts"].isoformat() if r["ts"] else None,
            "chunks_count": cc["c"] if cc else 0,
            "archive_path": str(archive_p),
            "archive_present": archive_p.exists(),
        })
    return out


# ── wiki_leer ──────────────────────────────────────────────────────

def wiki_leer_sync(
    slug: str,
    version: Optional[int] = None,
    scope: Optional[str] = None,
) -> dict:
    """Lee una página. Si version es None, devuelve la última."""
    if version is not None:
        if scope:
            row = db.read_one(
                "SELECT version, body, frontmatter, author, ts, scope "
                "FROM mm_wiki_pages WHERE slug = %s AND scope = %s AND version = %s",
                (slug, scope, version),
            )
        else:
            row = db.read_one(
                "SELECT version, body, frontmatter, author, ts, scope "
                "FROM mm_wiki_pages WHERE slug = %s AND version = %s",
                (slug, version),
            )
        if not row:
            raise LookupError(f"no existe {slug} v{version}")
        sc = row["scope"]
    else:
        if scope:
            row = db.read_one(
                "SELECT version, body, frontmatter, author, ts, scope "
                "FROM mm_wiki_pages WHERE slug = %s AND scope = %s "
                "ORDER BY version DESC LIMIT 1",
                (slug, scope),
            )
        else:
            row = db.read_one(
                "SELECT version, body, frontmatter, author, ts, scope "
                "FROM mm_wiki_pages WHERE slug = %s ORDER BY version DESC LIMIT 1",
                (slug,),
            )
        if not row:
            raise LookupError(f"no existe {slug}")
        version = row["version"]
        sc = row["scope"]

    return {
        "slug": slug,
        "scope": sc,
        "version": version,
        "body": row["body"],
        "frontmatter": _json.loads(row["frontmatter"]) if row["frontmatter"] else {},
        "author": row["author"],
        "ts": row["ts"].isoformat() if row["ts"] else None,
        "archive_path": str(_archive_path(slug, sc, version)),
    }


# ── Async wrappers (FastMCP) ───────────────────────────────────────

async def wiki_listar(scope: Optional[str] = None, limit: int = 50) -> list[dict]:
    return wiki_listar_sync(scope=scope, limit=limit)


async def wiki_leer(
    slug: str,
    version: Optional[int] = None,
    scope: Optional[str] = None,
) -> dict:
    return wiki_leer_sync(slug=slug, version=version, scope=scope)


# ── wiki_help (entry point — cómo usar el sistema) ──────────────────

# Páginas "starter" curadas. Cualquier agente nuevo debería leerlas primero
# para entender el sistema, sus decisiones arquitectónicas, y los patrones.
_STARTER_PAGES = [
    {
        "slug": "mop-398-wiki-research",
        "scope": "designs",
        "topic": "Overview de la wiki versionada: arquitectura DB-only + auto-archive",
    },
    {
        "slug": "mop-398-shared-test-isolation-module",
        "scope": "designs",
        "topic": "Cómo testear sin contaminar prod (patrón shared)",
    },
    {
        "slug": "mop-398-architecture-decision",
        "scope": "designs",
        "topic": "Por qué DB-only + auto-archive (vs dual-write)",
    },
    {
        "slug": "mop-398-known-issues",
        "scope": "designs",
        "topic": "Riesgos vivos y mitigaciones",
    },
    {
        "slug": "mop-398-future-work",
        "scope": "designs",
        "topic": "Backlog out-of-scope para futuros MOPs",
    },
]


def wiki_help_sync() -> dict:
    """Entry point: cómo usar el sistema de wiki + herramientas disponibles.

    Diseñado para ser el primer tool que un agente llama cuando llega al MCP
    sin contexto previo. Devuelve:
      - Welcome message.
      - Mapa de tools con propósito.
      - Scopes válidos.
      - Lista de páginas "starter" curadas (cross-tracking).
      - Total de páginas en DB (snapshot al momento de llamar).
    """
    # Snapshot del estado actual de la wiki
    total_versions_row = db.read_one("SELECT COUNT(*) AS c FROM mm_wiki_pages")
    total_versions = total_versions_row["c"] if total_versions_row else 0
    by_scope_rows = db.read_many(
        "SELECT scope, COUNT(DISTINCT slug) AS pages, "
        "COUNT(*) AS versions FROM mm_wiki_pages GROUP BY scope ORDER BY scope"
    )
    by_scope = [
        {"scope": r["scope"], "pages": r["pages"], "versions": r["versions"]}
        for r in by_scope_rows
    ]

    return {
        "welcome": (
            "mcp-memoria v0.2.0 — 21 tools totales (16 existentes + 5 wiki). "
            "Wiki versionada con DB `mm_wiki_pages` como source of truth. "
            "Empezá por leer esta help o las starter_pages para entender el sistema."
        ),
        "your_entry_point": "wiki_help() (esta función)",
        "tools": {
            "wiki_help": "← Esta. Cómo usar el sistema. LLAMÁ PRIMERO.",
            "wiki_listar": "Lista todas las páginas wiki (DB). Filtrá por scope.",
            "wiki_leer": "Lee una página específica (slug + version opcional).",
            "wiki_escribir": "Crea nueva versión append-only. Reindex automático.",
            "wiki_historial": "Lista todas las versiones de un slug.",
            "wiki_export": "Bundle JSON (todo o filtrado por slug/scope).",
        },
        "other_tools": [
            "kag_buscar(query) — búsqueda semántica en chunks",
            "grafo_vecinos(entity_id, depth) — navegación del grafo de entidades",
            "decision_list / decision_get — decisiones técnicas",
            "lesson_list / lesson_get — lecciones aprendidas",
            "adr_get(number) — architecture decision records",
            "bibliotecario_run / conflict_list / conflict_resolve — curador",
        ],
        "scopes": sorted(list(_VALID_SCOPE_NAMES)),
        "by_scope_stats": by_scope,
        "total_rows_in_db": total_versions,
        "starter_pages": _STARTER_PAGES,
        "discovery_tips": {
            "browse_all": "wiki_listar(scope='designs') para ver overview curado",
            "search_semantic": (
                "kag_buscar(query='tema') para búsqueda semántica en chunks "
                "de mm_entity_chunks"
            ),
            "cross_tracking": (
                "Páginas wiki tienen frontmatter `related:` que linkean a otras "
                "páginas. kag_buscar encuentra estas referencias vía embedding."
            ),
            "versioning": (
                "mm_wiki_pages PK (slug, version) es append-only. "
                "wiki_escribir siempre crea nueva versión, nunca sobreescribe."
            ),
        },
        "shared_module_for_tests": (
            "/opt/mcps/shared/mcp_test_isolation.py — patrón para tests aislados. "
            "Cualquier MCP nuevo debe usar force_test_db() + make_isolate_fixture()."
        ),
        "env_vars": {
            "WORKSPACE_ROOT": "Path al kb/ (default /home/cloudops/.openclaw/workspace)",
            "MCP_ARCHIVE_ON_WRITE": "ON (1) escribe .md archive por versión, "
                                    "OFF (0) DB-only",
            "MCP_DB_NAME": "Nombre de DB (set por /etc/mcp-memoria/db.env en runtime)",
        },
    }


async def wiki_help() -> dict:
    """Async wrapper del entry point wiki_help_sync."""
    return wiki_help_sync()


# ── Stubs (Tasks 5 y 6 implementan estos) ────────────────────────

import asyncio
import time as _time


def wiki_escribir_sync(
    slug: str,
    body: str,
    scope: str,
    author: str,
    frontmatter: Optional[dict] = None,
) -> dict:
    """Escribe nueva versión en DB + (opcional) archive filesystem + reindex.

    Order:
    1. Validar slug + scope vía path helper (raise antes de tocar nada).
    2. Computar next_version = MAX(version) + 1.
    3. INSERT en mm_wiki_pages. Si falla, raise sin tocar filesystem.
    4. Si ARCHIVE_ON_WRITE: escribir <WORKSPACE>/wiki_archive/<scope>/<slug>-v<N>.md
       con frontmatter versionado. Filename único → sin race.
    5. Reindex async vía chunker.chunk_and_index (delete + re-insert chunks).
    """
    # 1. Validación up-front (independiente del path helper para que los tests
    # con mock_paths no se salteen el chequeo).
    paths._validate_slug_scope(slug, scope)

    # 2. next_version
    next_version_row = db.read_one(
        "SELECT COALESCE(MAX(version), 0) AS v FROM mm_wiki_pages WHERE slug = %s",
        (slug,),
    )
    next_version = (next_version_row["v"] if next_version_row else 0) + 1
    archive_p = paths.wiki_archive_path(slug, scope, next_version)

    # 3. INSERT (append-only)
    fm_json = _json.dumps(frontmatter or {}, ensure_ascii=False)
    db.write_one(
        "INSERT INTO mm_wiki_pages (slug, version, body, frontmatter, author, scope) "
        "VALUES (%s, %s, %s, %s, %s, %s)",
        (slug, next_version, body, fm_json, author, scope),
    )
    ts_row = db.read_one(
        "SELECT ts FROM mm_wiki_pages WHERE slug = %s AND version = %s",
        (slug, next_version),
    )

    # 4. Archive filesystem (si enabled)
    archived = False
    if ARCHIVE_ON_WRITE:
        archive_dir = paths.wiki_archive_dir(scope)
        archive_dir.mkdir(parents=True, exist_ok=True)
        fm_to_write = dict(frontmatter or {})
        fm_to_write["version"] = next_version
        fm_to_write["author"] = author
        fm_to_write["scope"] = scope
        archive_p.write_text(
            render_with_frontmatter(fm_to_write, body), encoding="utf-8",
        )
        archived = True

    # 5. Reindex async (fire-and-forget si hay loop, sino inline)
    async def _reindex():
        from ..embed import embed_text
        return await chunker.chunk_and_index(
            page_slug=slug, content=body, scope=scope,
            title=(frontmatter or {}).get("title", slug),
            embed_text_fn=embed_text,
        )

    start = _time.monotonic()
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_reindex())
        chunks_indexed = -1  # marker: scheduled, no esperado
    except RuntimeError:
        # No hay loop activo → correr inline (caso sync wrapper / tests).
        chunks_indexed = asyncio.run(_reindex())

    return {
        "slug": slug,
        "scope": scope,
        "version": next_version,
        "ts": ts_row["ts"].isoformat() if ts_row and ts_row["ts"] else None,
        "chunks_indexed": chunks_indexed,
        "archived": archived,
        "archive_path": str(archive_p) if archived else None,
        "reindex_ms": int((_time.monotonic() - start) * 1000),
    }


async def wiki_escribir(
    slug: str,
    body: str,
    scope: str,
    author: str,
    frontmatter: Optional[dict] = None,
) -> dict:
    """Async wrapper. Hace TODO (incluido el reindex awaited)."""
    start = _time.monotonic()
    # Validación + INSERT DB + (opcional) archive, sin reindex.
    paths._validate_slug_scope(slug, scope)
    next_version_row = db.read_one(
        "SELECT COALESCE(MAX(version), 0) AS v FROM mm_wiki_pages WHERE slug = %s",
        (slug,),
    )
    next_version = (next_version_row["v"] if next_version_row else 0) + 1
    archive_p = paths.wiki_archive_path(slug, scope, next_version)
    fm_json = _json.dumps(frontmatter or {}, ensure_ascii=False)
    db.write_one(
        "INSERT INTO mm_wiki_pages (slug, version, body, frontmatter, author, scope) "
        "VALUES (%s, %s, %s, %s, %s, %s)",
        (slug, next_version, body, fm_json, author, scope),
    )
    ts_row = db.read_one(
        "SELECT ts FROM mm_wiki_pages WHERE slug = %s AND version = %s",
        (slug, next_version),
    )
    archived = False
    if ARCHIVE_ON_WRITE:
        archive_dir = paths.wiki_archive_dir(scope)
        archive_dir.mkdir(parents=True, exist_ok=True)
        fm_to_write = dict(frontmatter or {})
        fm_to_write["version"] = next_version
        fm_to_write["author"] = author
        fm_to_write["scope"] = scope
        archive_p.write_text(
            render_with_frontmatter(fm_to_write, body), encoding="utf-8",
        )
        archived = True

    # Reindex awaited (single source of truth — no fire-and-forget race).
    from ..embed import embed_text
    chunks_indexed = await chunker.chunk_and_index(
        page_slug=slug, content=body, scope=scope,
        title=(frontmatter or {}).get("title", slug),
        embed_text_fn=embed_text,
    )

    return {
        "slug": slug,
        "scope": scope,
        "version": next_version,
        "ts": ts_row["ts"].isoformat() if ts_row and ts_row["ts"] else None,
        "chunks_indexed": chunks_indexed,
        "archived": archived,
        "archive_path": str(archive_p) if archived else None,
        "reindex_ms": int((_time.monotonic() - start) * 1000),
    }


def wiki_historial_sync(slug: str, scope: Optional[str] = None) -> list[dict]:
    """Devuelve todas las versiones de un slug, ordenadas DESC por version."""
    if scope:
        rows = db.read_many(
            "SELECT version, ts, author, scope, body, frontmatter "
            "FROM mm_wiki_pages WHERE slug = %s AND scope = %s "
            "ORDER BY version DESC",
            (slug, scope),
        )
    else:
        rows = db.read_many(
            "SELECT version, ts, author, scope, body, frontmatter "
            "FROM mm_wiki_pages WHERE slug = %s ORDER BY version DESC",
            (slug,),
        )
    if not rows:
        raise LookupError(f"{slug} sin historial en DB")
    out = []
    for r in rows:
        ap = _archive_path(slug, r["scope"], r["version"])
        out.append({
            "version": r["version"],
            "ts": r["ts"].isoformat() if r["ts"] else None,
            "author": r["author"],
            "scope": r["scope"],
            "body_len": len(r["body"]),
            "frontmatter": _json.loads(r["frontmatter"]) if r["frontmatter"] else {},
            "archive_path": str(ap),
            "archive_present": ap.exists(),
        })
    return out


def wiki_export_sync(slug: Optional[str] = None, scope: Optional[str] = None) -> dict:
    """Bundle JSON con todas las versiones (DB only). Filtros opcionales."""
    where = []
    params: list = []
    if slug:
        where.append("slug = %s")
        params.append(slug)
    if scope:
        where.append("scope = %s")
        params.append(scope)
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""
    rows = db.read_many(
        f"SELECT slug, scope, version, body, frontmatter, author, ts "
        f"FROM mm_wiki_pages {where_sql} ORDER BY slug, scope, version DESC",
        tuple(params),
    )
    by_key: dict[tuple[str, str], dict] = {}
    for r in rows:
        key = (r["slug"], r["scope"])
        if key not in by_key:
            by_key[key] = {"slug": r["slug"], "scope": r["scope"], "versions": []}
        ap = _archive_path(r["slug"], r["scope"], r["version"])
        by_key[key]["versions"].append({
            "version": r["version"],
            "body": r["body"],
            "frontmatter": _json.loads(r["frontmatter"]) if r["frontmatter"] else {},
            "author": r["author"],
            "ts": r["ts"].isoformat() if r["ts"] else None,
            "archive_path": str(ap),
            "archive_present": ap.exists(),
        })
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "pages": list(by_key.values()),
    }


async def wiki_historial(slug: str, scope: Optional[str] = None) -> list[dict]:
    return wiki_historial_sync(slug=slug, scope=scope)


async def wiki_export(slug: Optional[str] = None, scope: Optional[str] = None) -> dict:
    return wiki_export_sync(slug=slug, scope=scope)