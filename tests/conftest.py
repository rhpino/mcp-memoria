"""conftest.py — pytest fixtures compartidos (mcp-memoria).

MOP-398 (2026-07-05): refactorizado para usar el patrón shared
`/opt/mcps/shared/mcp_test_isolation.py`. Sin este patrón, el pool module-level
del MCP conecta a prod al import y los fixtures de pytest que cambian
`db.DB_NAME` llegan tarde, contaminando producción.

Pre-MOP-398, conftest cargaba DB creds desde /etc/mcp-memoria/db.env. Ahora
usamos el helper shared que:
  - Fuerza `MCP_DB_NAME=mcp_memoria_test` ANTES de importar memoria_mcp.
  - Carga credenciales (USER/PASS/HOST/PORT) desde db.env SIN pisar DB_NAME.
"""
import sys

# CRÍTICO: agregar /opt/mcps al path ANTES de importar shared.
sys.path.insert(0, "/opt/mcps")

from shared.mcp_test_isolation import force_test_db, make_isolate_fixture

# 1) Setup ANTES de cualquier import de memoria_mcp.
force_test_db(
    env_var="MCP_DB_NAME",
    test_db_name="mcp_memoria_test",
    db_env_path="/etc/mcp-memoria/db.env",
)

import pytest


# 2) Fixture autouse compartido que cierra el pool entre tests.
isolate_test_db = make_isolate_fixture(
    pool_package="memoria_mcp.db",
    close_fn_name="close_pool",
    db_name_attr="DB_NAME",
    test_db_name="mcp_memoria_test",
)


def pytest_collection_modifyitems(config, items):
    """Skip tests que requieren DB si MCP_DB_PASS no está disponible."""
    import os
    if os.environ.get("MCP_DB_PASS"):
        return
    skip_marker = pytest.mark.skip(reason="MCP_DB_PASS not set; /etc/mcp-memoria/db.env not found")
    for item in items:
        if "db" in item.keywords or any("db" in m for m in item.iter_markers()):
            item.add_marker(skip_marker)