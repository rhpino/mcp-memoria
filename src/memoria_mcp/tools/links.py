"""tools/links.py — cross_links / link_add / link_list.

Stage 3/4 — implementación real con MariaDB mm_relations + entities.
"""
from __future__ import annotations

import json as _json
from typing import Optional

from .. import db, search as search_mod


async def cross_links(topic: str, limit: int = 20) -> list[dict]:
    """Entidades que mencionan un topic.

    Busca en:
    - mm_entities.name (case-insensitive)
    - mm_entity_chunks.entities_referenced (JSON_SEARCH)
    - mm_entity_chunks.chunk_text (LIKE)
    - mm_relations (from_id/to_id LIKE)
    """
    out: list[dict] = []
    topic_l = topic.lower()
    pattern = f"%{topic_l}%"

    # 1. Entities matching name
    entity_rows = db.read_many(
        "SELECT id, name, type, attributes FROM mm_entities "
        "WHERE LOWER(name) LIKE %s LIMIT %s",
        (pattern, limit),
    )
    for e in entity_rows:
        out.append({
            "type": "entity",
            "id": e["id"],
            "name": e["name"],
            "kind": e.get("type"),
            "source": "mm_entities",
        })

    # 2. Chunks que mencionan el topic
    chunk_rows = db.read_many(
        "SELECT id, page_slug, scope, heading, "
        "SUBSTRING(chunk_text, 1, 200) AS preview "
        "FROM mm_entity_chunks "
        "WHERE LOWER(chunk_text) LIKE %s OR LOWER(heading) LIKE %s "
        "OR LOWER(entities_referenced) LIKE %s "
        "LIMIT %s",
        (pattern, pattern, pattern, limit),
    )
    for c in chunk_rows:
        out.append({
            "type": "chunk",
            "id": f"chunk:{c['id']}",
            "page_slug": c["page_slug"],
            "scope": c.get("scope"),
            "heading": c["heading"],
            "preview": c["preview"],
            "source": "mm_entity_chunks",
        })

    # 3. Relations
    rel_rows = db.read_many(
        "SELECT relation_id, from_id, to_id, relation_type, notes "
        "FROM mm_relations "
        "WHERE LOWER(from_id) LIKE %s OR LOWER(to_id) LIKE %s "
        "OR LOWER(notes) LIKE %s LIMIT %s",
        (pattern, pattern, pattern, limit),
    )
    for r in rel_rows:
        out.append({
            "type": "relation",
            "id": f"relation:{r['relation_id']}",
            "from_id": r["from_id"],
            "to_id": r["to_id"],
            "relation_type": r["relation_type"],
            "notes": r.get("notes"),
            "source": "mm_relations",
        })

    return out[:limit]


async def list_links(entity_id: str) -> list[dict]:
    """Lista las relaciones de una entidad."""
    return db.read_many(
        "SELECT relation_id, from_id, to_id, relation_type, notes, ts "
        "FROM mm_relations WHERE from_id = %s OR to_id = %s ORDER BY ts DESC",
        (entity_id, entity_id),
    )


async def add_link(
    from_id: str,
    to_id: str,
    relation: str,
    actor: str,
    notes: str = "",
) -> dict:
    """Crea un link entre entidades. Idempotente (UNIQUE constraint)."""
    ALLOWED = {
        "derived_from", "blocks", "enables", "related_to",
        "supersedes", "implements", "depends_on", "mentions",
    }
    if relation not in ALLOWED:
        raise ValueError(f"relation '{relation}' not in allowlist: {sorted(ALLOWED)}")
    ALLOWED_ACTORS = {"geo", "claude-code", "codex", "rodrigo", "system", "smoke"}
    if actor not in ALLOWED_ACTORS:
        raise ValueError(f"actor '{actor}' not in allowlist: {sorted(ALLOWED_ACTORS)}")

    try:
        rid = db.write_one(
            "INSERT INTO mm_relations (from_id, to_id, relation_type, notes) "
            "VALUES (%s, %s, %s, %s)",
            (from_id, to_id, relation, notes or None),
        )
        return {
            "relation_id": rid,
            "from_id": from_id,
            "to_id": to_id,
            "relation": relation,
            "actor": actor,
            "created": True,
        }
    except Exception as e:
        if "Duplicate entry" in str(e):
            existing = db.read_one(
                "SELECT relation_id FROM mm_relations "
                "WHERE from_id=%s AND to_id=%s AND relation_type=%s",
                (from_id, to_id, relation),
            )
            if existing:
                return {
                    "relation_id": existing["relation_id"],
                    "from_id": from_id,
                    "to_id": to_id,
                    "relation": relation,
                    "idempotent": True,
                }
        raise