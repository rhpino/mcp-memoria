"""test_wiki_io.py — tests de parse/render frontmatter."""
from __future__ import annotations

from memoria_mcp.wiki_io import parse_frontmatter, render_with_frontmatter


def test_parse_frontmatter_with_yaml():
    text = (
        "---\ntitle: Mi Diseño\ntags: [a, b]\nversion: 3\n---\n"
        "# Heading\n\nBody."
    )
    fm, body = parse_frontmatter(text)
    assert fm["title"] == "Mi Diseño"
    assert fm["tags"] == ["a", "b"]
    assert fm["version"] == 3
    assert body.strip() == "# Heading\n\nBody."


def test_parse_frontmatter_no_yaml():
    fm, body = parse_frontmatter("# Solo markdown")
    assert fm == {}
    assert body == "# Solo markdown"


def test_parse_frontmatter_empty():
    fm, body = parse_frontmatter("")
    assert fm == {}
    assert body == ""


def test_parse_frontmatter_malformed_yaml_returns_empty_fm():
    """Si el YAML está malformado, devolvemos frontmatter={} y el texto entero como body."""
    text = "---\ntitle: [unclosed\n---\n# Body"
    fm, body = parse_frontmatter(text)
    assert fm == {}
    assert "title:" in body  # texto crudo


def test_render_with_frontmatter():
    out = render_with_frontmatter({"title": "X", "version": 1}, "# X\n\nFoo.")
    assert out.startswith("---\n")
    assert "title: X" in out
    assert "version: 1" in out
    assert out.endswith("# X\n\nFoo.")


def test_render_with_empty_frontmatter_returns_body():
    out = render_with_frontmatter({}, "# X")
    assert out == "# X"


def test_render_roundtrip():
    fm_in = {"title": "Y", "tags": ["c"]}
    body_in = "Body content"
    out = render_with_frontmatter(fm_in, body_in)
    fm_out, body_out = parse_frontmatter(out)
    assert fm_out == fm_in
    assert body_out == body_in