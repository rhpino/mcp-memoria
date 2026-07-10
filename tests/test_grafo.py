"""tests/test_grafo.py — Tests para grafo (BFS recursivo, add_entity)."""
from __future__ import annotations

import pytest

from memoria_mcp import grafo, db


@pytest.fixture(scope="session", autouse=True)
def seed_grafo():
    """Inserta un grafo de prueba: 4 entidades, 5 relaciones."""
    entities = [
        ("node-a", "Node A", "decision"),
        ("node-b", "Node B", "decision"),
        ("node-c", "Node C", "adr"),
        ("node-d", "Node D", "lesson"),
    ]
    for e in entities:
        grafo.add_entity(*e)

    relations = [
        ("node-a", "node-b", "implements", "tester"),
        ("node-a", "node-c", "related_to", "tester"),
        ("node-b", "node-d", "blocks", "tester"),
        ("node-c", "node-d", "mentions", "tester"),
        ("node-d", "node-a", "related_to", "tester"),  # cycle
    ]
    for frm, to, rel, actor in relations:
        try:
            db.write_one(
                "INSERT INTO mm_relations (from_id, to_id, relation_type, notes) "
                "VALUES (%s, %s, %s, %s)",
                (frm, to, rel, f"seeded by {actor}"),
            )
        except Exception:
            pass  # duplicate → ok

    yield

    # Cleanup
    db.write_one(
        "DELETE FROM mm_entities WHERE id IN (%s, %s, %s, %s)",
        ("node-a", "node-b", "node-c", "node-d"),
    )
    db.write_one(
        "DELETE FROM mm_relations WHERE from_id IN (%s, %s, %s, %s) OR to_id IN (%s, %s, %s, %s)",
        ("node-a", "node-b", "node-c", "node-d") * 2,
    )


def test_add_entity_idempotent(seed_grafo):
    """add_entity con mismo id es idempotente (update)."""
    r = grafo.add_entity("node-a", "Node A renamed", "decision")
    assert r["id"] == "node-a"
    assert r.get("created") or r.get("updated")

    rows = db.read_many("SELECT name FROM mm_entities WHERE id = 'node-a'")
    assert len(rows) == 1
    assert rows[0]["name"] == "Node A renamed"


def test_vecinos_depth_1(seed_grafo):
    """vecinos depth=1 retorna los vecinos directos."""
    nodes = grafo.vecinos("node-a", depth=1)
    ids = [n.id for n in nodes]
    assert "node-b" in ids
    assert "node-c" in ids
    assert "node-d" not in ids or any(n.depth == 2 for n in nodes if n.id == "node-d")


def test_vecinos_depth_2(seed_grafo):
    """vecinos depth=2 retorna los de depth 1 + sus hijos."""
    nodes = grafo.vecinos("node-a", depth=2)
    depths = sorted([n.depth for n in nodes])
    assert 1 in depths
    assert 2 in depths


def test_vecinos_max_depth(seed_grafo):
    """depth > 3 se clipea a 3."""
    nodes = grafo.vecinos("node-a", depth=10)
    assert all(n.depth <= 3 for n in nodes)


def test_vecinos_filter_by_relation(seed_grafo):
    """Filtro por relation_type funciona."""
    nodes = grafo.vecinos("node-a", depth=1, relation_type="implements")
    ids = [n.id for n in nodes]
    assert "node-b" in ids
    assert "node-c" not in ids


def test_shortest_path(seed_grafo):
    """shortest_path encuentra camino entre entidades."""
    path = grafo.shortest_path("node-a", "node-d")
    assert path is not None
    assert path[0] == "node-a"
    assert path[-1] == "node-d"


def test_shortest_path_no_path(seed_grafo):
    """shortest_path entre entidades desconectadas devuelve None."""
    grafo.add_entity("node-x", "Node X", "concept")
    grafo.add_entity("node-y", "Node Y", "concept")
    assert grafo.shortest_path("node-x", "node-y") is None


def test_entity_stats(seed_grafo):
    """entity_stats devuelve in/out degree."""
    stats = grafo.entity_stats("node-a")
    assert stats["out_degree"] >= 2
    assert stats["in_degree"] >= 1  # node-d points to node-a (cycle)