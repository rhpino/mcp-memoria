# C1 Vertex Embeddings Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the hot-path local fastembed/ONNX model from mcp-memoria by moving KAG/wiki embeddings to Vertex AI with ADC, without silently comparing vectors from incompatible embedding spaces.

**Architecture:** Introduce a single shared Vertex HTTP/ADC helper, split document and query embedding calls, and persist embedding-space metadata on each chunk. `EMBEDDING_DIM=384` preserves vector shape only; it does **not** make Vertex vectors comparable with existing fastembed vectors. The cutover must therefore include metadata gating plus a supervised full reindex before Vertex vector search is considered enabled.

**Tech Stack:** Python 3.14, pytest, numpy, urllib.request, subprocess `gcloud`, MariaDB BLOB embeddings, Vertex AI embeddings.

## Global Constraints

- No live network calls in pytest; mock token and HTTP helpers.
- No Gemini API key path for embeddings.
- Use ADC via `gcloud auth application-default print-access-token`.
- Keep `EMBEDDING_DIM=384` only to preserve storage shape and test simplicity; never claim it preserves semantic compatibility.
- Do not compare query vectors against chunks from a different embedding provider/model/dim.
- Persist `embedding_provider`, `embedding_model`, and `embedding_dim` per chunk.
- `kag_buscar` must embed queries with `RETRIEVAL_QUERY`.
- `wiki_escribir`/chunk indexing must embed chunks with `RETRIEVAL_DOCUMENT`.
- Reindex is mandatory before enabling Vertex vector search over production corpus.
- Keep fastembed only as explicit fallback: `EMBEDDING_PROVIDER=fastembed`.
- Do not remove `fastembed` from `pyproject.toml` in this PR.
- Model choice: start from local source-of-truth `CLAUDE.md` default `text-embedding-004`. `gemini-embedding-001` can replace it only after a live smoke proves `:predict`, `outputDimensionality`, and task types work in this project.

---

## File Structure

- Create `src/memoria_mcp/vertex_client.py`: shared ADC token cache and JSON POST helper for bibliotecario and embed.
- Modify `src/memoria_mcp/bibliotecario.py`: reuse `vertex_client` instead of duplicating ADC/HTTP.
- Modify `src/memoria_mcp/embed.py`: provider selection, batch Vertex calls, `embed_document`, `embed_query`, explicit fastembed fallback.
- Modify `src/memoria_mcp/db.py`: add embedding metadata columns to `mm_entity_chunks`.
- Modify `src/memoria_mcp/chunker.py`: persist embedding metadata returned by `embed.py`.
- Modify `src/memoria_mcp/search.py`: filter cosine rows by current embedding space.
- Modify `src/memoria_mcp/tools/kag.py`: use `embed_query` for the user query and `embed_document` for reindex/chunk paths.
- Create `src/memoria_mcp/embed_admin.py`: count stale chunks for health and reindex scripts.
- Modify `src/memoria_mcp/health.py`: report provider/model/dim and vector-space status.
- Modify `.env.example` and `src/memoria_mcp/__init__.py`: align docs with Vertex ADC.
- Create `tests/test_vertex_client.py`, `tests/test_embed_vertex.py`, `tests/test_embedding_space.py`, and `scripts/reindex_embeddings.py`.

---

### Task 1: Shared Vertex Client

**Files:**
- Create: `tests/test_vertex_client.py`
- Create: `src/memoria_mcp/vertex_client.py`
- Modify: `src/memoria_mcp/bibliotecario.py`

**Interfaces:**
- Produces:
  - `vertex_client.get_adc_access_token() -> str`
  - `vertex_client.post_json(url: str, payload: dict, headers: dict, timeout: int = 30) -> dict`
  - `vertex_client.auth_headers() -> dict[str, str]`

- [ ] **Step 1: Write failing tests**

Create `tests/test_vertex_client.py`:

