"""db.py — MariaDB local pool para mcp-memoria.

Stack decisión (MOP-352 v3):
- MariaDB 11.8.6 LOCAL en secops :3306 (ya corriendo, validado 2026-07-02).
- Schema: DB `mcp_memoria`, prefijo `mm_` (D1 — separado de omni-mcp).
- Driver: PyMySQL 1.1+ (pure Python, portable, sync API).
- Sin dual-pool por ahora (fase futura replica a otros mariadb).

Patrón (réplica conceptual de mop-mcp/db.py y omni-mcp):
- Pool de conexiones thread-safe.
- read_one(sql, params) → dict | None.
- read_many(sql, params) → list[dict].
- write_one(sql, params) → int (lastrowid o rowcount).
- init_schema() idempotente: CREATE DATABASE + 6 tablas mm_*.
"""
from __future__ import annotations

import logging
import os
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Generator, Optional

import pymysql
from pymysql.cursors import DictCursor
from pymysql import Connection

log = logging.getLogger("memoria_db")

# ── Configuración ──────────────────────────────────────────────────
DB_NAME = os.environ.get("MCP_DB_NAME", "mcp_memoria")

DB_HOST = os.environ.get("MCP_DB_HOST", "127.0.0.1")
DB_PORT = int(os.environ.get("MCP_DB_PORT", "3306"))
DB_USER = os.environ.get("MCP_DB_USER", "root")
DB_PASS = os.environ.get("MCP_DB_PASS", "")
DB_SOCKET = os.environ.get("MCP_DB_SOCKET")  # si unix socket

POOL_MIN = int(os.environ.get("MCP_DB_POOL_MIN", "1"))
POOL_MAX = int(os.environ.get("MCP_DB_POOL_MAX", "5"))

EMBEDDING_DIM = int(os.environ.get("EMBEDDING_DIM", "384"))


