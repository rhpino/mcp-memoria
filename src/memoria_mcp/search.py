"""search.py — Búsqueda híbrida (cosine + keyword + RRF) sobre mm_entity_chunks.

Réplica conceptual del `cosineSearch` de omni-mcp (server.js:446) con:
- Vector cosine sobre embeddings BLOB.
- Keyword boost +0.15 (omni pattern, ver IDEAS.md §Idea 4).
- Reciprocal Rank Fusion (RRF) sobre 3 rankings: vector, keyword, graph (Stage 3).
- Logging de búsqueda en mm_search_log (métricas).
"""
from __future__ import annotations

import logging
import math
import re
import time
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from . import db

log = logging.getLogger("memoria_search")


# ── Data class ────────────────────────────────────────────────────
@dataclass
class SearchResult:
    chunk_id: int
    page_slug: str
    scope: Optional[str]
    chunk_index: int
    heading: Optional[str]
    chunk_text: str
    score: float
    cosine: float = 0.0
    keyword_boost: float = 0.0
    entities_referenced: list[dict] = field(default_factory=list)


# ── Vector cosine sobre mm_entity_chunks ─────────────────────────
def _bytes_to_vec(blob: bytes) -> np.ndarray:
    """Convierte BLOB de float32 a numpy array."""
    return np.frombuffer(blob, dtype=np.float32)


def cosine_search(
    query_embedding: np.ndarray,
    scope: Optional[str] = None,
    limit: int = 10,
    keyword_boost_enabled: bool = True,
    query_text: str = "",
    embedding_provider: str | None = None,
    embedding_model: str | None = None,
    embedding_dim: int | None = None,
) -> list[SearchResult]:
    """Búsqueda por coseno + keyword boost (réplica omni-mcp/server.js:446).

    Score = cosine + keyword_boost (omni pattern).
    keyword_boost = +0.15 * (palabras_match / total_palabras_query)
    """
    if query_embedding is None:
        return []

    q_norm = float(np.linalg.norm(query_embedding))
    if q_norm == 0:
        return []

    # Construir SQL
    sql = (
        "SELECT id, page_slug, chunk_index, heading, chunk_text, "
        "entities_referenced, embedding, scope "
        "FROM mm_entity_chunks WHERE embedding IS NOT NULL"
    )
    params: list = []
    if scope:
        sql += " AND scope = %s"
        params.append(scope)
    if embedding_provider and embedding_model and embedding_dim:
        sql += " AND embedding_provider = %s AND embedding_model = %s AND embedding_dim = %s"
        params.extend([embedding_provider, embedding_model, embedding_dim])

    rows = db.read_many(sql, tuple(params))
    if not rows:
        return []

    # Pre-compute keywords (omni pattern: query words >2 chars)
    query_words = [
        w for w in re.split(r"\s+", (query_text or "").lower()) if len(w) > 2
    ]

    scored: list[tuple[float, float, float, SearchResult]] = []
    for r in rows:
        try:
            emb = _bytes_to_vec(bytes(r["embedding"]))
        except Exception as e:
            log.warning("vec_decode_failed", extra={"chunk_id": r["id"], "error": str(e)})
            continue
        # C1: embedding spaces are now heterogeneous (vertex vs fastembed vs
        # corrupt/truncated BLOBs). Skip any vector whose dimensionality does
        # not match the query instead of crashing np.dot for the whole search.
        if emb.shape[0] != query_embedding.shape[0]:
            log.warning("vec_dim_mismatch_skipped",
                        extra={"chunk_id": r["id"], "emb_dim": int(emb.shape[0]),
                               "query_dim": int(query_embedding.shape[0])})
            continue
        e_norm = float(np.linalg.norm(emb))
        if e_norm == 0:
            continue
        cosine = float(np.dot(query_embedding, emb) / (q_norm * e_norm))

        # Keyword boost (omni: +0.15 per match, capped)
        kw_boost = 0.0
        if keyword_boost_enabled and query_words:
            haystack = (
                (r["chunk_text"] or "") + " " +
                (r["heading"] or "") + " " +
                (r["page_slug"] or "")
            ).lower().replace("-", " ").replace("_", " ")
            matches = sum(1 for w in query_words if w in haystack)
            kw_boost = (matches / len(query_words)) * 0.15

        score = cosine + kw_boost

        # Parse entities_referenced (JSON string → list)
        import json as _json
        try:
            refs = _json.loads(r["entities_referenced"]) if r["entities_referenced"] else []
        except (ValueError, TypeError):
            refs = []

        result = SearchResult(
            chunk_id=r["id"],
            page_slug=r["page_slug"],
            scope=r.get("scope"),
            chunk_index=r["chunk_index"],
            heading=r["heading"],
            chunk_text=r["chunk_text"],
            score=score,
            cosine=cosine,
            keyword_boost=kw_boost,
            entities_referenced=refs,
        )
        scored.append((score, cosine, kw_boost, result))

    scored.sort(key=lambda x: -x[0])
    return [r for _, _, _, r in scored[:limit]]


