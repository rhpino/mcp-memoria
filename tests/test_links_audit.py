"""Regression tests for link audit metadata."""
from __future__ import annotations

import pytest

from memoria_mcp import db
from memoria_mcp.tools import links


@pytest.mark.asyncio
async def test_link_add_persists_actor_for_audit():
    """Validated actor must be persisted in mm_relations, not only echoed."""
    from_id = "test-actor-from"
    to_id = "test-actor-to"

    db.init_schema()
    db.write_one(
        "DELETE FROM mm_relations WHERE from_id=%s OR to_id=%s",
        (from_id, to_id),
    )
    try:
        result = await links.add_link(
            from_id=from_id,
            to_id=to_id,
            relation="mentions",
            actor="codex",
            notes="actor audit regression",
        )

        row = db.read_one(
            "SELECT actor FROM mm_relations WHERE relation_id=%s",
            (result["relation_id"],),
        )

        assert row is not None
        assert row["actor"] == "codex"
    finally:
        db.write_one(
            "DELETE FROM mm_relations WHERE from_id=%s OR to_id=%s",
            (from_id, to_id),
        )
