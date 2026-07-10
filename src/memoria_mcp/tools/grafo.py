"""tools/grafo.py — entity_añadir, grafo_vecinos."""
from __future__ import annotations

from typing import Optional

from .. import grafo as grafo_mod
from .. import db


async def entity_añadir(
    id: str,
    name: str,
    type: str,
    attrs: Optional[dict] = None,
) -> dict:
    """Añade un nodo al grafo de entidades (idempotente por id)."""
    return grafo_mod.add_entity(id=id, name=name, type=type, attributes=attrs or {})


async def grafo_vecinos(
    entity_id: str,
    depth: int = 1,
    relation_type: Optional[str] = None,
) -> list[dict]:
    """Vecinos BFS N saltos desde una entidad."""
    nodes = grafo_mod.vecinos(entity_id, depth=depth, relation_type=relation_type)
    return [
        {
            "id": n.id,
            "name": n.name,
            "type": n.type,
            "depth": n.depth,
            "via_relation": n.via_relation,
        }
        for n in nodes
    ]


async def entity_stats(entity_id: str) -> dict:
    """In/out degree de una entidad."""
    return grafo_mod.entity_stats(entity_id)


async def shortest_path(from_id: str, to_id: str) -> dict:
    """Camino más corto entre dos entidades."""
    path = grafo_mod.shortest_path(from_id, to_id)
    return {"from": from_id, "to": to_id, "path": path}