```python
from __future__ import annotations

import pytest


def test_adc_token_is_cached(monkeypatch):
    from memoria_mcp import vertex_client

    vertex_client.reset_adc_cache()
    calls = []

    def fake_check_output(cmd, text, timeout):
        calls.append(cmd)
        return "token-1\n"

    monkeypatch.setattr(vertex_client.subprocess, "check_output", fake_check_output)
    monkeypatch.setattr(vertex_client.time, "time", lambda: 1000.0)

    assert vertex_client.get_adc_access_token() == "token-1"
    assert vertex_client.get_adc_access_token() == "token-1"
    assert calls == [[vertex_client.GCLOUD_BIN, "auth", "application-default", "print-access-token"]]


def test_adc_token_refreshes_after_expiry(monkeypatch):
    from memoria_mcp import vertex_client

    vertex_client.reset_adc_cache()
    calls = []

    def fake_check_output(cmd, text, timeout):
        calls.append(cmd)
        return f"token-{len(calls)}\n"

    now = {"value": 1000.0}
    monkeypatch.setattr(vertex_client.subprocess, "check_output", fake_check_output)
    monkeypatch.setattr(vertex_client.time, "time", lambda: now["value"])

    assert vertex_client.get_adc_access_token() == "token-1"
    now["value"] += 51 * 60
    assert vertex_client.get_adc_access_token() == "token-2"


def test_auth_headers_use_bearer(monkeypatch):
    from memoria_mcp import vertex_client

    monkeypatch.setattr(vertex_client, "get_adc_access_token", lambda: "adc-token")

    assert vertex_client.auth_headers() == {
        "Content-Type": "application/json",
        "Authorization": "Bearer adc-token",
    }
```

- [ ] **Step 2: Verify RED**

Run:

```bash
/opt/mcps/memoria/.venv/bin/python -m pytest tests/test_vertex_client.py -q
```

Expected: FAIL because `vertex_client` does not exist.

- [ ] **Step 3: Implement shared helper**

Create `src/memoria_mcp/vertex_client.py`:

```python
from __future__ import annotations

import json
import os
import subprocess
import time
import urllib.request

GCLOUD_BIN = os.environ.get("GCLOUD_BIN", "/snap/bin/gcloud")

_adc_token: str | None = None
_adc_token_expires_at = 0.0


def reset_adc_cache() -> None:
    global _adc_token, _adc_token_expires_at
    _adc_token = None
    _adc_token_expires_at = 0.0


def get_adc_access_token() -> str:
    global _adc_token, _adc_token_expires_at
    now = time.time()
    if _adc_token and now < _adc_token_expires_at:
        return _adc_token

    out = subprocess.check_output(
        [GCLOUD_BIN, "auth", "application-default", "print-access-token"],
        text=True,
        timeout=10,
    )
    token = out.strip()
    if not token:
        raise RuntimeError("gcloud returned empty ADC token")
    _adc_token = token
    _adc_token_expires_at = now + 50 * 60
    return token


def auth_headers() -> dict[str, str]:
    return {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {get_adc_access_token()}",
    }


def post_json(url: str, payload: dict, headers: dict, timeout: int = 30) -> dict:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))
```

- [ ] **Step 4: Refactor bibliotecario**

In `src/memoria_mcp/bibliotecario.py`, remove local ADC globals/helpers and import:

```python
from . import vertex_client
```

Change Vertex call to:

```python
data = vertex_client.post_json(
    url,
    {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"maxOutputTokens": 8192, "temperature": 0.3},
    },
    vertex_client.auth_headers(),
)
```

- [ ] **Step 5: Verify GREEN**

Run:

```bash
/opt/mcps/memoria/.venv/bin/python -m pytest tests/test_vertex_client.py tests/test_bibliotecario.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/memoria_mcp/vertex_client.py src/memoria_mcp/bibliotecario.py tests/test_vertex_client.py
git commit -m "refactor(vertex): share ADC HTTP helper"
```

---

### Task 2: Vertex Embedding Provider With Query/Document Split

**Files:**
- Create: `tests/test_embed_vertex.py`
- Modify: `src/memoria_mcp/embed.py`

**Interfaces:**
- Produces:
  - `current_space() -> dict`
  - `embed_document(text: str) -> np.ndarray | None`
  - `embed_query(text: str) -> np.ndarray | None`
  - `embed_batch(texts: list[str], task_type: str = "RETRIEVAL_DOCUMENT") -> list[np.ndarray | None]`
  - `embed_text(text: str) -> np.ndarray | None` as a compatibility alias for `embed_document`

- [ ] **Step 1: Write failing tests**

