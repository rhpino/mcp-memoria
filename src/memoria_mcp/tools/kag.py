"""tools/kag.py — kag_buscar, kag_evaluar.

Réplica conceptual de omni-mcp kag_buscar y kag_evaluar.

Devuelve AMBOS scores:
- score: RRF score (1/(k+rank)) — usado para ordenar y combinar rankings.
- cosine: cosine similarity raw (sobre embeddings).
- keyword_boost: bonus por keyword match (omni pattern).
"""
from __future__ import annotations

from typing import Optional

import numpy as np

from .. import search as search_mod
from .. import embed as embed_mod


async def kag_buscar(
    query: str,
    scope: Optional[str] = None,
    cross_refs: bool = False,
    hop_depth: int = 0,
    limit: int = 10,
    agent_signature: str = "",
) -> list[dict]:
    """Búsqueda híbrida: vector + keyword + RRF + cross-refs (KAG)."""
    query_emb = await embed_mod.embed_text(query)

    results = await search_mod.hybrid_search(
        query_text=query,
        query_embedding=query_emb if query_emb is not None else np.array([]),
        scope=scope,
        cross_refs=cross_refs,
        hop_depth=hop_depth,
        limit=limit,
        agent_signature=agent_signature,
        embed_text_fn=embed_mod.embed_text,
    )

    return [
        {
            "chunk_id": r.chunk_id,
            "page_slug": r.page_slug,
            "scope": r.scope,
            "heading": r.heading,
            "score": r.score,  # RRF score (1/(k+rank))
            "cosine": getattr(r, "cosine", None),  # raw cosine similarity
            "keyword_boost": getattr(r, "keyword_boost", None),
            "chunk_preview": r.chunk_text[:200],
            "entities_referenced": r.entities_referenced,
        }
        for r in results
    ]


async def kag_evaluar(
    query: str,
    chunk_id: int,
    feedback: str,
    page_slug: str = "",
    agent_signature: str = "",
) -> dict:
    """Persiste feedback de calidad para ajustar pesos."""
    if not query or not chunk_id or not feedback:
        raise ValueError("query, chunk_id, feedback are required")
    search_mod.record_feedback(
        query_text=query,
        chunk_id=chunk_id,
        feedback=feedback,
        page_slug=page_slug,
        agent_signature=agent_signature,
    )
    return {"chunk_id": chunk_id, "feedback": feedback, "recorded": True}