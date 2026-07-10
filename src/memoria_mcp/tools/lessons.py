"""tools/lessons.py — lesson_list / lesson_get."""
from __future__ import annotations

from typing import Optional

from .. import db


async def list_lessons(topic: Optional[str] = None) -> list[dict]:
    """Lista lecciones aprendidas (kb/lessons/*.md).

    H7 audit 2026-07-02: el parámetro topic se ignora. Filtramos por
    LIKE en heading + chunk_text (topic aparece en el H1 o intro de la lección).
    """
    if topic:
        sql = (
            "SELECT DISTINCT page_slug, MIN(heading) AS first_heading, COUNT(*) AS chunk_count, "
            "MAX(ts) AS last_indexed "
            "FROM mm_entity_chunks WHERE scope = 'lessons' AND "
            "(LOWER(heading) LIKE %s OR LOWER(chunk_text) LIKE %s) "
            "GROUP BY page_slug ORDER BY last_indexed DESC LIMIT 100"
        )
        topic_pat = f"%{topic.lower()}%"
        rows = db.read_many(sql, (topic_pat, topic_pat))
    else:
        sql = (
            "SELECT page_slug, MIN(heading) AS first_heading, COUNT(*) AS chunk_count, "
            "MAX(ts) AS last_indexed "
            "FROM mm_entity_chunks WHERE scope = 'lessons' "
            "GROUP BY page_slug ORDER BY last_indexed DESC LIMIT 100"
        )
        rows = db.read_many(sql)
    return [
        {
            "id": f"lesson:{r['page_slug']}",
            "slug": r["page_slug"],
            "title": (r.get("first_heading") or r["page_slug"]).replace("-", " ").title(),
            "scope": "lessons",
            "topic": topic,
            "chunk_count": r["chunk_count"],
        }
        for r in rows
    ]


async def get_lesson(id: str) -> dict:
    """Devuelve chunks concatenados de una lección."""
    slug = id.split(":", 1)[1] if ":" in id else id
    rows = db.read_many(
        "SELECT chunk_index, heading, chunk_text FROM mm_entity_chunks "
        "WHERE page_slug = %s AND scope = 'lessons' ORDER BY chunk_index",
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
        "title": rows[0].get("heading") or slug,
        "body": body,
        "chunk_count": len(rows),
    }