Create `tests/test_embed_vertex.py`:

```python
from __future__ import annotations

import importlib

import numpy as np
import pytest


def _reload_embed(monkeypatch, **env):
    for key in [
        "EMBEDDING_PROVIDER",
        "EMBEDDING_MODEL",
        "EMBEDDING_DIM",
        "EMBEDDING_MAX_CHARS",
        "VERTEX_PROJECT",
        "GOOGLE_CLOUD_PROJECT",
        "VERTEX_LOCATION",
    ]:
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, str(value))

    import memoria_mcp.embed as embed_mod

    return importlib.reload(embed_mod)


def test_current_space_defaults_to_vertex_shape_384(monkeypatch):
    embed_mod = _reload_embed(monkeypatch, VERTEX_PROJECT="test-project")

    assert embed_mod.current_space() == {
        "provider": "vertex",
        "model": "text-embedding-004",
        "dim": 384,
    }


@pytest.mark.asyncio
async def test_embed_document_uses_retrieval_document(monkeypatch):
    embed_mod = _reload_embed(monkeypatch, VERTEX_PROJECT="test-project")
    calls = {}

    def fake_post_json(url, payload, headers, timeout=30):
        calls["payload"] = payload
        return {"predictions": [{"embeddings": {"values": [0.1, 0.2]}}]}

    async def fake_to_thread(fn):
        return fn()

    monkeypatch.setattr(embed_mod.vertex_client, "auth_headers", lambda: {"Authorization": "Bearer adc-token"})
    monkeypatch.setattr(embed_mod.vertex_client, "post_json", fake_post_json)
    monkeypatch.setattr(embed_mod.asyncio, "to_thread", fake_to_thread)

    result = await embed_mod.embed_document("doc text")

    assert isinstance(result, np.ndarray)
    assert result.tolist() == pytest.approx([0.1, 0.2])
    assert calls["payload"]["instances"][0]["task_type"] == "RETRIEVAL_DOCUMENT"


@pytest.mark.asyncio
async def test_embed_query_uses_retrieval_query(monkeypatch):
    embed_mod = _reload_embed(monkeypatch, VERTEX_PROJECT="test-project")
    calls = {}

    def fake_post_json(url, payload, headers, timeout=30):
        calls["payload"] = payload
        return {"predictions": [{"embeddings": {"values": [0.3, 0.4]}}]}

    async def fake_to_thread(fn):
        return fn()

    monkeypatch.setattr(embed_mod.vertex_client, "auth_headers", lambda: {"Authorization": "Bearer adc-token"})
    monkeypatch.setattr(embed_mod.vertex_client, "post_json", fake_post_json)
    monkeypatch.setattr(embed_mod.asyncio, "to_thread", fake_to_thread)

    result = await embed_mod.embed_query("query text")

    assert result.tolist() == pytest.approx([0.3, 0.4])
    assert calls["payload"]["instances"][0]["task_type"] == "RETRIEVAL_QUERY"


@pytest.mark.asyncio
async def test_embed_batch_sends_multiple_instances_once(monkeypatch):
    embed_mod = _reload_embed(monkeypatch, VERTEX_PROJECT="test-project")
    calls = []

    def fake_post_json(url, payload, headers, timeout=30):
        calls.append(payload)
        return {
            "predictions": [
                {"embeddings": {"values": [1.0, 0.0]}},
                {"embeddings": {"values": [0.0, 1.0]}},
            ]
        }

    async def fake_to_thread(fn):
        return fn()

    monkeypatch.setattr(embed_mod.vertex_client, "auth_headers", lambda: {"Authorization": "Bearer adc-token"})
    monkeypatch.setattr(embed_mod.vertex_client, "post_json", fake_post_json)
    monkeypatch.setattr(embed_mod.asyncio, "to_thread", fake_to_thread)

    result = await embed_mod.embed_batch(["a", "b"])

    assert len(calls) == 1
    assert [v.tolist() for v in result] == [[1.0, 0.0], [0.0, 1.0]]
    assert [i["content"] for i in calls[0]["instances"]] == ["a", "b"]


@pytest.mark.asyncio
async def test_malformed_vertex_response_raises(monkeypatch):
    embed_mod = _reload_embed(monkeypatch, VERTEX_PROJECT="test-project")

    def fake_post_json(url, payload, headers, timeout=30):
        return {"predictions": [{}]}

    async def fake_to_thread(fn):
        return fn()

    monkeypatch.setattr(embed_mod.vertex_client, "auth_headers", lambda: {"Authorization": "Bearer adc-token"})
    monkeypatch.setattr(embed_mod.vertex_client, "post_json", fake_post_json)
    monkeypatch.setattr(embed_mod.asyncio, "to_thread", fake_to_thread)

    with pytest.raises(RuntimeError, match="embedding"):
        await embed_mod.embed_query("x")
```

