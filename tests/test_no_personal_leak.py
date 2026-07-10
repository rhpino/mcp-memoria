"""test_no_personal_leak.py — CRÍTICO. Privacy gate.

v2: actualizado a la estructura real del kb/ de vps-geo-noc.
- ALLOWED_DIRS: {concepts, designs, lessons, papers, reports} (no kb/decisions/).
- Root files: DESIGNS.md, INDEX.md, IMPLEMENTED.md.
- Retrocompatibilidad: 04-decisions/, clientes/ siguen en ALLOWED_FILES_GLOB.

Si falla → NO deploy.
"""
from __future__ import annotations

import importlib
import os
import tempfile
from pathlib import Path

import pytest

from memoria_mcp.paths import is_path_allowed, safe_read, WORKSPACE


def _reload_paths(monkeypatch, workspace: Path) -> None:
    monkeypatch.setenv("WORKSPACE_ROOT", str(workspace))
    importlib.reload(__import__("memoria_mcp.paths", fromlist=["paths"]))


@pytest.fixture
def fake_workspace(monkeypatch, tmp_path: Path) -> Path:
    """Workspace fake con archivos personales que NO deben pasar el allowlist.

    Estructura matches /opt/mcp-memoria/snapshot/kb/ (vps-geo-noc kb/):
    - subdirs: concepts/, designs/, lessons/, papers/, reports/
    - root files: DESIGNS.md, INDEX.md (compat)
    - personal files: MEMORY.md, USER.md, SOUL.md, IDENTITY.md, AGENTS.md
    - personal dirs: briefing/, memory/sessions/, clientes/buincity/contactos/
    - legacy compat: 04-decisions/, clientes/
    """
    # Allowed dirs (v2: kb/ real de vps-geo-noc)
    (tmp_path / "concepts").mkdir(parents=True)
    (tmp_path / "designs").mkdir(parents=True)
    (tmp_path / "lessons").mkdir(parents=True)
    (tmp_path / "papers").mkdir(parents=True)
    (tmp_path / "reports").mkdir(parents=True)

    # Legacy allowed dirs (compat con seed)
    (tmp_path / "kb" / "decisions").mkdir(parents=True)
    (tmp_path / "kb" / "lessons").mkdir(parents=True)
    (tmp_path / "kb" / "jobs").mkdir(parents=True)
    (tmp_path / "kb" / "concepts").mkdir(parents=True)
    (tmp_path / "kb" / "wiki").mkdir(parents=True)
    (tmp_path / "04-decisions").mkdir(parents=True)
    (tmp_path / "clientes" / "buincity").mkdir(parents=True)

    # Personal files (must NOT pass allowlist even if they exist)
    (tmp_path / "MEMORY.md").write_text("private memory", encoding="utf-8")
    (tmp_path / "USER.md").write_text("private user", encoding="utf-8")
    (tmp_path / "SOUL.md").write_text("private soul", encoding="utf-8")
    (tmp_path / "IDENTITY.md").write_text("private identity", encoding="utf-8")
    (tmp_path / "AGENTS.md").write_text("private agents", encoding="utf-8")
    (tmp_path / "briefing").mkdir()
    (tmp_path / "briefing" / "AGENTS.md").write_text("briefing content", encoding="utf-8")
    (tmp_path / "memory" / "sessions").mkdir(parents=True)
    (tmp_path / "memory" / "sessions" / "abc.md").write_text("session", encoding="utf-8")
    (tmp_path / "clientes" / "buincity" / "contactos").mkdir()
    (tmp_path / "clientes" / "buincity" / "contactos" / "list.md").write_text("contactos", encoding="utf-8")

    # Root files (compat)
    (tmp_path / "DESIGNS.md").write_text(
        "---\ntitle: Test Designs\n---\n\n# Test Designs\n\nContent.\n",
        encoding="utf-8",
    )
    (tmp_path / "INDEX.md").write_text("# Test Index\n", encoding="utf-8")

    # Allowed sample content in v2 dir
    (tmp_path / "designs" / "test-design.md").write_text(
        "---\ntitle: Test Design\ndate: 2026-07-02\ntags: [ai,test]\n---\n\n# Test Design\n\nThis is test content for privacy tests.\n",
        encoding="utf-8",
    )

    _reload_paths(monkeypatch, tmp_path)
    return tmp_path


# ── Test 1: archivos personales nunca pasan el allowlist ─────────
def test_personal_files_never_allowed(fake_workspace):
    """Ningún archivo personal debe pasar el allowlist, aunque exista."""
    personal = [
        fake_workspace / "MEMORY.md",
        fake_workspace / "USER.md",
        fake_workspace / "SOUL.md",
        fake_workspace / "IDENTITY.md",
        fake_workspace / "AGENTS.md",
    ]
    for f in personal:
        if f.exists():
            assert not is_path_allowed(f), f"LEAK: {f} should not be allowed"