# ── Pool thread-safe ──────────────────────────────────────────────
class _Pool:
    """Pool simple de conexiones PyMySQL con lock.

    Para v1 (kb/ <500 docs, single-instance) un pool de hasta 5 conexiones
    es más que suficiente. Brute-force cosine sobre kb/ entera es <100ms.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._available: list[Connection] = []

    def _make_conn(self) -> Connection:
        kwargs: dict[str, Any] = dict(
            user=DB_USER,
            password=DB_PASS,
            database=DB_NAME,
            charset="utf8mb4",
            autocommit=True,
        )
        if DB_SOCKET:
            kwargs["unix_socket"] = DB_SOCKET
        else:
            kwargs["host"] = DB_HOST
            kwargs["port"] = DB_PORT
            kwargs["connect_timeout"] = 5
        return pymysql.connect(**kwargs)

    def acquire(self) -> Connection:
        with self._lock:
            while self._available:
                conn = self._available.pop()
                # H10 audit 2026-07-02: pymysql 1.1+ deprecó `reconnect=True`.
                # Capturamos exceptions explícitamente y re-creamos la conexión.
                try:
                    conn.ping()
                except Exception:
                    try:
                        conn.close()
                    except Exception:
                        pass
                    conn = self._make_conn()
                    return conn
                return conn
            # Pool empty → crear nueva (hasta POOL_MAX en uso concurrente)
            return self._make_conn()

    def release(self, conn: Connection) -> None:
        with self._lock:
            if len(self._available) < POOL_MAX:
                self._available.append(conn)
            else:
                try:
                    conn.close()
                except Exception:
                    pass

    def close_all(self) -> None:
        with self._lock:
            for c in self._available:
                try:
                    c.close()
                except Exception:
                    pass
            self._available.clear()


_pool = _Pool()


@contextmanager
def acquire() -> Generator[Connection, None, None]:
    """Context manager para conexión del pool."""
    conn = _pool.acquire()
    try:
        yield conn
    finally:
        _pool.release(conn)


def read_one(sql: str, params: tuple = ()) -> Optional[dict]:
    """Lee una fila. Devuelve dict o None."""
    with acquire() as conn:
        with conn.cursor(DictCursor) as cur:
            cur.execute(sql, params)
            return cur.fetchone()


def read_many(sql: str, params: tuple = ()) -> list[dict]:
    """Lee múltiples filas. Devuelve lista de dicts."""
    with acquire() as conn:
        with conn.cursor(DictCursor) as cur:
            cur.execute(sql, params)
            return list(cur.fetchall())


def write_one(sql: str, params: tuple = ()) -> int:
    """Ejecuta INSERT/UPDATE/DELETE. Devuelve lastrowid o rowcount."""
    with acquire() as conn:
        try:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                return cur.lastrowid or cur.rowcount
        except Exception as e:
            log.error("write_failed", extra={"sql": sql[:100], "error": str(e)})
            raise


def write_many(sql: str, params_seq: list[tuple]) -> int:
    """Bulk insert. Devuelve rowcount total."""
    with acquire() as conn:
        try:
            with conn.cursor() as cur:
                cur.executemany(sql, params_seq)
                return cur.rowcount
        except Exception as e:
            log.error("write_many_failed", extra={"sql": sql[:100], "error": str(e)})
            raise


def health_check() -> dict:
    """Estado de conexión. Para /health endpoint."""
    try:
        with acquire() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 AS ok")
                row = cur.fetchone()
                return {"db": DB_NAME, "status": "ok" if row else "no_row"}
    except Exception as e:
        return {"db": DB_NAME, "status": "error", "error": str(e)}


# ── Schema (idempotente) ───────────────────────────────────────────
# DDL replicando el patrón omni-mcp/server.js ensureTables:
# cada CREATE usa IF NOT EXISTS para que sea safe re-correr.
SCHEMA_STATEMENTS: list[str] = [
    # Entidades (grafo)
    """
    CREATE TABLE IF NOT EXISTS mm_entities (
      id VARCHAR(64) PRIMARY KEY,
      name VARCHAR(200) NOT NULL,
      type VARCHAR(50) NOT NULL,
      attributes JSON,
      created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
      INDEX idx_type (type),
      INDEX idx_name (name)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    # Relaciones (grafo) — UNIQUE constraint para idempotencia
    """
    CREATE TABLE IF NOT EXISTS mm_relations (
      relation_id BIGINT AUTO_INCREMENT PRIMARY KEY,
      from_id VARCHAR(64) NOT NULL,
      to_id VARCHAR(64) NOT NULL,
      relation_type VARCHAR(20) NOT NULL,
      notes TEXT,
      ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
      UNIQUE KEY uniq_rel (from_id, to_id, relation_type),
      INDEX idx_from (from_id),
      INDEX idx_to (to_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    # Chunks KAG (auto-chunk + embedding BLOB)
    """
    CREATE TABLE IF NOT EXISTS mm_entity_chunks (
      id BIGINT AUTO_INCREMENT PRIMARY KEY,
      page_slug VARCHAR(200) NOT NULL,
      chunk_index INT NOT NULL,
      heading VARCHAR(200),
      chunk_text MEDIUMTEXT NOT NULL,
      entities_referenced JSON,
      word_count INT,
      embedding BLOB,
      scope VARCHAR(20),
      ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
      UNIQUE KEY uniq_chunk (page_slug, chunk_index),
      INDEX idx_slug (page_slug),
      INDEX idx_scope (scope),
      FULLTEXT INDEX ft_chunk (chunk_text, heading)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    # Feedback loop (kag_evaluar)
    """
    CREATE TABLE IF NOT EXISTS mm_search_feedback (
      id BIGINT AUTO_INCREMENT PRIMARY KEY,
      query_text VARCHAR(500) NOT NULL,
      chunk_id VARCHAR(100) NOT NULL,
      page_slug VARCHAR(200),
      feedback ENUM('useful','not_useful','partially_useful') NOT NULL,
      agent_signature VARCHAR(100),
      ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
      INDEX idx_query (query_text(100)),
      INDEX idx_chunk (chunk_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    # Conflict queue (bibliotecario)
    """
    CREATE TABLE IF NOT EXISTS mm_conflict_queue (
      id BIGINT AUTO_INCREMENT PRIMARY KEY,
      entity_type VARCHAR(20) NOT NULL,
      entity_id VARCHAR(255) NOT NULL,
      gcp_content MEDIUMTEXT,
      node_content MEDIUMTEXT,
      resolution ENUM('pending','merged','kept','skipped') DEFAULT 'pending',
      resolved_content LONGTEXT,
      resolved_by VARCHAR(50),
      notes TEXT,
      ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
      resolved_at TIMESTAMP NULL,
      INDEX idx_resolution (resolution),
      INDEX idx_entity (entity_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    # Log de búsquedas (métricas)
    """
    CREATE TABLE IF NOT EXISTS mm_search_log (
      id BIGINT AUTO_INCREMENT PRIMARY KEY,
      query_text VARCHAR(500) NOT NULL,
      method VARCHAR(20) NOT NULL,
      latency_ms INT NOT NULL,
      results_count INT NOT NULL,
      cross_refs BOOLEAN DEFAULT FALSE,
      agent_signature VARCHAR(100),
      ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
      INDEX idx_created (ts),
      INDEX idx_method (method)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    # Wiki versionada (mm_wiki_pages) — append-only, source of truth para wiki.
    # PK compuesta (slug, version) garantiza NUNCA overwrite.
    # Backup filesystem (wiki_archive/) se escribe desde wiki_escribir (MOP-398)
    # pero NO es leído por el live — es solo artefacto.
    """
    CREATE TABLE IF NOT EXISTS mm_wiki_pages (
      slug VARCHAR(200) NOT NULL,
      version INT NOT NULL,
      body MEDIUMTEXT NOT NULL,
      frontmatter JSON,
      author VARCHAR(64) NOT NULL,
      scope VARCHAR(50),
      ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
      PRIMARY KEY (slug, version),
      INDEX idx_slug (slug),
      INDEX idx_scope (scope),
      INDEX idx_ts (ts)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
]


def _ensure_database() -> None:
    """Crea la DB si no existe (no se puede usar connect con db= si no existe)."""
    # Conexión sin database, solo server
    kwargs: dict[str, Any] = dict(
        user=DB_USER,
        password=DB_PASS,
        charset="utf8mb4",
        autocommit=True,
    )
    if DB_SOCKET:
        kwargs["unix_socket"] = DB_SOCKET
    else:
        kwargs["host"] = DB_HOST
        kwargs["port"] = DB_PORT
        kwargs["connect_timeout"] = 5
    conn = pymysql.connect(**kwargs)
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"CREATE DATABASE IF NOT EXISTS {DB_NAME} "
                "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
            )
    finally:
        conn.close()


def init_schema() -> dict:
    """Crea DB + 6 tablas si no existen. Idempotente.

    Returns: {db, tables_created, status}
    """
    try:
        _ensure_database()
    except Exception as e:
        log.error("ensure_db_failed", extra={"db": DB_NAME, "error": str(e)})
        return {"db": DB_NAME, "status": "error", "error": str(e)}

    created: list[str] = []
    for stmt in SCHEMA_STATEMENTS:
        try:
            write_one(stmt)
        except Exception as e:
            log.error("ddl_failed", extra={"error": str(e), "stmt_head": stmt[:60]})
            return {"db": DB_NAME, "status": "error", "error": str(e)}
    log.info("schema_ready", extra={"db": DB_NAME, "tables": 6})
    return {"db": DB_NAME, "status": "ok", "tables": 6}


def close_pool() -> None:
    """Cierra el pool. Para shutdown."""
    _pool.close_all()