- [ ] **Step 2: Verify RED**

Run:

```bash
/opt/mcps/memoria/.venv/bin/python -m pytest tests/test_embed_vertex.py -q
```

Expected: FAIL because the current provider has no split query/document API.

- [ ] **Step 3: Implement provider**

Modify `src/memoria_mcp/embed.py` with these concrete rules:

```python
EMBEDDING_PROVIDER = os.environ.get("EMBEDDING_PROVIDER", "vertex").lower()
DEFAULT_MODEL = "text-embedding-004"
DEFAULT_DIM = 384
EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", DEFAULT_MODEL)
EMBEDDING_DIM = int(os.environ.get("EMBEDDING_DIM", str(DEFAULT_DIM)))
VERTEX_PROJECT = os.environ.get("VERTEX_PROJECT") or os.environ.get("GOOGLE_CLOUD_PROJECT", "")
VERTEX_LOCATION = os.environ.get("VERTEX_LOCATION", "us-central1")
```

Implement:

```python
def current_space() -> dict:
    return {"provider": EMBEDDING_PROVIDER, "model": EMBEDDING_MODEL, "dim": EMBEDDING_DIM}


def _vertex_url() -> str:
    if not VERTEX_PROJECT:
        raise RuntimeError("VERTEX_PROJECT or GOOGLE_CLOUD_PROJECT is required for Vertex embeddings")
    return (
        f"https://{VERTEX_LOCATION}-aiplatform.googleapis.com/v1/"
        f"projects/{VERTEX_PROJECT}/locations/{VERTEX_LOCATION}/"
        f"publishers/google/models/{EMBEDDING_MODEL}:predict"
    )
```

Vertex payload shape:

```python
payload = {
    "instances": [
        {"content": text, "task_type": task_type}
        for text in truncated_texts
    ],
    "parameters": {"outputDimensionality": EMBEDDING_DIM},
}
```

Public calls:

```python
async def embed_document(text: str) -> np.ndarray | None:
    values = await embed_batch([text], task_type="RETRIEVAL_DOCUMENT")
    return values[0] if values else None


async def embed_query(text: str) -> np.ndarray | None:
    values = await embed_batch([text], task_type="RETRIEVAL_QUERY")
    return values[0] if values else None


async def embed_text(text: str) -> np.ndarray | None:
    return await embed_document(text)
```

For `EMBEDDING_PROVIDER=fastembed`, keep one local model singleton and use it only when explicitly configured.

- [ ] **Step 4: Verify GREEN**

Run:

```bash
/opt/mcps/memoria/.venv/bin/python -m pytest tests/test_embed_vertex.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/memoria_mcp/embed.py tests/test_embed_vertex.py
git commit -m "fix(embed): add Vertex query and document embeddings"
```

---

### Task 3: Embedding-Space Metadata and Safe Search

**Files:**
- Create: `tests/test_embedding_space.py`
- Modify: `src/memoria_mcp/db.py`
- Modify: `src/memoria_mcp/chunker.py`
- Modify: `src/memoria_mcp/search.py`
- Modify: `src/memoria_mcp/tools/kag.py`

**Interfaces:**
- Consumes: `embed.current_space()`, `embed.embed_document`, `embed.embed_query`.
- Produces: DB metadata columns and search filtering by vector space.

- [ ] **Step 1: Write failing tests**

Create `tests/test_embedding_space.py`:

