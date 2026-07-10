"""paths.py — Allowlist de paths (privacidad física).

CRÍTICO: este módulo es la ÚNICA barrera contra lectura de archivos
personales. Defense in depth: allowlist + denylist explícita + symlink check.

v2: estructura kb/ de vps-geo-noc — incluye designs/, papers/, lessons/, concepts/, reports/.
"""
from __future__ import annotations

import fnmatch
import logging
import os
from pathlib import Path
from typing import Iterable

log = logging.getLogger("memoria_paths")

WORKSPACE = Path(
    os.environ.get("WORKSPACE_ROOT", "/home/cloudops/.openclaw/workspace")
)

# Allowlist de directorios (SÍ se leen)
# Estructura real de kb/ vps-geo-noc (2026-07-02 audit):
# /home/cloudops/.openclaw/workspace/{concepts,designs,lessons,papers,reports}/
ALLOWED_DIRS: list[Path] = [
    WORKSPACE / "concepts",
    WORKSPACE / "designs",
    WORKSPACE / "lessons",
    WORKSPACE / "papers",
    WORKSPACE / "reports",
]

# Allowlist de archivos individuales (no en subdirs)
ALLOWED_FILES_GLOB: list[tuple[Path, str]] = [
    (WORKSPACE, "DESIGNS.md"),
    (WORKSPACE, "INDEX.md"),
    # Compat: si existe clientes/ con decisions.md
    (WORKSPACE / "clientes", "*/decisions.md"),
]

# Denylist: defense in depth
DENYLIST_PATTERNS: list[str] = [
    "MEMORY.md",
    "USER.md",
    "SOUL.md",
    "IDENTITY.md",
    "AGENTS.md",
    "/briefing/",
    "/memory/",
    "/contactos",
    "/sessions/",
]


def _resolved(path: Path) -> Path | None:
    try:
        return path.resolve(strict=True)
    except (OSError, RuntimeError):
        return None


def _in_allowed_dir(real: Path) -> bool:
    for allowed in ALLOWED_DIRS:
        try:
            allowed_real = allowed.resolve(strict=False)
        except (OSError, RuntimeError):
            continue
        try:
            real.relative_to(allowed_real)
            return True
        except ValueError:
            continue
    return False


def _in_allowed_glob(real: Path) -> bool:
    for base, pattern in ALLOWED_FILES_GLOB:
        try:
            base_real = base.resolve(strict=False)
        except (OSError, RuntimeError):
            continue
        try:
            rel = real.relative_to(base_real)
        except ValueError:
            continue
        if fnmatch.fnmatch(str(rel), pattern):
            return True
    return False


def _matches_denylist(real: Path) -> bool:
    s = str(real)
    for pattern in DENYLIST_PATTERNS:
        if pattern in s:
            return True
    return False


def is_path_allowed(path: str | Path) -> bool:
    p = Path(path)
    real = _resolved(p)
    if real is None:
        return False
    if not (_in_allowed_dir(real) or _in_allowed_glob(real)):
        return False
    if _matches_denylist(real):
        log.warning("denylist_match_blocked",
                    extra={"path": str(real), "reason": "denylist_pattern"})
        return False
    return True


def safe_read(path: str | Path) -> str:
    """Read a file, with allowlist check applied to the resolved path.

    H9 audit 2026-07-02: TOCTOU. Resolver y validar el path REAL
    (post-symlink-resolution) ANTES de leer. Antes: is_path_allowed(path)
    sobre la ruta original, luego read_text() que re-resolvía symlinks.
    Ahora: resolvemos primero, validamos, leemos sobre la ruta ya validada.
    """
    real = _resolved(Path(path))
    if real is None or not is_path_allowed(real):
        raise PermissionError(f"Path not allowed: {path}")
    return real.read_text(encoding="utf-8")


def list_allowed_files(scope: str | None = None) -> list[Path]:
    out: list[Path] = []
    scope_dirs = {d.parts[-1]: [d] for d in ALLOWED_DIRS}

    if scope is None or scope == "all":
        dirs: Iterable[Path] = ALLOWED_DIRS
    elif scope in scope_dirs:
        dirs = scope_dirs[scope]
    else:
        return []

    for d in dirs:
        if not d.exists():
            continue
        for f in sorted(d.rglob("*")):
            if f.is_file() and is_path_allowed(f):
                out.append(f)

    # Root-level allowed files
    if scope is None or scope == "all":
        for base, pattern in ALLOWED_FILES_GLOB:
            for f in sorted(base.glob(pattern)):
                if is_path_allowed(f):
                    out.append(f)

    return out


def validate_allowlist() -> dict[str, bool]:
    result: dict[str, bool] = {}
    for d in ALLOWED_DIRS:
        result[str(d)] = d.exists()
    for base, _ in ALLOWED_FILES_GLOB:
        result[str(base)] = base.exists()
    missing = [k for k, v in result.items() if not v]
    if missing:
        log.warning("allowlist_missing_paths", extra={"missing": missing})
    else:
        log.info("allowlist_ok", extra={"n": len(result)})
    return result


# ── Wiki archive (MOP-398) ────────────────────────────────────────
# Filesystem como backup artefact, NO live. El chunker NO debe re-ingerir
# estos archivos (no están en ALLOWED_DIRS arriba).

import re as _re

_VALID_SCOPE_NAMES = {"concepts", "designs", "lessons", "papers", "reports"}
# Slug acepta lowercase + UPPERCASE + dígitos + '-' + '_'.
# Razón: el kb/ legacy tiene archivos en UPPERCASE (CHG-*, MOP-*, RCA-*,
# INDEPENDENCIA, INVESTIGACION-*, etc.) que el chunker indexa con el filename
# original como page_slug. Migración preserva casing para no romper
# referencias en mm_entity_chunks.
_SLUG_RE = _re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,198}$")

ARCHIVE_ROOT = WORKSPACE / "wiki_archive"


def _validate_slug_scope(slug: str, scope: str) -> None:
    """Valida formato de slug y pertenencia del scope. Raises ValueError."""
    if not _SLUG_RE.match(slug or ""):
        raise ValueError(
            f"slug inválido: {slug!r}. Debe coincidir ^[a-zA-Z0-9][a-zA-Z0-9_-]{{0,198}}$"
        )
    if scope not in _VALID_SCOPE_NAMES:
        raise ValueError(
            f"scope inválido: {scope!r}. Debe ser uno de {sorted(_VALID_SCOPE_NAMES)}"
        )


def wiki_archive_path(slug: str, scope: str, version: int) -> Path:
    """Path inmutable por versión: <WORKSPACE>/wiki_archive/<scope>/<slug>-v<N>.md.

    Filename único por versión → cualquier v<N> se escribe UNA vez, sin race.
    El chunker NO debe leer este dir (no está en ALLOWED_DIRS).
    """
    _validate_slug_scope(slug, scope)
    if not isinstance(version, int) or version < 1:
        raise ValueError(f"version inválida: {version!r}. Debe ser int >= 1")
    return ARCHIVE_ROOT / scope / f"{slug}-v{version}.md"


def wiki_archive_dir(scope: str) -> Path:
    """<WORKSPACE>/wiki_archive/<scope>/. Usado para mkdir pre-write."""
    if scope not in _VALID_SCOPE_NAMES:
        raise ValueError(f"scope inválido: {scope!r}")
    return ARCHIVE_ROOT / scope
