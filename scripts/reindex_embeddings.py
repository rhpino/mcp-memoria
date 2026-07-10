from __future__ import annotations

import argparse
import asyncio

from memoria_mcp import config

config.load_dotenv()

from memoria_mcp import db, embed, embed_admin
from memoria_mcp.chunker import chunk_and_index


async def reindex_all(dry_run: bool = True) -> dict:
    init = db.init_schema()
    if init.get("status") != "ok":
        raise RuntimeError(f"schema init failed: {init}")

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
