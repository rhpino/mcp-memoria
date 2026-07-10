"""tools/bibliotecario.py — bibliotecario_run, conflict_list, conflict_resolve."""
from __future__ import annotations

from typing import Optional

from .. import bibliotecario as bib_mod


async def bibliotecario_run(max_conflicts: int = 1) -> dict:
    """Trigger curador: procesa hasta N conflictos pending."""
    return await bib_mod.run(max_conflicts=max_conflicts)


async def conflict_list(state: Optional[str] = None) -> list[dict]:
    """Lista conflictos en mm_conflict_queue."""
    return await bib_mod.list_conflicts(state=state)


async def conflict_resolve(conflict_id: int, action: str, notes: str = "") -> dict:
    """Resolución manual de un conflicto."""
    return await bib_mod.resolve_conflict(
        conflict_id=conflict_id, action=action, notes=notes,
    )


async def bibliotecario_status() -> dict:
    """Estado del bibliotecario: llm available, pending conflicts count."""
    return {
        "llm_available": bib_mod.llm_available(),
        "pending_count": len(await bib_mod.list_conflicts(state="pending")),
    }