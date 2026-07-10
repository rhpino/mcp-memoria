from __future__ import annotations

from . import db


def count_stale_chunks(provider: str, model: str, dim: int) -> int:
    row = db.read_one(
        "SELECT COUNT(*) AS n FROM mm_entity_chunks "
        "WHERE embedding IS NULL "
        "OR embedding_provider <> %s OR embedding_model <> %s OR embedding_dim <> %s "
        "OR embedding_provider IS NULL OR embedding_model IS NULL OR embedding_dim IS NULL",
        (provider, model, dim),
    )
    return int(row["n"] if row else 0)
