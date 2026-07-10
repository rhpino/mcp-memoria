"""tools/adr.py — adr_get.

ADRs viven en `04-decisions/NNNN-slug.md`. La indexación los guarda
como `04-decisions-NNNN-slug` (path relativo con guiones).

El kb/ real de vps-geo-noc no tiene 04-decisions/. Esta tool retorna
"not_found" con hint claro cuando no hay ADRs indexados.
"""
from __future__ import annotations

from .. import db


async def get_adr(number: int) -> dict:
    """Devuelve un ADR por número (4 dígitos).

    Args:
        number: entero (ej 12 para ADR-0012)

    Estrategia: encontrar el page_slug que empieza con `04-decisions-NNNN-`.
    """
    n4 = f"{number:04d}"

    # Primero verificar si hay scope=adrs en el corpus
    has_adrs = db.read_one(
        "SELECT COUNT(*) AS c FROM mm_entity_chunks WHERE scope = %s",
        ("adrs",),
    )
    if not has_adrs or has_adrs.get("c", 0) == 0:
        return {
            "number": number,
            "error": "not_found",
            "hint": "No ADRs in this kb/. adr_get expects 04-decisions/ scope. "
                    "Use doc_get(slug) for arbitrary pages.",
        }

    rows = db.read_many(
        "SELECT page_slug, chunk_index, heading, chunk_text FROM mm_entity_chunks "
        "WHERE page_slug LIKE %s AND scope = 'adrs' "
        "ORDER BY page_slug, chunk_index",
        (f"04-decisions-{n4}-%",),
    )
    if not rows:
        return {
            "number": number,
            "error": "not_found",
            "hint": f"no ADR with number {number} (expected page_slug like '04-decisions-{n4}-<slug>')",
        }

    body = "\n\n".join(
        (f"## {r['heading']}\n\n{r['chunk_text']}" if r.get("heading") else r["chunk_text"])
        for r in rows
    )
    page_slug = rows[0]["page_slug"]
    return {
        "number": number,
        "slug": page_slug,
        "canonical": f"adr:{n4}",
        "title": rows[0].get("heading") or page_slug,
        "body": body,
        "chunk_count": len(rows),
    }