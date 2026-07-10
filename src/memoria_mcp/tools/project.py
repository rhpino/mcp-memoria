"""tools/project.py — project_brief.

Agrega decisiones + lessons + ADRs por proyecto.
Para v1, project se infiere por tag en frontmatter o por menciones en chunks.
"""
from __future__ import annotations

from .. import db


async def get_brief(name: str) -> dict:
    """Resumen de un proyecto por nombre.

    Args:
        name: ej "flow", "painemuni", "entel", "buincity"

    Busca chunks que mencionen `name` en:
    - chunk_text (case-insensitive match)
    - entities_referenced (JSON_SEARCH)
    - page_slug
    """
    name_l = name.lower()
    pattern = f"%{name_l}%"

    # Búsqueda por slug / heading / text / entities
    rows = db.read_many(
        "SELECT DISTINCT page_slug, scope, chunk_index, heading, "
        "SUBSTRING(chunk_text, 1, 200) AS preview, entities_referenced "
        "FROM mm_entity_chunks "
        "WHERE LOWER(chunk_text) LIKE %s OR LOWER(heading) LIKE %s "
        "OR LOWER(page_slug) LIKE %s OR LOWER(entities_referenced) LIKE %s "
        "ORDER BY scope, page_slug, chunk_index LIMIT 200",
        (pattern, pattern, pattern, pattern),
    )

    # Agrupar por scope
    by_scope: dict[str, list[dict]] = {}
    for r in rows:
        scope = r.get("scope") or "unknown"
        by_scope.setdefault(scope, []).append(
            {
                "page_slug": r["page_slug"],
                "chunk_index": r["chunk_index"],
                "heading": r["heading"],
                "preview": r["preview"],
            }
        )

    return {
        "project": name,
        "total_chunks": len(rows),
        "by_scope": {k: len(v) for k, v in by_scope.items()},
        "details": by_scope,
    }