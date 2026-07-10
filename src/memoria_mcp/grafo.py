"""grafo.py — Grafo de entidades con BFS recursivo (SQL CTE).

Réplica conceptual del `grafo_vecinos` de omni-mcp (server.js:619).

Implementación con WITH RECURSIVE de MariaDB:
- Walk N saltos desde una entidad origen.
- Devuelve entidades vecinas + relation_type por nivel.

Suficiente para kb/ interna (<500 docs, miles de entidades máximo).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from . import db

log = logging.getLogger("memoria_grafo")


@dataclass
class GraphNode:
    id: str
    name: str
    type: str | None
    depth: int
    via_relation: str | None = None


MAX_DEPTH = 3


def vecinos(
    entity_id: str,
    depth: int = 1,
    relation_type: str | None = None,
) -> list[GraphNode]:
    """BFS recursivo desde `entity_id` hasta `depth` saltos.

    Args:
        entity_id: ej "decision:foo", "adr:0012", "kag"
        depth: 1-3 (default 1)
        relation_type: filtro opcional (ej "implements")

    Returns:
        Lista de GraphNode con depth 1..N.
    """
    depth = max(1, min(int(depth), MAX_DEPTH))

    # WITH RECURSIVE: level 0 = root, level 1 = direct neighbors, etc.
    sql = """
    WITH RECURSIVE walk AS (
      SELECT
        to_id AS node_id,
        1 AS depth,
        relation_type AS via_rel
      FROM mm_relations
      WHERE from_id = %s
    """
    params: list = [entity_id]

    if relation_type:
        sql += " AND relation_type = %s"
        params.append(relation_type)

    # CTE recursive: descend through relations
    sql += """
      UNION ALL
      SELECT r.to_id, w.depth + 1, r.relation_type
      FROM mm_relations r
      INNER JOIN walk w ON r.from_id = w.node_id
      WHERE w.depth < %s
    """
    params.append(depth)

    if relation_type:
        sql += " AND r.relation_type = %s"
        params.append(relation_type)

    sql += """
    )
    SELECT DISTINCT w.node_id, e.name, e.type, w.depth, w.via_rel
    FROM walk w
    LEFT JOIN mm_entities e ON e.id = w.node_id
    WHERE w.node_id != %s
    ORDER BY w.depth, w.node_id
    """
    params.append(entity_id)

    rows = db.read_many(sql, tuple(params))
    out: list[GraphNode] = []
    seen: set[str] = set()
    for r in rows:
        nid = r["node_id"]
        if nid in seen:
            continue
        seen.add(nid)
        out.append(
            GraphNode(
                id=nid,
                name=r.get("name") or nid,
                type=r.get("type"),
                depth=int(r["depth"]),
                via_relation=r.get("via_rel"),
            )
        )
    log.debug("grafo_vecinos", extra={"root": entity_id, "depth": depth, "found": len(out)})
    return out


def shortest_path(from_id: str, to_id: str, max_depth: int = 5) -> list[str] | None:
    """Camino más corto entre dos entidades (BFS).

    Returns: lista de IDs en orden [from, ..., to] o None si no hay camino.
    """
    sql = """
    WITH RECURSIVE paths AS (
      SELECT
        CAST(from_id AS CHAR(2000)) AS path,
        to_id AS node_id,
        1 AS depth
      FROM mm_relations WHERE from_id = %s
      UNION ALL
      SELECT CONCAT(p.path, '->', r.to_id), r.to_id, p.depth + 1
      FROM mm_relations r INNER JOIN paths p ON r.from_id = p.node_id
      WHERE p.depth < %s AND LOCATE(r.to_id, p.path) = 0
    )
    SELECT path FROM paths WHERE node_id = %s ORDER BY depth LIMIT 1
    """
    rows = db.read_many(sql, (from_id, max_depth, to_id))
    if not rows:
        return None
    return rows[0]["path"].split("->")


def entity_stats(entity_id: str) -> dict:
    """Estadísticas de una entidad: in/out degree, clusters cercanos."""
    out = db.read_one(
        "SELECT COUNT(*) AS c FROM mm_relations WHERE from_id = %s",
        (entity_id,),
    )
    inn = db.read_one(
        "SELECT COUNT(*) AS c FROM mm_relations WHERE to_id = %s",
        (entity_id,),
    )
    return {
        "id": entity_id,
        "out_degree": out["c"] if out else 0,
        "in_degree": inn["c"] if inn else 0,
    }


def add_entity(
    id: str,
    name: str,
    type: str,
    attributes: dict | None = None,
) -> dict:
    """Añade o actualiza una entidad (idempotente)."""
    import json as _json
    attrs = _json.dumps(attributes or {}, ensure_ascii=False)
    try:
        rid = db.write_one(
            "INSERT INTO mm_entities (id, name, type, attributes) VALUES (%s, %s, %s, %s)",
            (id, name, type, attrs),
        )
        return {"id": id, "name": name, "type": type, "created": True}
    except Exception as e:
        # Audit mcp-memoria 2026-07-05 (MOP-388) C8: usar errno (1062)
        # en vez de string match. Más robusto a wrapping, locale, collation.
        errno = getattr(e, "errno", None) or (
            e.args[0] if e.args and isinstance(e.args[0], int) else None
        )
        if errno == 1062:
            db.write_one(
                "UPDATE mm_entities SET name=%s, type=%s, attributes=%s WHERE id=%s",
                (name, type, attrs, id),
            )
            return {"id": id, "name": name, "type": type, "updated": True}
        raise