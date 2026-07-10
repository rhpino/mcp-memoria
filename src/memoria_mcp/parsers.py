"""parsers.py — Parsers de archivos markdown con frontmatter."""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import frontmatter

log = logging.getLogger("memoria_parsers")


@dataclass
class ParsedDoc:
    file_path: Path
    scope: str
    slug: str
    frontmatter: dict = field(default_factory=dict)
    body: str = ""
    title: str = ""
    tags: list[str] = field(default_factory=list)
    date: Optional[str] = None
    parse_warnings: list[str] = field(default_factory=list)


RE_KB_SLUG = re.compile(r"^([a-z0-9][a-z0-9\-]*[a-z0-9])\.md$", re.IGNORECASE)
RE_ADR_NUMBER = re.compile(r"^(\d{4})-(.+)\.md$")


def _detect_scope(file_path: Path, workspace: Path) -> str:
    try:
        rel = file_path.relative_to(workspace)
    except ValueError:
        return "unknown"
    parts = rel.parts
    if len(parts) >= 3 and parts[0] == "kb":
        scope = parts[1]
        if scope in ("decisions", "lessons", "jobs", "concepts", "wiki"):
            return scope
    if len(parts) >= 2 and parts[0] == "04-decisions":
        return "adrs"
    if len(parts) >= 3 and parts[0] == "clientes" and file_path.name == "decisions.md":
        return "clientes"
    return "unknown"


def _slug_from_filename(file_path: Path, scope: str) -> str:
    stem = file_path.stem
    if scope == "adrs":
        m = RE_ADR_NUMBER.match(stem)
        if m:
            return f"adr:{m.group(1)}"
        return f"adr:{stem}"
    if scope == "clientes":
        parent = file_path.parent.name
        return f"cliente:{parent}"
    m = RE_KB_SLUG.match(stem)
    if m:
        return f"{scope}:{m.group(1)}"
    return f"{scope}:{stem}"


def parse_doc(file_path: Path, workspace: Path) -> ParsedDoc:
    scope = _detect_scope(file_path, workspace)
    slug = _slug_from_filename(file_path, scope)
    try:
        text = file_path.read_text(encoding="utf-8")
    except OSError as e:
        log.error("read_failed", extra={"file": str(file_path), "error": str(e)})
        raise

    warnings: list[str] = []
    try:
        post = frontmatter.loads(text)
        fm = dict(post.metadata)
        body = post.content
    except Exception as e:
        warnings.append(f"frontmatter_parse_failed: {e}")
        fm = {}
        body = text

    title = fm.get("title", "")
    if not title:
        m = re.search(r"^#\s+(.+?)$", body, re.MULTILINE)
        if m:
            title = m.group(1).strip()
        else:
            title = file_path.stem.replace("-", " ").title()
            warnings.append("title_inferred_from_filename")

    tags_raw = fm.get("tags", [])
    if isinstance(tags_raw, str):
        tags = [t.strip() for t in tags_raw.split(",") if t.strip()]
    elif isinstance(tags_raw, list):
        tags = [str(t).strip() for t in tags_raw if str(t).strip()]
    else:
        tags = []

    date_raw = fm.get("date")
    date: Optional[str] = None
    if date_raw is not None:
        try:
            date = str(date_raw)
        except Exception:
            date = None

    if warnings:
        for w in warnings:
            log.warning("parse_warning",
                        extra={"file": str(file_path), "warning": w})

    return ParsedDoc(
        file_path=file_path,
        scope=scope,
        slug=slug,
        frontmatter=fm,
        body=body,
        title=title,
        tags=tags,
        date=date,
        parse_warnings=warnings,
    )


def discover(workspace: Path, scope: str | None = None) -> list[ParsedDoc]:
    out: list[ParsedDoc] = []
    if scope is None or scope == "all":
        scopes_to_scan = [
            "decisions", "lessons", "jobs", "concepts", "wiki", "adrs", "clientes",
        ]
    else:
        scopes_to_scan = [scope]

    if "decisions" in scopes_to_scan:
        d = workspace / "kb" / "decisions"
        if d.exists():
            for f in sorted(d.glob("*.md")):
                out.append(parse_doc(f, workspace))
    if "lessons" in scopes_to_scan:
        d = workspace / "kb" / "lessons"
        if d.exists():
            for f in sorted(d.glob("*.md")):
                out.append(parse_doc(f, workspace))
    if "jobs" in scopes_to_scan:
        d = workspace / "kb" / "jobs"
        if d.exists():
            for f in sorted(d.glob("*.md")):
                out.append(parse_doc(f, workspace))
    if "concepts" in scopes_to_scan:
        d = workspace / "kb" / "concepts"
        if d.exists():
            for f in sorted(d.glob("*.md")):
                out.append(parse_doc(f, workspace))
    if "wiki" in scopes_to_scan:
        d = workspace / "kb" / "wiki"
        if d.exists():
            for f in sorted(d.glob("*.md")):
                out.append(parse_doc(f, workspace))
    if "adrs" in scopes_to_scan:
        d = workspace / "04-decisions"
        if d.exists():
            for f in sorted(d.glob("*.md")):
                out.append(parse_doc(f, workspace))
    if "clientes" in scopes_to_scan:
        d = workspace / "clientes"
        if d.exists():
            for f in sorted(d.glob("*/decisions.md")):
                out.append(parse_doc(f, workspace))

    log.info("discover_done", extra={"n": len(out), "scope": scope or "all"})
    return out