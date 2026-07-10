"""memoria-mcp — MCP server para memoria de proyectos.

Replica el patrón de mop-mcp (FastAPI + FastMCP + sqlite-vec + fastembed)
pero para kb/ (decisiones, lecciones, ADRs, links cruzados).

Privacidad física: allowlist de paths (NO lee archivos personales).
Stage 0: RESEARCH.md justificó sqlite-vec + paraphrase-multilingual-MiniLM-L12-v2.
"""

__version__ = "0.1.0"
__all__ = ["__version__"]


# Configurar logging al importar para que las tools tengan logger
import logging
import os


def _setup_default_logging() -> None:
    """Setup logging default. Sobreescribible por setup_logging()."""
    level = os.environ.get("MCP_LOG_LEVEL", "info").upper()
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


_setup_default_logging()