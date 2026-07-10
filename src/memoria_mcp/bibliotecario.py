"""bibliotecario.py — Curador con LLM merge de conflictos.

Port conceptual de omni-mcp/bibliotecario.cjs (Node.js, merge con MiniMax M3 / Gemini):
- Detecta conflictos en `mm_conflict_queue` (entity_type, entity_id, gcp_content vs node_content).
- Para cada conflicto, llama un LLM (MiniMax M3 default, Gemini fallback) para merge semántico.
- Persiste el merge en `mm_conflict_queue.resolved_content`.
- Marca con `resolution='merged'` y `resolved_by='bibliotecario'`.

**Degraded mode:** si no hay LLM key activo, marca conflictos como `skipped` con reason.

Réplica conceptual — no copy-paste de Node.
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Optional

from . import db

log = logging.getLogger("memoria_bibliotecario")

# LLM config (env-based; si no hay, degraded mode)
MINIMAX_ENABLED = os.environ.get("MINIMAX_ENABLED", "false").lower() == "true"
MINIMAX_API = os.environ.get("MINIMAX_API", "https://api.minimax.com/v1/text/chatcompletion_v2")
MINIMAX_KEY = os.environ.get("MINIMAX_KEY", "")
MINIMAX_MODEL = os.environ.get("MINIMAX_MODEL", "minimax-m3")

GEMINI_API = os.environ.get("GEMINI_API", "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.1-pro-preview:generateContent")
GEMINI_KEY = os.environ.get("GEMINI_KEY", "")


def _is_llm_available() -> bool:
    """True si hay al menos un LLM key configurado."""
    return (MINIMAX_ENABLED and bool(MINIMAX_KEY)) or bool(GEMINI_KEY)


def _build_merge_prompt(entity_id: str, content_a: str, content_b: str) -> str:
    return (
        f"Eres un bibliotecario que consolida información sobre el mismo tema '{entity_id}'. "
        "Ambas describen información relacionada pero desde fuentes diferentes. "
        "Tu tarea: combinarlas en un solo texto coherente, conservando TODA la información de ambas. "
        "No pierdas detalles. No resumas — fusiona.\n\n"
        f"## Fuente A:\n{content_a}\n\n"
        f"## Fuente B:\n{content_b}\n\n"
        "## Resultado consolidado (texto completo fusionado):"
    )


async def _call_minimax(prompt: str) -> Optional[str]:
    """Llama MiniMax M3. Returns merged content o None si falla."""
    if not (MINIMAX_ENABLED and MINIMAX_KEY):
        return None
    try:
        def _request() -> Optional[str]:
            import urllib.request, json
            req = urllib.request.Request(
                MINIMAX_API,
                data=json.dumps({
                    "model": MINIMAX_MODEL,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 8192,
                    "temperature": 0.3,
                }).encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {MINIMAX_KEY}",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return data.get("choices", [{}])[0].get("message", {}).get("content")

        return await asyncio.to_thread(_request)
    except Exception as e:
        log.warning("minimax_call_failed", extra={"error": str(e)})
        return None


async def _call_gemini(prompt: str) -> Optional[str]:
    """Llama Gemini (fallback)."""
    if not GEMINI_KEY:
        return None
    try:
        def _request() -> Optional[str]:
            import urllib.request, json, urllib.parse
            url = f"{GEMINI_API}?key={urllib.parse.quote(GEMINI_KEY)}"
            req = urllib.request.Request(
                url,
                data=json.dumps({
                    "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                    "generationConfig": {"maxOutputTokens": 8192, "temperature": 0.3},
                }).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return (
                    data.get("candidates", [{}])[0]
                    .get("content", {})
                    .get("parts", [{}])[0]
                    .get("text")
                )

        return await asyncio.to_thread(_request)
    except Exception as e:
        log.warning("gemini_call_failed", extra={"error": str(e)})
        return None


async def _merge_content(entity_id: str, content_a: str, content_b: str) -> Optional[str]:
    """Merge semántico con MiniMax → Gemini fallback."""
    prompt = _build_merge_prompt(entity_id, content_a, content_b)
    merged = await _call_minimax(prompt)
    if merged:
        return merged
    return await _call_gemini(prompt)


async def enqueue_conflict(
    entity_type: str,
    entity_id: str,
    gcp_content: str,
    node_content: str,
) -> int:
    """Añade un conflicto a mm_conflict_queue."""
    return db.write_one(
        "INSERT INTO mm_conflict_queue (entity_type, entity_id, gcp_content, node_content) "
        "VALUES (%s, %s, %s, %s)",
        (entity_type, entity_id, gcp_content, node_content),
    )


async def run(max_conflicts: int = 1) -> dict:
    """Trigger curador: procesa hasta N conflictos pending.

    Returns: {processed, merged, skipped, llm_available}
    """
    if not _is_llm_available():
        log.warning("bibliotecario_no_llm_available")
        # Marca todos los pending como skipped
        n_skipped = db.write_one(
            "UPDATE mm_conflict_queue SET resolution='skipped', "
            "resolved_by='bibliotecario', "
            "notes='No LLM key available' "
            "WHERE resolution='pending'"
        )
        return {
            "processed": 0,
            "merged": 0,
            "skipped": n_skipped or 0,
            "llm_available": False,
        }

    # Cargar hasta max_conflicts pending
    rows = db.read_many(
        "SELECT id, entity_type, entity_id, gcp_content, node_content "
        "FROM mm_conflict_queue WHERE resolution='pending' "
        "ORDER BY ts ASC LIMIT %s",
        (max_conflicts,),
    )

    merged_count = 0
    skipped_count = 0
    for r in rows:
        if not (r["gcp_content"] and r["node_content"]):
            # Vacío en un lado: skip
            db.write_one(
                "UPDATE mm_conflict_queue SET resolution='skipped', "
                "resolved_by='bibliotecario', "
                "notes='Contenido vacío en un lado', resolved_at=NOW() "
                "WHERE id=%s",
                (r["id"],),
            )
            skipped_count += 1
            continue

        merged = await _merge_content(r["entity_id"], r["gcp_content"], r["node_content"])
        if merged:
            db.write_one(
                "UPDATE mm_conflict_queue SET resolution='merged', "
                "resolved_content=%s, resolved_by='bibliotecario', "
                "notes='LLM merge OK', resolved_at=NOW() "
                "WHERE id=%s",
                (merged, r["id"]),
            )
            merged_count += 1
        else:
            db.write_one(
                "UPDATE mm_conflict_queue SET resolution='skipped', "
                "resolved_by='bibliotecario', "
                "notes='LLM merge failed', resolved_at=NOW() "
                "WHERE id=%s",
                (r["id"],),
            )
            skipped_count += 1

    return {
        "processed": len(rows),
        "merged": merged_count,
        "skipped": skipped_count,
        "llm_available": True,
    }


async def list_conflicts(state: Optional[str] = None) -> list[dict]:
    """Lista conflictos en mm_conflict_queue."""
    if state:
        return db.read_many(
            "SELECT id, entity_type, entity_id, resolution, resolved_by, "
            "SUBSTRING(notes, 1, 100) AS notes, ts, resolved_at "
            "FROM mm_conflict_queue WHERE resolution = %s ORDER BY ts DESC",
            (state,),
        )
    return db.read_many(
        "SELECT id, entity_type, entity_id, resolution, resolved_by, "
        "SUBSTRING(notes, 1, 100) AS notes, ts, resolved_at "
        "FROM mm_conflict_queue ORDER BY ts DESC LIMIT 100"
    )


async def resolve_conflict(conflict_id: int, action: str, notes: str = "") -> dict:
    """Resolución manual de un conflicto."""
    if action not in ("merged", "kept", "skipped"):
        raise ValueError(f"action must be merged|kept|skipped, got: {action}")
    db.write_one(
        "UPDATE mm_conflict_queue SET resolution=%s, "
        "resolved_by='manual', notes=%s, resolved_at=NOW() "
        "WHERE id=%s",
        (action, notes, conflict_id),
    )
    return {"id": conflict_id, "action": action, "resolved_by": "manual"}


def llm_available() -> bool:
    """Para checks externos."""
    return _is_llm_available()
