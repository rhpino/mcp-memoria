"""Manual smoke test for Vertex embeddings.

Runs one document + one query embedding and prints metadata only.
Does not write to DB. Use to verify ADC + model + task_type + dim before
enabling Vertex vector search over production corpus.

    gcloud auth application-default print-access-token >/dev/null && \
    EMBEDDING_MODEL=text-embedding-004 \
    PYTHONPATH=/opt/mcps/memoria \
    /opt/mcps/memoria/.venv/bin/python scripts/smoke_vertex_embedding.py
"""
from __future__ import annotations

import asyncio
import os

from memoria_mcp import embed


async def main() -> None:
    text = os.environ.get("SMOKE_EMBED_TEXT", "mcp memoria vertex embedding smoke")
    doc = await embed.embed_document(text)
    query = await embed.embed_query(text)
    if doc is None or query is None:
        raise SystemExit("embedding returned None")
    print(
        {
            "provider": embed.EMBEDDING_PROVIDER,
            "model": embed.EMBEDDING_MODEL,
            "dim_doc": int(doc.shape[0]),
            "dim_query": int(query.shape[0]),
            "dtype": str(doc.dtype),
            "doc_nonzero": bool((doc != 0).any()),
            "query_nonzero": bool((query != 0).any()),
            "space": embed.current_space(),
        }
    )


if __name__ == "__main__":
    asyncio.run(main())