# ── Keyword (FULLTEXT) search ─────────────────────────────────────
def keyword_search(
    query_text: str,
    scope: Optional[str] = None,
    limit: int = 10,
) -> list[SearchResult]:
    """Búsqueda por FULLTEXT MATCH AGAINST sobre chunk_text + heading."""
    if not query_text.strip():
        return []
    sql = (
        "SELECT id, page_slug, chunk_index, heading, chunk_text, "
        "entities_referenced, scope, "
        "MATCH(chunk_text, heading) AGAINST (%s IN NATURAL LANGUAGE MODE) AS relevance "
        "FROM mm_entity_chunks "
        "WHERE MATCH(chunk_text, heading) AGAINST (%s IN NATURAL LANGUAGE MODE)"
    )
    params: list = [query_text, query_text]
    if scope:
        sql += " AND scope = %s"
        params.append(scope)
    sql += " ORDER BY relevance DESC LIMIT %s"
    params.append(limit)

    rows = db.read_many(sql, tuple(params))
    import json as _json
    out: list[SearchResult] = []
    for r in rows:
        try:
            refs = _json.loads(r["entities_referenced"]) if r["entities_referenced"] else []
        except (ValueError, TypeError):
            refs = []
        out.append(
            SearchResult(
                chunk_id=r["id"],
                page_slug=r["page_slug"],
                scope=r.get("scope"),
                chunk_index=r["chunk_index"],
                heading=r["heading"],
                chunk_text=r["chunk_text"],
                score=float(r.get("relevance", 0)),
                entities_referenced=refs,
            )
        )
    return out


# ── Reciprocal Rank Fusion (RRF) ──────────────────────────────────
def rrf_fuse(
    rankings: list[list[SearchResult]],
    k: int = 60,
    limit: int = 10,
) -> list[SearchResult]:
    """Reciprocal Rank Fusion (Cormack et al. 2009).

    Para cada ranking, asigna score_rrf = sum(1 / (k + rank_i)) sobre cada método.
    Combina resultados por chunk_id.
    """
    scores: dict[int, float] = {}
    by_id: dict[int, SearchResult] = {}
    for ranking in rankings:
        for rank, r in enumerate(ranking, start=1):
            scores[r.chunk_id] = scores.get(r.chunk_id, 0.0) + 1.0 / (k + rank)
            if r.chunk_id not in by_id:
                by_id[r.chunk_id] = r

    # Sort by RRF score
    sorted_ids = sorted(scores.keys(), key=lambda i: -scores[i])
    out: list[SearchResult] = []
    for cid in sorted_ids[:limit]:
        r = by_id[cid]
        r.score = scores[cid]
        out.append(r)
    return out


