"""index_real.py — Indexa el kb/ real de vps-geo-noc.

Scope detection:
- WORKSPACE/{concepts,designs,lessons,papers,reports}/X.md → scope = dirname
- WORKSPACE/DESIGNS.md o INDEX.md → scope = "root"
"""
import asyncio
import os
import sys
import time
from pathlib import Path

# H11 audit 2026-07-02: read DB credentials from /etc/mcp-memoria/db.env
# instead of hardcoding them in source.
_ENV_FILE = "/etc/mcp-memoria/db.env"
if os.path.exists(_ENV_FILE):
    for _line in open(_ENV_FILE).read().splitlines():
        _line = _line.strip()
        if "=" in _line and not _line.startswith("#"):
            _k, _, _v = _line.partition("=")
            os.environ.setdefault(_k.strip(), _v.strip())
os.environ.setdefault("MCP_DB_USER", "mcp_memoria")
os.environ.setdefault("WORKSPACE_ROOT", "/tmp/kb_real")

sys.path.insert(0, "/opt/mcps/memoria/src")

from memoria_mcp import db, chunker, embed as embed_mod, paths as paths_mod


async def main():
    print("=== mcp-memoria: index REAL kb/ ===")
    db.init_schema()

    # MOP-398 fix: usar WORKSPACE_ROOT del env (default = paths.WORKSPACE default).
    workspace_env = os.environ.get("WORKSPACE_ROOT")
    workspace = Path(workspace_env) if workspace_env else paths_mod.WORKSPACE
    docs = paths_mod.list_allowed_files()
    print(f"Found {len(docs)} files in {workspace}\n")

    by_scope: dict[str, list[Path]] = {}
    for f in docs:
        try:
            rel = f.relative_to(workspace)
        except ValueError:
            continue
        if rel.parts[0] in ("concepts", "designs", "lessons", "papers", "reports"):
            scope = rel.parts[0]
        else:
            scope = rel.stem.lower()  # DESIGNS.md → "designs", INDEX.md → "index"
        by_scope.setdefault(scope, []).append(f)

    total_chunks = 0
    total_bytes = 0
    for scope, files in sorted(by_scope.items()):
        print(f"--- scope: {scope} ({len(files)} files) ---")
        for f in files:
            try:
                content = f.read_text(encoding="utf-8")
            except Exception as e:
                print(f"  {f.relative_to(workspace)}: SKIP ({e})")
                continue
            rel = f.relative_to(workspace).with_suffix("")
            # MOP-398 fix: usar path.stem para consistencia con migration script.
            # Antes: str(rel).replace("/", "-") → "lessons-INDEPENDENCIA" (mismatch).
            # Ahora: path.stem → "INDEPENDENCIA" (matches mm_wiki_pages.slug).
            slug = f.stem
            total_bytes += len(content)

            t0 = time.time()
            try:
                n = await chunker.chunk_and_index(
                    page_slug=slug,
                    content=content,
                    scope=scope,
                    title=slug,
                    embed_text_fn=embed_mod.embed_text,
                )
                elapsed = (time.time() - t0) * 1000
                print(f"  {slug}: {n} chunks ({elapsed:.0f}ms, {len(content)} chars)")
                total_chunks += n
            except Exception as e:
                print(f"  {slug}: ERROR ({e})")

    print(f"\n=== TOTAL ===")
    print(f"  Files: {len(docs)}")
    print(f"  Chunks: {total_chunks}")
    print(f"  Content: {total_bytes:,} bytes")


if __name__ == "__main__":
    asyncio.run(main())