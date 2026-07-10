"""chunker.py — Port conceptual de omni-mcp `autoChunkAndIndex()`.

Patrón omni-mcp (server.js:376):
1. Split content por `###` y `##` headings; heredar el current heading.
2. Si un chunk es >MAX_CHUNK_CHARS, split adicional por párrafos.
3. Si no hay párrafos, split por sentences (heuristic).
4. Crear chunks con paragraph lines; chunks ≥MIN_CHUNK_CHARS.
5. Detectar entidades referenciadas (case-insensitive match en nombre).
6. Generar embedding por chunk (con fastembed).
7. INSERT en mm_entity_chunks.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Optional

import numpy as np

from . import db

log = logging.getLogger("memoria_chunker")

MIN_CHUNK_CHARS = 50
MAX_CHUNK_CHARS = 1500
SENTENCE_OVERLAP = 100  # chars de overlap entre sentences


def _split_by_headings(content: str) -> list[tuple[str, str]]:
    """Split content por headings (##, ###). Returns [(heading, text), ...]."""
    lines = content.split("\n")
    chunks: list[tuple[str, str]] = []
    current_heading = "general"
    current_paragraph: list[str] = []

    for line in lines:
        stripped = line.strip()
        if line.startswith("### ") or line.startswith("## "):
            if current_paragraph:
                text = "\n".join(current_paragraph).strip()
                if len(text) >= MIN_CHUNK_CHARS:
                    _extend_chunks(chunks, current_heading, text)
                current_paragraph = []
            current_heading = re.sub(r"^#{2,3}\s+", "", line).strip() or "general"
        elif stripped == "":
            if current_paragraph:
                text = "\n".join(current_paragraph).strip()
                if len(text) >= MIN_CHUNK_CHARS:
                    _extend_chunks(chunks, current_heading, text)
                current_paragraph = []
        else:
            current_paragraph.append(line)

    if current_paragraph:
        text = "\n".join(current_paragraph).strip()
        if len(text) >= MIN_CHUNK_CHARS:
            _extend_chunks(chunks, current_heading, text)

    return chunks


def _extend_chunks(chunks: list[tuple[str, str]], heading: str, text: str) -> None:
    """Si text > MAX_CHUNK_CHARS, split por párrafos o sentences."""
    if len(text) <= MAX_CHUNK_CHARS:
        chunks.append((heading, text))
        return

    # First try: split por párrafos (doble newline)
    paragraphs = re.split(r"\n\s*\n", text)
    if len(paragraphs) > 1:
        _add_by_paragraphs(chunks, heading, text, paragraphs)
        return

    # No hay párrafos — split por sentences
    sentences = _split_sentences(text)
    _add_by_sentences(chunks, heading, text, sentences)


def _add_by_paragraphs(chunks, heading, full_text, paragraphs) -> None:
    """Agrupa paragraphs en chunks ≤ MAX_CHUNK_CHARS."""
    current = []
    current_len = 0
    sub_idx = 0
    for p in paragraphs:
        p = p.strip()
        if not p:
            continue
        if current_len + len(p) + 2 > MAX_CHUNK_CHARS and current:
            sub_text = "\n\n".join(current)
            sub_heading = f"{heading} (part {sub_idx + 1})" if sub_idx > 0 else heading
            chunks.append((sub_heading, sub_text))
            sub_idx += 1
            current = [p]
            current_len = len(p)
        else:
            current.append(p)
            current_len += len(p) + 2

    if current:
        sub_text = "\n\n".join(current)
        sub_heading = f"{heading} (part {sub_idx + 1})" if sub_idx > 0 else heading
        chunks.append((sub_heading, sub_text))


def _split_sentences(text: str) -> list[str]:
    """Split texto en sentences usando heuristic (`. `, `! `, `? `, newlines)."""
    # Split ANTES de periods/exclamations/questions seguidas de mayúscula o newline
    sentences = re.split(r"(?<=[.!?])\s+(?=[A-ZÁÉÍÓÚÑ])|(?<=\.)\s*\n", text)
    return [s.strip() for s in sentences if s.strip()]


def _add_by_sentences(chunks, heading, full_text, sentences) -> None:
    """Agrupa sentences en chunks ≤ MAX_CHUNK_CHARS, con overlap."""
    sub_idx = 0
    current = []
    current_len = 0

    for sent in sentences:
        if current_len + len(sent) + 1 > MAX_CHUNK_CHARS and current:
            sub_text = " ".join(current)
            sub_heading = f"{heading} (part {sub_idx + 1})" if sub_idx > 0 else heading
            chunks.append((sub_heading, sub_text))
            sub_idx += 1
            # Overlap: keep last 1-2 sentences
            overlap = [current[-1]] if len(current) > 1 else []
            current = overlap + [sent]
            current_len = sum(len(s) + 1 for s in current)
        else:
            current.append(sent)
            current_len += len(sent) + 1

    if current:
        sub_text = " ".join(current)
        sub_heading = f"{heading} (part {sub_idx + 1})" if sub_idx > 0 else heading
        chunks.append((sub_heading, sub_text))


def _detect_entities(text: str, entities: list[dict]) -> list[dict]:
    """Case-insensitive match de entity names en text."""
    text_lower = text.lower()
    refs: list[dict] = []
    seen: set[str] = set()
    for e in entities:
        name = (e.get("name") or "").strip()
        if not name or name.lower() in seen:
            continue
        if name.lower() in text_lower:
            refs.append({"id": e["id"], "name": name})
            seen.add(name.lower())
    return refs


async def chunk_and_index(
    page_slug: str,
    content: str,
    scope: str,
    title: str,
    embed_text_fn,
) -> int:
    """Auto-chunk + embed + INSERT en mm_entity_chunks."""
    db.write_one(
        "DELETE FROM mm_entity_chunks WHERE page_slug = %s",
        (page_slug,),
    )

    heading_text_pairs = _split_by_headings(content)
    if not heading_text_pairs:
        log.info("no_chunks_yielded", extra={"page_slug": page_slug})
        return 0

    entity_rows = db.read_many("SELECT id, name FROM mm_entities")
    entities = [{"id": r["id"], "name": r["name"]} for r in entity_rows]

    indexed = 0
    for i, (heading, text) in enumerate(heading_text_pairs):
        refs = _detect_entities(text, entities)
        word_count = len(text.split())
        try:
            emb = await embed_text_fn(text)
        except Exception as e:
            log.error("embed_call_failed", extra={"page_slug": page_slug, "error": str(e)})
            emb = None

        emb_blob: Optional[bytes] = None
        if emb is not None:
            try:
                emb_blob = emb.astype(np.float32).tobytes()
            except Exception as e:
                log.warning("blob_conversion_failed", extra={"error": str(e)})
                emb_blob = None

        db.write_one(
            """
            INSERT INTO mm_entity_chunks (
                page_slug, chunk_index, heading, chunk_text,
                entities_referenced, word_count, embedding, scope
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                page_slug,
                i,
                heading[:200] if heading else None,
                text,
                json.dumps(refs, ensure_ascii=False),
                word_count,
                emb_blob,
                scope,
            ),
        )
        indexed += 1

    log.info(
        "chunk_and_index_done",
        extra={"page_slug": page_slug, "chunks": indexed, "scope": scope},
    )
    return indexed


def reset_page(page_slug: str) -> int:
    return db.write_one(
        "DELETE FROM mm_entity_chunks WHERE page_slug = %s",
        (page_slug,),
    )