```python
from __future__ import annotations

import numpy as np
import pytest

from memoria_mcp import db, search


def test_cosine_search_ignores_mismatched_embedding_space(isolate_test_db):
    db.write_one(
        "INSERT INTO mm_entity_chunks "
        "(page_slug, chunk_index, heading, chunk_text, entities_referenced, word_count, embedding, scope, "
        "embedding_provider, embedding_model, embedding_dim) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (
            "test/mixed-space",
            0,
            "Mixed",
            "Old fastembed vector",
            "[]",
            3,
            np.array([1.0, 0.0] + [0.0] * 382, dtype=np.float32).tobytes(),
            "decisions",
            "fastembed",
            "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
            384,
        ),
    )

    results = search.cosine_search(
        np.array([1.0, 0.0] + [0.0] * 382, dtype=np.float32),
        scope="decisions",
        limit=10,
        embedding_provider="vertex",
        embedding_model="text-embedding-004",
        embedding_dim=384,
    )

    assert results == []


@pytest.mark.asyncio
async def test_kag_buscar_uses_query_embedding(monkeypatch):
    from memoria_mcp.tools import kag

    calls = []

    async def fake_embed_query(text):
        calls.append(("query", text))
        return np.array([1.0, 0.0], dtype=np.float32)

    async def fake_hybrid_search(**kwargs):
        calls.append(("hybrid", kwargs["query_embedding"].tolist()))
        return []

    monkeypatch.setattr(kag.embed_mod, "embed_query", fake_embed_query)
    monkeypatch.setattr(kag.search_mod, "hybrid_search", fake_hybrid_search)

    assert await kag.kag_buscar("hola") == []
    assert calls[0] == ("query", "hola")
```

- [ ] **Step 2: Verify RED**

Run:

```bash
/opt/mcps/memoria/.venv/bin/python -m pytest tests/test_embedding_space.py -q
```

Expected: FAIL because metadata columns/search filters do not exist and `kag_buscar` still uses `embed_text`.

- [ ] **Step 3: Add schema metadata columns**

Modify `src/memoria_mcp/db.py` `mm_entity_chunks` DDL:

```sql
embedding_provider VARCHAR(32),
embedding_model VARCHAR(128),
embedding_dim INT,
```

Add idempotent migrations:

```python
"ALTER TABLE mm_entity_chunks ADD COLUMN IF NOT EXISTS embedding_provider VARCHAR(32) NULL AFTER embedding",
"ALTER TABLE mm_entity_chunks ADD COLUMN IF NOT EXISTS embedding_model VARCHAR(128) NULL AFTER embedding_provider",
"ALTER TABLE mm_entity_chunks ADD COLUMN IF NOT EXISTS embedding_dim INT NULL AFTER embedding_model",
```

- [ ] **Step 4: Persist metadata in chunker**

Modify `chunk_and_index` so after a successful embedding it gets:

```python
from . import embed as embed_mod

embedding_space = embed_mod.current_space()
```

Insert `embedding_provider`, `embedding_model`, `embedding_dim` with each chunk.

- [ ] **Step 5: Filter search by embedding space**

Modify `search.cosine_search` signature:

```python
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
```

Add SQL filters when all metadata is present:

```python
if embedding_provider and embedding_model and embedding_dim:
    sql += " AND embedding_provider = %s AND embedding_model = %s AND embedding_dim = %s"
    params.extend([embedding_provider, embedding_model, embedding_dim])
```

Modify `hybrid_search` to accept the same metadata and pass it to `cosine_search`.

- [ ] **Step 6: Use query embeddings in KAG**

Modify `src/memoria_mcp/tools/kag.py`:

```python
query_emb = await embed_mod.embed_query(query)
space = embed_mod.current_space()
```

Pass `embedding_provider=space["provider"]`, `embedding_model=space["model"]`, and `embedding_dim=space["dim"]` into `hybrid_search`.

- [ ] **Step 7: Verify GREEN**

Run:

```bash
/opt/mcps/memoria/.venv/bin/python -m pytest tests/test_embedding_space.py tests/test_search.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/memoria_mcp/db.py src/memoria_mcp/chunker.py src/memoria_mcp/search.py src/memoria_mcp/tools/kag.py tests/test_embedding_space.py
git commit -m "fix(search): gate cosine by embedding space"
```

---

### Task 4: Mandatory Reindex Script and Gate

**Files:**
- Create: `scripts/reindex_embeddings.py`
- Create: `src/memoria_mcp/embed_admin.py`
- Create: `tests/test_reindex_embeddings.py`
- Modify: `src/memoria_mcp/health.py`

