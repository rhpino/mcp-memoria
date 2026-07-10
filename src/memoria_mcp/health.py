"""health.py — /health + /metrics."""
from __future__ import annotations

import os

from fastapi import APIRouter, Response

from . import db
from .observability import metrics

router = APIRouter()


@router.get("/health")
async def health() -> dict:
    try:
        h = db.health_check()
    except Exception as e:
        h = {"db": "unknown", "error": str(e)}
    return {
        "status": "ok" if h.get("status") == "ok" else "degraded",
        "name": "mcp-memoria",
        "version": os.environ.get("MCP_VERSION", "0.1.0"),
        "db": h,
        "embed_model": os.environ.get(
            "EMBEDDING_MODEL",
            "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
        ),
        "vector_store": "mariadb-blob",
    }


@router.get("/metrics")
async def prometheus_metrics() -> Response:
    body = metrics.to_prometheus()
    return Response(content=body, media_type="text/plain; version=0.0.4")