"""wiki_io.py — parse y render de frontmatter YAML.

Patrón (réplica conceptual de omni-mcp wiki subsystem):
- Frontmatter entre dos líneas `---` al inicio del archivo.
- YAML real (no JSON) para flexibilidad humana.
- Si el YAML está malformado, devolvemos ({}, texto crudo) en vez de raise.
"""
from __future__ import annotations

import logging
import re

import yaml

log = logging.getLogger("memoria_wiki_io")

_FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?\n)---\s*\n?(.*)\Z", re.DOTALL)


def parse_frontmatter(text: str) -> tuple[dict, str]:
    """Separa frontmatter YAML del body markdown.

    Returns:
        (frontmatter_dict, body_str). Si no hay frontmatter o está malformado,
        devuelve ({}, text). Si el YAML parsea pero no es dict, devuelve ({}, text).
    """
    if not text:
        return {}, ""
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return {}, text
    try:
        fm = yaml.safe_load(m.group(1)) or {}
        if not isinstance(fm, dict):
            log.warning("frontmatter_not_dict", extra={"type": type(fm).__name__})
            return {}, text
    except yaml.YAMLError as e:
        log.warning("frontmatter_yaml_error", extra={"error": str(e)})
        return {}, text
    return fm, m.group(2)


def render_with_frontmatter(fm: dict, body: str) -> str:
    """Junta frontmatter + body en formato markdown válido.

    Si fm es vacío, devuelve solo el body.
    """
    if not fm:
        return body
    yaml_str = yaml.safe_dump(
        fm, allow_unicode=True, sort_keys=False, default_flow_style=False,
    ).rstrip()
    return f"---\n{yaml_str}\n---\n{body}"