**Interfaces:**
- Produces a supervised operation that re-embeds all wiki pages/chunks into the current embedding space before Vertex vector search is considered healthy.

- [ ] **Step 1: Write failing tests for stale-space count**

Create `tests/test_reindex_embeddings.py`:

```python
from __future__ import annotations

from memoria_mcp import db


def test_count_stale_embedding_chunks(isolate_test_db):
    from memoria_mcp import embed_admin

    db.write_one(
        "INSERT INTO mm_entity_chunks "
        "(page_slug, chunk_index, heading, chunk_text, entities_referenced, word_count, embedding, scope, "
        "embedding_provider, embedding_model, embedding_dim) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        ("test/stale", 0, "h", "body", "[]", 1, b\"1234\", "decisions", "fastembed", "old", 384),
    )

    assert embed_admin.count_stale_chunks("vertex", "text-embedding-004", 384) >= 1
```

- [ ] **Step 2: Verify RED**

Run:

```bash
/opt/mcps/memoria/.venv/bin/python -m pytest tests/test_reindex_embeddings.py -q
```

Expected: FAIL because the script does not exist.

- [ ] **Step 3: Add admin helper and script**

Create `src/memoria_mcp/embed_admin.py`:

```python
from __future__ import annotations

from . import db


def count_stale_chunks(provider: str, model: str, dim: int) -> int:
    row = db.read_one(
        "SELECT COUNT(*) AS n FROM mm_entity_chunks "
        "WHERE embedding IS NULL OR embedding_provider <> %s OR embedding_model <> %s OR embedding_dim <> %s "
        "OR embedding_provider IS NULL OR embedding_model IS NULL OR embedding_dim IS NULL",
        (provider, model, dim),
    )
    return int(row["n"] if row else 0)
```

Create `scripts/reindex_embeddings.py` with:

```python
from __future__ import annotations

import argparse
import asyncio

from memoria_mcp import db, embed, embed_admin
from memoria_mcp.chunker import chunk_and_index


async def reindex_all(dry_run: bool = True) -> dict:
    space = embed.current_space()
    stale = embed_admin.count_stale_chunks(space["provider"], space["model"], space["dim"])
    if dry_run:
        return {"dry_run": True, "stale_chunks": stale, "space": space}

    pages = db.read_many(
        "SELECT p.slug, p.body, p.scope FROM mm_wiki_pages p "
        "JOIN (SELECT slug, MAX(version) AS version FROM mm_wiki_pages GROUP BY slug) latest "
        "ON p.slug = latest.slug AND p.version = latest.version "
        "ORDER BY p.slug"
    )
    count = 0
    for page in pages:
        count += await chunk_and_index(
            page_slug=page["slug"],
            content=page["body"],
            scope=page.get("scope") or "",
            title=page["slug"],
            embed_text_fn=embed.embed_document,
        )
    return {"dry_run": False, "pages": len(pages), "chunks": count, "space": space}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    print(asyncio.run(reindex_all(dry_run=not args.apply)))


if __name__ == "__main__":
    main()
```

This script intentionally reindexes from `mm_wiki_pages`, because today `wiki_escribir` is the only supported chunk ingestion path. If another ingestion path is added later, it must either write to `mm_wiki_pages` or add its own reindex source before this gate can be considered complete.

- [ ] **Step 4: Health exposes stale count**

Modify `src/memoria_mcp/health.py` to include:

```python
from . import embed, embed_admin

space = embed.current_space()

"embedding": {
    "provider": embed.EMBEDDING_PROVIDER,
    "model": embed.EMBEDDING_MODEL,
    "dim": embed.EMBEDDING_DIM,
    "stale_chunks": embed_admin.count_stale_chunks(
        space["provider"],
        space["model"],
        space["dim"],
    ),
}
```

- [ ] **Step 5: Verify script dry run**

Run:

```bash
PYTHONPATH=/opt/mcps/memoria /opt/mcps/memoria/.venv/bin/python scripts/reindex_embeddings.py
```

Expected: prints dry-run dict and writes no DB rows.

- [ ] **Step 6: Commit**

