"""tools/decisions.py — decision_list / decision_get.

Scope-agnostic: acepta `decisions` (default), `lessons`, `adrs`, `clientes`, `designs`,
`papers`, `concepts`, `reports`, o `all`. El kb/ real de vps-geo-noc tiene los
scopes `designs/papers/concepts/lessons/reports` (más root files).
"""
from __future__ import annotations

from typing import Optional

from .. import db

# Scopes válidos (subset de la lista completa; otros retornan []).
VALID_SCOPES: set[str] = {
    "decisions", "lessons", "adrs", "clientes",  # legacy / seed
    "concepts", "designs", "papers", "reports",  # kb/ real vps-geo-noc
    "all",  # todos los scopes
}


async def list_decisions(scope: str = "decisions", tag: Optional[str] = None) -> list[dict]:
    """Lista docs indexados en un scope.

    Args:
        scope: uno de VALID_SCOPES. Default "decisions" (compat seed).
        tag: filtro opcional (in-memory, simple).

    Returns:
        Lista de resumenes por page_slug, ordenados por last_indexed DESC.
    """
    if scope not in VALID_SCOPES:
        return []

    # H7 audit 2026-07-02: tag filter. Como tags se guardan en
    # entities_referenced JSON (lo que el chunker detectó como entity match)
    # y en heading, filtramos por LIKE en ambos. Para "all", filtramos en
    # page_slugs que tengan al menos 1 chunk con la tag (DISTINCT).
    if scope == "all":
        if tag:
            sql = (
                "SELECT DISTINCT page_slug, scope, MIN(heading) AS first_heading, "
                "COUNT(*) AS chunk_count, MAX(ts) AS last_indexed "
                "FROM mm_entity_chunks "
                "WHERE LOWER(entities_referenced) LIKE %s OR LOWER(heading) LIKE %s "
                "GROUP BY page_slug, scope ORDER BY last_indexed DESC LIMIT 200"
            )
            tag_pat = f"%{tag.lower()}%"
            rows = db.read_many(sql, (tag_pat, tag_pat))
        else:
            sql = (
                "SELECT page_slug, MIN(heading) AS first_heading, COUNT(*) AS chunk_count, "
                "MAX(ts) AS last_indexed, scope "
                "FROM mm_entity_chunks "
                "GROUP BY page_slug, scope ORDER BY last_indexed DESC LIMIT 200"
            )
            rows = db.read_many(sql)
    else:
        if tag:
            sql = (
                "SELECT DISTINCT page_slug, scope, MIN(heading) AS first_heading, "
                "COUNT(*) AS chunk_count, MAX(ts) AS last_indexed "
                "FROM mm_entity_chunks WHERE scope = %s AND "
                "(LOWER(entities_referenced) LIKE %s OR LOWER(heading) LIKE %s) "
                "GROUP BY page_slug ORDER BY last_indexed DESC LIMIT 200"
            )
            tag_pat = f"%{tag.lower()}%"
            rows = db.read_many(sql, (scope, tag_pat, tag_pat))
        else:
            sql = (
                "SELECT page_slug, MIN(heading) AS first_heading, COUNT(*) AS chunk_count, "
                "MAX(ts) AS last_indexed, scope "
                "FROM mm_entity_chunks WHERE scope = %s "
                "GROUP BY page_slug ORDER BY last_indexed DESC LIMIT 200"
            )
            rows = db.read_many(sql, (scope,))

    out: list[dict] = []
    for r in rows:
        row_scope = r.get("scope") or scope
        out.append(
            {
                "id": f"{row_scope}:{r['page_slug']}",
                "slug": r["page_slug"],
                "title": (r.get("first_heading") or r["page_slug"]).replace("-", " ").title(),
                "scope": row_scope,
                "tag": tag,
                "chunk_count": r["chunk_count"],
                "last_indexed": str(r["last_indexed"]) if r.get("last_indexed") else None,
            }
        )
    return out


async def get_decision(id: str) -> dict:
    """Devuelve todos los chunks de un doc (cualquier scope).

    Args:
        id: ej "designs:architecture-evolution-trinity" o "architecture-evolution-trinity".
            El prefijo scope es opcional.
    """
    if ":" in id:
        scope, slug = id.split(":", 1)
    else:
        scope, slug = None, id

    if scope:
        rows = db.read_many(
            "SELECT chunk_index, heading, chunk_text FROM mm_entity_chunks "
            "WHERE page_slug = %s AND scope = %s ORDER BY chunk_index",
            (slug, scope),
        )
    else:
        rows = db.read_many(
            "SELECT chunk_index, heading, chunk_text, scope FROM mm_entity_chunks "
            "WHERE page_slug = %s ORDER BY scope, chunk_index",
            (slug,),
        )

    if not rows:
        return {"id": id, "error": "not_found", "slug": slug}

    body = "\n\n".join(
        (f"## {r['heading']}\n\n{r['chunk_text']}" if r.get("heading") else r["chunk_text"])
        for r in rows
    )
    return {
        "id": id,
        "slug": slug,
        "scope": rows[0].get("scope") or scope,
        "title": rows[0].get("heading") or slug,
        "body": body,
        "chunk_count": len(rows),
    }