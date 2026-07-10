"""health.py — /health + /metrics."""
from __future__ import annotations

import os

from fastapi import APIRouter, Response

from . import db, embed, embed_admin
from .observability import metrics

router = APIRouter()


@router.get("/health")
async def health() -> dict:
    try:
        h = db.health_check()
    except Exception as e:
        h = {"db": "unknown", "error": str(e)}
    space = embed.current_space()
    try:
        stale_chunks = embed_admin.count_stale_chunks(
            space["provider"],
            space["model"],
            space["dim"],
        )
    except Exception as e:
        stale_chunks = None
        h.setdefault("warnings", []).append(f"embedding_stale_count_error: {e}")
    return {
        "status": "ok" if h.get("status") == "ok" else "degraded",
        "name": "mcp-memoria",
        "version": os.environ.get("MCP_VERSION", "0.1.0"),
        "db": h,
        "embedding": {
            "provider": space["provider"],
            "model": space["model"],
            "dim": space["dim"],
            "stale_chunks": stale_chunks,
        },
        "vector_store": "mariadb-blob",
    }


@router.get("/metrics")
async def prometheus_metrics() -> Response:
    body = metrics.to_prometheus()
    return Response(content=body, media_type="text/plain; version=0.0.4")