# ── Hybrid search (entry point) ────────────────────────────────────
async def hybrid_search(
    query_text: str,
    query_embedding: np.ndarray,
    scope: Optional[str] = None,
    cross_refs: bool = False,
    hop_depth: int = 0,
    limit: int = 10,
    agent_signature: str = "",
    embed_text_fn=None,
    embedding_provider: str | None = None,
    embedding_model: str | None = None,
    embedding_dim: int | None = None,
) -> list[SearchResult]:
    """Búsqueda híbrida: vector + keyword + RRF.

    Args:
        cross_refs: si True, expande con entidades referenciadas (hop_depth saltos).
        hop_depth: profundidad de expansion en grafo (0 = sin expansion).
    """
    start = time.time()

    # H6 audit 2026-07-02: kw_boost double-count degrada cosine.
    # cosine_search ya suma kw_boost internamente (hasta +0.15). Si después
    # fusionamos con keyword_search via RRF, las coincidencias exactas reciben
    # doble peso. Solución: en hybrid_search desactivamos kw_boost dentro de
    # cosine_search y dejamos que RRF combine ranking puro (cosine) con ranking
    # léxico (keyword_search) de forma balanceada.
    vector_results = cosine_search(
        query_embedding, scope=scope, limit=limit * 3,
        query_text=query_text,
        keyword_boost_enabled=False,
        embedding_provider=embedding_provider,
        embedding_model=embedding_model,
        embedding_dim=embedding_dim,
    )
    keyword_results = keyword_search(query_text, scope=scope, limit=limit * 3)

    # RRF fusion (k=60 default; tuneado experimentalmente — ver IDEAS.md §Idea 4)
    fused = rrf_fuse([vector_results, keyword_results], k=60, limit=limit)

    # Cross-refs: si True, expandir con entidades referenciadas.
    # Audit mcp-memoria 2026-07-05 (MOP-388) A4/C5: el patrón anterior re-pasaba
    # `fused` (ya combinación de vector+keyword) como 3er ranking en rrf_fuse,
    # causando que items ya rankeados reciban DOBLE RRF score. Bias dramático
    # hacia items en vector/keyword. Fix: cross_refs como ranking INDEPENDIENTE.
    cross_refs_results: list[SearchResult] = []
    if cross_refs and hop_depth > 0 and fused:
        expanded = set(r.chunk_id for r in fused)
        for r in fused[:limit]:
            for ref in r.entities_referenced:
                ent_id = ref.get("id") if isinstance(ref, dict) else None
                if not ent_id:
                    continue
                chunks = db.read_many(
                    "SELECT id, page_slug, chunk_index, heading, chunk_text, "
                    "entities_referenced, scope, embedding "
                    "FROM mm_entity_chunks WHERE JSON_SEARCH(entities_referenced, "
                    "'one', %s) IS NOT NULL LIMIT %s",
                    (ent_id, limit),
                )
                for c in chunks:
                    if c["id"] not in expanded:
                        expanded.add(c["id"])
                        import json as _json
                        try:
                            refs = _json.loads(c["entities_referenced"]) if c["entities_referenced"] else []
                        except (ValueError, TypeError):
                            refs = []
                        cross_refs_results.append(
                            SearchResult(
                                chunk_id=c["id"],
                                page_slug=c["page_slug"],
                                scope=c.get("scope"),
                                chunk_index=c["chunk_index"],
                                heading=c["heading"],
                                chunk_text=c["chunk_text"],
                                score=0.0,
                                entities_referenced=refs,
                            )
                        )
        # Cross-refs como 3er ranking independiente — fusiona con vector+keyword
        # pero NO reusa `fused`. Items presentes en vector/keyword reciben su
        # score RRF una sola vez (no doble).
        fused = rrf_fuse([vector_results, keyword_results, cross_refs_results], k=60, limit=limit)

    latency_ms = int((time.time() - start) * 1000)

    # Audit log
    try:
        db.write_one(
            "INSERT INTO mm_search_log (query_text, method, latency_ms, results_count, cross_refs, agent_signature) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            (
                query_text[:500],
                "hybrid",
                latency_ms,
                len(fused),
                cross_refs,
                agent_signature[:100] if agent_signature else None,
            ),
        )
    except Exception as e:
        log.warning("search_log_failed", extra={"error": str(e)})

    return fused[:limit]


# ── Feedback ─────────────────────────────────────────────────────
def record_feedback(
    query_text: str,
    chunk_id: int,
    feedback: str,  # useful | not_useful | partially_useful
    page_slug: str = "",
    agent_signature: str = "",
) -> None:
    """Persiste feedback para ajustar pesos (kag_evaluar)."""
    if feedback not in ("useful", "not_useful", "partially_useful"):
        raise ValueError(f"feedback must be useful|not_useful|partially_useful, got: {feedback}")
    db.write_one(
        "INSERT INTO mm_search_feedback (query_text, chunk_id, page_slug, feedback, agent_signature) "
        "VALUES (%s, %s, %s, %s, %s)",
        (
            query_text[:500],
            chunk_id,
            page_slug or None,
            feedback,
            agent_signature[:100] if agent_signature else None,
        ),
    )
    log.info(
        "feedback_recorded",
        extra={"query": query_text[:50], "chunk_id": chunk_id, "feedback": feedback},
    )