def test_personal_dirs_never_allowed(fake_workspace):
    """Cualquier archivo en dirs personales debe ser rechazado."""
    personal_dirs = [
        fake_workspace / "briefing",
        fake_workspace / "memory" / "sessions",
        fake_workspace / "clientes" / "buincity" / "contactos",
    ]
    for d in personal_dirs:
        if d.exists():
            for f in d.rglob("*"):
                if f.is_file():
                    assert not is_path_allowed(f), f"LEAK: {f}"


# ── Test 2: path traversal bloqueado ─────────────────────────────
def test_path_traversal_blocked(fake_workspace):
    """Path traversal no debe escapar del workspace."""
    with pytest.raises(PermissionError):
        safe_read(fake_workspace / "designs" / ".." / ".." / ".." / "MEMORY.md")
    with pytest.raises(PermissionError):
        safe_read(Path("/etc/shadow"))
    with pytest.raises(PermissionError):
        safe_read(Path("/root/.ssh/id_ed25519"))


def test_symlink_traversal_blocked(fake_workspace, tmp_path: Path):
    """Symlinks que apuntan a archivos privados deben ser rechazados."""
    target = fake_workspace / "MEMORY.md"
    if not target.exists():
        pytest.skip(f"target file not present: {target}")
    evil = tmp_path / "evil.md"
    try:
        evil.symlink_to(target)
    except OSError:
        pytest.skip("cannot create symlink in this env")
    assert not is_path_allowed(evil), "Symlink to private file should be blocked"


# ── Test 3: keywords personales no devuelven leaks ────────────────
def test_no_personal_leak_via_search(fake_workspace):
    """list_allowed_files no debe devolver paths que matchean denylist."""
    from memoria_mcp.paths import list_allowed_files, _matches_denylist

    files = list_allowed_files()
    for f in files:
        assert not _matches_denylist(f), f"LEAK via list_allowed_files: {f}"


# ── Test 4: safe_read falla limpio en path inválido ──────────────
def test_safe_read_invalid_path(fake_workspace):
    """safe_read en path inválido o no permitido debe raise PermissionError."""
    with pytest.raises(PermissionError):
        safe_read("/tmp/totally-random-nonexistent-path-xyz.md")


# ── Test 5: archivos permitidos pasan ──────────────────────────────
def test_allowed_files_pass(fake_workspace):
    """Archivos en allowed dirs pasan el allowlist."""
    # v2: usa el path v2 (designs/) que sí está en ALLOWED_DIRS actual
    allowed_path = fake_workspace / "designs" / "test-design.md"
    assert is_path_allowed(allowed_path), f"Allowed file should pass: {allowed_path}"
    # safe_read debería funcionar
    content = safe_read(allowed_path)
    assert "Test Design" in content


# ── Test 6: denylist matchea MEMORY.md aunque esté en allowed dir ─
def test_denylist_overrides_allowed_dir(fake_workspace):
    """Un archivo MEMORY.md dentro de designs/ debe ser rechazado."""
    decoy = fake_workspace / "designs" / "MEMORY.md"
    decoy.write_text("# decoy\n", encoding="utf-8")
    assert not is_path_allowed(decoy), "denylist must exclude MEMORY.md even inside allowlist dir"


# ── Test 7: list_allowed_files respeta scope filter ─────────────
def test_list_allowed_files_scope_filter(fake_workspace):
    """list_allowed_files(scope='designs') solo retorna designs."""
    from memoria_mcp.paths import list_allowed_files
    files = list_allowed_files("designs")
    for f in files:
        rel = f.relative_to(fake_workspace)
        assert "designs" in str(rel), f"Expected only designs, got {rel}"


# ── Test 8: workspace default respeta privacy ───────────────────
def test_workspace_override_via_env(monkeypatch, tmp_path: Path):
    """Override de WORKSPACE_ROOT vía env var sigue aplicando allowlist.

    v2: usa estructura designs/ (válida en ALLOWED_DIRS actual).
    """
    (tmp_path / "designs").mkdir(parents=True)
    (tmp_path / "designs" / "good.md").write_text("# good", encoding="utf-8")
    (tmp_path / "MEMORY.md").write_text("private", encoding="utf-8")

    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path))
    importlib.reload(__import__("memoria_mcp.paths", fromlist=["paths"]))

    from memoria_mcp.paths import is_path_allowed
    assert is_path_allowed(tmp_path / "designs" / "good.md")
    assert not is_path_allowed(tmp_path / "MEMORY.md")