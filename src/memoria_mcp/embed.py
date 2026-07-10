"""embed.py — Wrapper async sobre fastembed para mcp-memoria.

Stage 0 model: sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2
(384 dim, 50+ languages including Spanish).
"""
from __future__ import annotations

import asyncio
import logging
import os

import numpy as np
from fastembed import TextEmbedding

log = logging.getLogger("memoria_embed")

DEFAULT_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
DEFAULT_DIM = 384
MAX_CHARS = int(os.environ.get("EMBEDDING_MAX_CHARS", "512"))

_model: TextEmbedding | None = None
_sem = asyncio.Semaphore(int(os.environ.get("EMBEDDING_SEMAPHORE", "4")))


def _get_model() -> TextEmbedding:
    global _model
    if _model is None:
        name = os.environ.get("EMBEDDING_MODEL", DEFAULT_MODEL)
        log.info("loading_embedding_model", extra={"model": name})
        _model = TextEmbedding(model_name=name)
    return _model


async def embed_text(text: str) -> np.ndarray | None:
    if not text or not text.strip():
        return None
    try:
        truncated = text[:MAX_CHARS]
        async with _sem:
            result = await asyncio.to_thread(
                lambda: list(_get_model().embed([truncated]))[0]
            )
        return np.array(result, dtype=np.float32)
    except Exception as e:
        # Audit mcp-memoria 2026-07-05 (MOP-388) C3: re-raise para que el
        # caller (chunker) decida qué hacer, en lugar de degradar silenciosamente
        # a NULL embedding (que el search skip-ea sin error visible).
        log.error("embed_failed", extra={"error": str(e), "text_len": len(text)})
        raise RuntimeError(f"embed_failed: {e}") from e


async def embed_batch(texts: list[str]) -> list[np.ndarray | None]:
    return await asyncio.gather(*[embed_text(t) for t in texts])


def reset_model() -> None:
    global _model
    _model = None


def warmup() -> None:
    _get_model()
    log.info("embedding_model_warmed_up")