```bash
git add src/memoria_mcp/embed_admin.py scripts/reindex_embeddings.py tests/test_reindex_embeddings.py src/memoria_mcp/health.py
git commit -m "feat(embed): add supervised reindex gate"
```

---

### Task 5: Live Smoke Before Choosing Final Model

**Files:**
- Create: `scripts/smoke_vertex_embedding.py`

**Interfaces:**
- Produces a no-write live check for ADC/model/task/dim support.

- [ ] **Step 1: Add smoke script**

Create `scripts/smoke_vertex_embedding.py`:

```python
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
        }
    )


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 2: Run smoke for source-of-truth model**

Run:

```bash
/snap/bin/gcloud auth application-default print-access-token >/dev/null && \
EMBEDDING_MODEL=text-embedding-004 \
PYTHONPATH=/opt/mcps/memoria /opt/mcps/memoria/.venv/bin/python scripts/smoke_vertex_embedding.py
```

Expected: `dim_doc=384`, `dim_query=384`, both nonzero.

- [ ] **Step 3: Optional model probe**

Only after `text-embedding-004` smoke passes, optionally run:

```bash
EMBEDDING_MODEL=gemini-embedding-001 \
PYTHONPATH=/opt/mcps/memoria /opt/mcps/memoria/.venv/bin/python scripts/smoke_vertex_embedding.py
```

If it passes, open a separate decision note to switch the default model. Do not silently change the default inside this C1 fix.

- [ ] **Step 4: Commit**

```bash
git add scripts/smoke_vertex_embedding.py
git commit -m "test(embed): add Vertex embedding smoke script"
```

---

### Task 6: Full Verification and PR

**Files:**
- No code changes unless verification exposes a bug.

- [ ] **Step 1: Run diff check**

```bash
git diff --check
```

Expected: no output, exit 0.

- [ ] **Step 2: Run focused tests**

```bash
/opt/mcps/memoria/.venv/bin/python -m pytest \
  tests/test_vertex_client.py \
  tests/test_embed_vertex.py \
  tests/test_embedding_space.py \
  tests/test_reindex_embeddings.py \
  tests/test_bibliotecario.py \
  tests/test_search.py -q
```

Expected: PASS.

- [ ] **Step 3: Run full suite**

```bash
/opt/mcps/memoria/.venv/bin/python -m pytest -q
```

Expected: all tests pass. Baseline before C1 is `89 passed, 1 skipped`.

- [ ] **Step 4: Create PR**

```bash
git push -u origin fix/c1-vertex-embeddings-2026-07-10
gh pr create --draft \
  --title "fix(embed): use Vertex embeddings via ADC with safe reindex gate" \
  --body-file /tmp/c1-vertex-embeddings-pr.md
```

PR body must state:

```markdown
## Summary

Closes C1 by moving hot-path embeddings from local fastembed/ONNX to Vertex AI via ADC.

## Safety

- Vector shape compatibility is not semantic compatibility.
- Existing fastembed chunks are not compared against Vertex query vectors.
- Chunk rows now store embedding provider/model/dim.
- Cosine search filters by embedding space.
- Full reindex is mandatory before Vertex vector search is considered healthy.

## Retrieval Quality

- Indexing uses `RETRIEVAL_DOCUMENT`.
- Query search uses `RETRIEVAL_QUERY`.
- Batch embedding sends multiple chunks in one Vertex request.

## Tests

- `pytest tests/test_vertex_client.py tests/test_embed_vertex.py tests/test_embedding_space.py tests/test_reindex_embeddings.py tests/test_bibliotecario.py tests/test_search.py -q`
- `pytest -q`

## Live Smoke

```bash
EMBEDDING_MODEL=text-embedding-004 \
PYTHONPATH=/opt/mcps/memoria /opt/mcps/memoria/.venv/bin/python scripts/smoke_vertex_embedding.py
```
```

---

## Self-Review

- Corrected false premise: `384` preserves shape only, not vector-space compatibility.
- Mixed-space comparison is blocked by metadata filters.
- Reindex is mandatory and represented by code, not a footnote.
- Query/document task types are split.
- Vertex ADC/HTTP is shared with bibliotecario.
- Batch embedding is included for indexing efficiency.
- Default model follows local constraint `CLAUDE.md`; any change to `gemini-embedding-001` requires successful live smoke and a separate decision.
