# SECURITY.md — mcp-memoria privacy boundaries

**Principio:** privacidad por construcción, no por convención. El server **NO** tiene acceso a archivos privados ni por path ni por nombre. Si una pieza de config está mal y el path es accesible, igual falla el allowlist.

---

## 1. Allowlist (lo que SÍ lee)

| Path pattern | Tipo |
|---|---|
| `~/.openclaw/workspace/kb/decisions/*` | Decisiones técnicas |
| `~/.openclaw/workspace/kb/lessons/*` | Lecciones aprendidas |
| `~/.openclaw/workspace/kb/jobs/*` | Jobs activos |
| `~/.openclaw/workspace/kb/concepts/*` | Conceptos técnicos |
| `~/.openclaw/workspace/kb/wiki/*` | Wiki técnica |
| `~/.openclaw/workspace/04-decisions/*` | ADRs (0001-0020+) |
| `~/.openclaw/workspace/clientes/*/decisions.md` | Decisiones por cliente (headlines) |

Cada path es resuelto con `os.path.realpath()` antes de checkear contra la allowlist — previene symlink traversal.

---

## 2. Denylist explícita (lo que NUNCA lee)

| Path | Razón |
|---|---|
| `~/.openclaw/workspace/MEMORY.md` | Memoria personal de Geo (decisiones, lecciones) |
| `~/.openclaw/workspace/SOUL.md` | Identidad de Geo |
| `~/.openclaw/workspace/IDENTITY.md` | Quién es Geo |
| `~/.openclaw/workspace/USER.md` | Rodrigo, Josefina, Rosa, contactos |
| `~/.openclaw/workspace/AGENTS.md` | Reglas operativas internas |
| `~/.openclaw/workspace/briefing/` | Contexto privado de sesión |
| `~/.openclaw/workspace/memory/sessions/` | Conversaciones (sesiones de chat) |
| `~/.openclaw/workspace/clientes/*/contactos*` | Datos personales de clientes |
| `/etc/shadow` y otros | Sistema operativo |
| Cualquier path fuera de `~/.openclaw/workspace/` | Defensa en profundidad |

---

## 3. Implementación del check (paths.py)

```python
import os
from pathlib import Path

WORKSPACE = Path(os.environ.get("WORKSPACE_ROOT", "/home/cloudops/.openclaw/workspace"))

ALLOWLIST = [
    WORKSPACE / "kb" / "decisions",
    WORKSPACE / "kb" / "lessons",
    WORKSPACE / "kb" / "jobs",
    WORKSPACE / "kb" / "concepts",
    WORKSPACE / "kb" / "wiki",
    WORKSPACE / "04-decisions",
    *WORKSPACE.glob("clientes/*/decisions.md"),  # files, not dirs
]

DENYLIST_PATTERNS = [
    "MEMORY.md", "USER.md", "SOUL.md", "IDENTITY.md", "AGENTS.md",
    "/briefing/", "/memory/", "/contactos",
]

def is_path_allowed(path: Path) -> bool:
    """True si el path está dentro del allowlist y no matchea denylist."""
    try:
        real = path.resolve(strict=True)
    except (OSError, RuntimeError):
        return False

    # Check allowlist
    in_allow = False
    for allowed in ALLOWLIST:
        try:
            real.relative_to(allowed.resolve())
            in_allow = True
            break
        except ValueError:
            continue
    if not in_allow:
        return False

    # Check denylist (defense in depth)
    path_str = str(real)
    for pattern in DENYLIST_PATTERNS:
        if pattern in path_str:
            return False

    return True

def safe_read(path: Path) -> str:
    """Lee un archivo solo si está en el allowlist."""
    if not is_path_allowed(path):
        raise PermissionError(f"Path not allowed: {path}")
    return path.read_text(encoding="utf-8")
```

---

## 4. Test de no-leak (CRÍTICO, debe correr primero en CI)

