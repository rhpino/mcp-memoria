#!/usr/bin/env python3
"""migrate-kb-to-wiki.py — Backfill único desde kb/ legacy a mm_wiki_pages.

Uso:
    python scripts/migrate-kb-to-wiki.py --dry-run   # default, no escribe
    python scripts/migrate-kb-to-wiki.py --apply      # INSERT en DB

Idempotente: si (slug, 1) ya existe, skip.

Configuración (env vars, lee /etc/mcp-memoria/db.env si existe):
    WORKSPACE_ROOT     path al kb/ (default: paths.WORKSPACE default)
    MCP_DB_NAME        nombre DB (default: 'mcp_memoria')
    MCP_DB_USER/PASS/HOST/PORT  MariaDB connection
"""
from __future__ import annotations

import argparse
import json as _json
import logging
import os
import sys
from pathlib import Path

# Permitir import de memoria_mcp desde /opt/mcps/memoria/src
sys.path.insert(0, "/opt/mcps/memoria/src")

from memoria_mcp import db  # noqa: E402
from memoria_mcp.wiki_io import parse_frontmatter  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("migrate-kb")

VALID_SCOPES = ("concepts", "designs", "lessons", "papers", "reports")


def _workspace_root() -> Path:
    env = os.environ.get("WORKSPACE_ROOT")
    if env:
        return Path(env)
    # Default de paths.WORKSPACE
    from memoria_mcp import paths as paths_mod
    return paths_mod.WORKSPACE


def _scan_files(workspace: Path) -> tuple[list[Path], list[Path]]:
    """Devuelve (files_en_scopes, files_en_root). Excluye subdirs no-scope."""
    in_scope: list[Path] = []
    in_root: list[Path] = []
    for scope in VALID_SCOPES:
        scope_dir = workspace / scope
        if not scope_dir.is_dir():
            continue
        for p in sorted(scope_dir.glob("*.md")):
            if p.is_file():
                in_scope.append(p)
    for p in sorted(workspace.glob("*.md")):
        if p.is_file():
            in_root.append(p)
    return in_scope, in_root


def _insert_page(slug: str, scope: str, body: str, frontmatter: dict) -> bool:
    """INSERT (slug, version=1) si no existe. Devuelve True si insertó."""
    existing = db.read_one(
        "SELECT version FROM mm_wiki_pages WHERE slug = %s AND version = 1",
        (slug,),
    )
    if existing:
        return False
    db.write_one(
        "INSERT INTO mm_wiki_pages (slug, version, body, frontmatter, author, scope) "
        "VALUES (%s, 1, %s, %s, %s, %s)",
        (
            slug,
            body,
            _json.dumps(frontmatter, ensure_ascii=False) if frontmatter else None,
            "legacy-migration",
            scope,
        ),
    )
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--dry-run", action="store_true", default=True,
                       help="Solo reportar, no escribir (default).")
    group.add_argument("--apply", action="store_true",
                       help="Escribir INSERTs en mm_wiki_pages.")
    args = parser.parse_args()
    apply = args.apply

    workspace = _workspace_root()
    log.info("workspace_root=%s apply=%s", workspace, apply)

    in_scope, in_root = _scan_files(workspace)
    log.info("found in_scope=%d root=%d (skipped)", len(in_scope), len(in_root))

    counts = {
        "migrated": 0, "skipped": 0, "lowercased": 0,
        "failed": 0, "root": len(in_root),
    }

    for path in in_scope:
        scope = path.parent.name
        if scope not in VALID_SCOPES:
            counts["failed"] += 1
            continue
        # Preservamos casing original (el chunker existente usa filename tal cual
        # como page_slug; cambiar casing rompería referencias en mm_entity_chunks).
        slug = path.stem

        try:
            text = path.read_text(encoding="utf-8")
            frontmatter, body = parse_frontmatter(text)
        except Exception as e:
            log.error("read_failed slug=%s err=%s", slug, e)
            counts["failed"] += 1
            continue

        if apply:
            try:
                inserted = _insert_page(slug, scope, body, frontmatter)
                if inserted:
                    counts["migrated"] += 1
                else:
                    counts["skipped"] += 1
            except Exception as e:
                log.error("insert_failed slug=%s err=%s", slug, e)
                counts["failed"] += 1
        else:
            counts["migrated"] += 1
            log.info("[DRY-RUN] would insert slug=%s scope=%s", slug, scope)

    prefix = "[DRY-RUN] " if not apply else ""
    summary = (
        f"{prefix}summary: migrated={counts['migrated']} skipped={counts['skipped']} "
        f"lowercased={counts['lowercased']} failed={counts['failed']} "
        f"root={counts['root']}"
    )
    if apply:
        log.info(summary)
    else:
        log.info(summary)
    print(summary)

    return 0 if counts["failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
