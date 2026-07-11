"""embed.py — Async embedding provider for mcp-memoria.

Default provider is Vertex AI via ADC/gcloud. fastembed remains available only
as explicit fallback with EMBEDDING_PROVIDER=fastembed.
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

import numpy as np

from . import vertex_client

log = logging.getLogger("memoria_embed")

EMBEDDING_PROVIDER = os.environ.get("EMBEDDING_PROVIDER", "vertex").lower()
DEFAULT_MODEL = "text-embedding-004"
DEFAULT_DIM = 384
EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", DEFAULT_MODEL)
EMBEDDING_DIM = int(os.environ.get("EMBEDDING_DIM", str(DEFAULT_DIM)))
MAX_CHARS = int(os.environ.get("EMBEDDING_MAX_CHARS", "512"))
VERTEX_PROJECT = os.environ.get("VERTEX_PROJECT") or os.environ.get("GOOGLE_CLOUD_PROJECT", "")
VERTEX_LOCATION = os.environ.get("VERTEX_LOCATION", "us-central1")

_fastembed_model: Any | None = None
_sem = asyncio.Semaphore(int(os.environ.get("EMBEDDING_SEMAPHORE", "4")))


def current_space() -> dict:
    return {
        "provider": EMBEDDING_PROVIDER,
        "model": EMBEDDING_MODEL,
        "dim": EMBEDDING_DIM,
    }


def _vertex_url() -> str:
    if not VERTEX_PROJECT:
        raise RuntimeError("VERTEX_PROJECT or GOOGLE_CLOUD_PROJECT is required for Vertex embeddings")
    return (
        f"https://{VERTEX_LOCATION}-aiplatform.googleapis.com/v1/"
        f"projects/{VERTEX_PROJECT}/locations/{VERTEX_LOCATION}/"
        f"publishers/google/models/{EMBEDDING_MODEL}:predict"
    )


def _parse_vertex_embeddings(data: dict) -> list[np.ndarray]:
    predictions = data.get("predictions")
    if not isinstance(predictions, list):
        raise RuntimeError("Vertex embedding response missing predictions")

    vectors: list[np.ndarray] = []
    for prediction in predictions:
        values = (
            prediction.get("embeddings", {})
            .get("values")
            if isinstance(prediction, dict)
            else None
        )
        if not values:
            raise RuntimeError("Vertex embedding response missing predictions[].embeddings.values")
        vectors.append(np.array(values, dtype=np.float32))
    return vectors


def _call_vertex_embeddings(texts: list[str], task_type: str) -> list[np.ndarray]:
    payload = {
        "instances": [
            {"content": text, "task_type": task_type}
            for text in texts
        ],
        "parameters": {"outputDimensionality": EMBEDDING_DIM},
    }
    data = vertex_client.post_json(
        _vertex_url(),
        payload,
        vertex_client.auth_headers(),
    )
    vectors = _parse_vertex_embeddings(data)
    if len(vectors) != len(texts):
        raise RuntimeError("Vertex embedding response count does not match request count")
    return vectors


def _get_fastembed_model() -> Any:
    global _fastembed_model
    if _fastembed_model is None:
        from fastembed import TextEmbedding

        log.info("loading_fastembed_model", extra={"model": EMBEDDING_MODEL})
        _fastembed_model = TextEmbedding(model_name=EMBEDDING_MODEL)
    return _fastembed_model


def _call_fastembed_embeddings(texts: list[str]) -> list[np.ndarray]:
    return [
        np.array(result, dtype=np.float32)
        for result in _get_fastembed_model().embed(texts)
    ]


async def embed_batch(
    texts: list[str],
    task_type: str = "RETRIEVAL_DOCUMENT",
) -> list[np.ndarray | None]:
    if not texts:
        return []

    out: list[np.ndarray | None] = [None] * len(texts)
    pending: list[str] = []
    pending_indexes: list[int] = []
    for idx, text in enumerate(texts):
        if text and text.strip():
            pending_indexes.append(idx)
            pending.append(text[:MAX_CHARS])

    if not pending:
        return out

    try:
        async with _sem:
            if EMBEDDING_PROVIDER == "vertex":
                vectors = await asyncio.to_thread(
                    lambda: _call_vertex_embeddings(pending, task_type)
                )
            elif EMBEDDING_PROVIDER == "fastembed":
                vectors = await asyncio.to_thread(
                    lambda: _call_fastembed_embeddings(pending)
                )
            else:
                raise RuntimeError(f"unsupported EMBEDDING_PROVIDER={EMBEDDING_PROVIDER!r}")
    except Exception as e:
        log.error(
            "embed_failed",
            extra={
                "provider": EMBEDDING_PROVIDER,
                "model": EMBEDDING_MODEL,
                "task_type": task_type,
                "error": str(e),
                "text_count": len(texts),
            },
        )
        raise RuntimeError(f"embed_failed: {e}") from e

    for idx, vector in zip(pending_indexes, vectors):
        out[idx] = vector
    return out


async def embed_document(text: str) -> np.ndarray | None:
    values = await embed_batch([text], task_type="RETRIEVAL_DOCUMENT")
    return values[0] if values else None


async def embed_query(text: str) -> np.ndarray | None:
    values = await embed_batch([text], task_type="RETRIEVAL_QUERY")
    return values[0] if values else None


async def embed_text(text: str) -> np.ndarray | None:
    return await embed_document(text)


def reset_model() -> None:
    global _fastembed_model
    _fastembed_model = None
    vertex_client.reset_adc_cache()


def warmup() -> None:
    if EMBEDDING_PROVIDER == "vertex":
        vertex_client.get_adc_access_token()
        log.info(
            "embedding_provider_warmed_up",
            extra={"provider": "vertex", "model": EMBEDDING_MODEL},
        )
        return
    if EMBEDDING_PROVIDER == "fastembed":
        _get_fastembed_model()
        log.info(
            "embedding_provider_warmed_up",
            extra={"provider": "fastembed", "model": EMBEDDING_MODEL},
        )
        return
    raise RuntimeError(f"unsupported EMBEDDING_PROVIDER={EMBEDDING_PROVIDER!r}")