```python
# tests/test_no_leak.py
import pytest
from memoria_mcp.server import MemMCPServer
from memoria_mcp.paths import is_path_allowed, safe_read

def test_personal_files_never_allowed():
    """Ningún archivo personal debe pasar el allowlist, aunque el path exista."""
    workspace = Path("/home/cloudops/.openclaw/workspace")
    personal_files = [
        workspace / "MEMORY.md",
        workspace / "USER.md",
        workspace / "SOUL.md",
        workspace / "IDENTITY.md",
        workspace / "AGENTS.md",
        workspace / "briefing" / "AGENTS.md",  # ejemplo
    ]
    for f in personal_files:
        if f.exists():
            assert not is_path_allowed(f), f"LEAK: {f} should not be allowed"

def test_personal_dirs_never_allowed():
    """Directorios personales tampoco."""
    workspace = Path("/home/cloudops/.openclaw/workspace")
    personal_dirs = [
        workspace / "briefing",
        workspace / "memory" / "sessions",
        workspace / "clientes" / "buincity" / "contactos",
    ]
    for d in personal_dirs:
        if d.exists():
            # Cualquier archivo dentro debe ser rechazado
            for f in d.rglob("*"):
                if f.is_file():
                    assert not is_path_allowed(f), f"LEAK: {f}"

def test_path_traversal_blocked():
    """Path traversal no debe escapar del workspace."""
    with pytest.raises(PermissionError):
        safe_read(Path("/home/cloudops/.openclaw/workspace/kb/decisions/../../../MEMORY.md"))
    with pytest.raises(PermissionError):
        safe_read(Path("/etc/shadow"))
    with pytest.raises(PermissionError):
        safe_read(Path("/root/.ssh/id_ed25519"))

def test_symlink_traversal_blocked():
    """Symlinks que apuntan fuera deben ser rechazados."""
    import tempfile, os
    with tempfile.TemporaryDirectory() as tmpdir:
        # Crear symlink que apunta a MEMORY.md
        symlink = Path(tmpdir) / "evil.md"
        try:
            symlink.symlink_to("/home/cloudops/.openclaw/workspace/MEMORY.md")
            assert not is_path_allowed(symlink), "Symlink to private file should be blocked"
        except OSError:
            pass  # OK if symlink not allowed to create

def test_no_personal_leak_via_search():
    """Keywords personales no deben devolver resultados desde memoria personal."""
    server = MemMCPServer(test_mode=True)
    personal_keywords = ["Rodrigo", "Josefina", "Rosa", "rhpino", "TARS", "Entel"]
    for kw in personal_keywords:
        results = server.cross_links(kw)
        for r in results:
            assert "MEMORY" not in r.source
            assert "USER" not in r.source
            assert "SOUL" not in r.source
            assert "IDENTITY" not in r.source
            assert "AGENTS" not in r.source
            assert "/briefing/" not in r.source
            assert "/memory/" not in r.source
            assert "/contactos" not in r.source
```

---

## 5. Auditoría periódica (manual)

Una vez al mes, Rodrigo (o un agente con scope admin) corre:

```bash
# En secops, con cuenta rodrigo:
sudo -u geo /opt/mcps/memoria/.venv/bin/python -c "
from memoria_mcp.paths import is_path_allowed
from pathlib import Path
import os

workspace = Path('/home/cloudops/.openclaw/workspace')
total = 0
leaked = 0
for path in workspace.rglob('*'):
    if path.is_file() and not is_path_allowed(path):
        leaked += 1
        if leaked <= 5:
            print(f'NOT IN ALLOWLIST (OK si es privado): {path}')
    if path.is_file():
        total += 1
print(f'\n{total} files totales, {leaked} fuera de allowlist (esperado: muchos)')
"
```

Si encuentra archivos que **deberían** estar en allowlist pero no están, se actualiza el config. Si encuentra archivos privados que sí pasan, es bug crítico.

---

## 6. Respuesta ante incidente

Si `test_no_personal_leak` falla en CI o en producción:

1. **STOP** del server: `sudo systemctl mcp-memoria`
2. **Auditoría**: revisar logs, identificar qué path fue filtrado
3. **Patch**: actualizar `paths.py` con el path correcto
4. **Verificación**: re-correr tests, validar fix
5. **Re-deploy**: `sudo systemctl mcp-memoria`
6. **Notificación**: mensaje a Rodrigo con detalles

---

## 7. NO permitimos

- `link_add` desde el MCP público que apunte a entidades privadas
- Custom `kb/index.json` que mencione paths privados
- Override de `WORKSPACE_ROOT` por env var sin auth admin
- Lectura de archivos fuera de `~/.openclaw/workspace/` (ni siquiera para "testing")
