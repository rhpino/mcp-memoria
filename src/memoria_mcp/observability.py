"""observability.py — Logging + metrics setup + audit logging."""
from __future__ import annotations

import json
import logging
import os
import sys
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import Any

# ── Logging setup ─────────────────────────────────────────────────
def setup_logging(level: str | None = None) -> None:
    level = (level or os.environ.get("MCP_LOG_LEVEL", "info")).upper()
    fmt = os.environ.get("MCP_LOG_FORMAT", "plain").lower()

    root = logging.getLogger()
    if getattr(root, "_memoria_configured", False):
        return

    root.setLevel(level)
    for h in list(root.handlers):
        root.removeHandler(h)

    handler = logging.StreamHandler(stream=sys.stdout)
    if fmt == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
        )
    root.addHandler(handler)
    root._memoria_configured = True


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


class JsonFormatter(logging.Formatter):
    _RESERVED = {
        "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
        "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
        "created", "msecs", "relativeCreated", "thread", "threadName",
        "processName", "process", "message", "taskName",
    }

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for k, v in record.__dict__.items():
            if k in self._RESERVED or k.startswith("_"):
                continue
            try:
                json.dumps(v)
                payload[k] = v
            except (TypeError, ValueError):
                payload[k] = str(v)
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


# ── Metrics ──────────────────────────────────────────────────────
class Metrics:
    """Counter + histogram + gauge con export Prometheus text."""

    def __init__(self) -> None:
        self._counters: dict[str, int] = defaultdict(int)
        # Audit mcp-memoria 2026-07-05 (MOP-388) C2: bounded deque(maxlen=1000).
        # Audit B1: pre-fix era `defaultdict(list)` con append ilimitado → OOM
        # eventual. Ahora cap a 1000 samples por (metric, label) combo.
        self._histograms: dict[str, deque] = defaultdict(
            lambda: deque(maxlen=1000)
        )
        self._gauges: dict[str, float] = {}
        self._counter_started: dict[str, float] = {}

    def inc(self, name: str, labels: dict[str, str] | None = None, value: int = 1) -> None:
        key = self._key(name, labels)
        self._counters[key] += value

    def observe(self, name: str, value: float, labels: dict[str, str] | None = None) -> None:
        key = self._key(name, labels)
        self._histograms[key].append(value)

    def set_gauge(self, name: str, value: float) -> None:
        self._gauges[name] = value

    @staticmethod
    def _key(name: str, labels: dict[str, str] | None) -> str:
        if not labels:
            return name
        items = ",".join(f'{k}="{v}"' for k, v in sorted(labels.items()))
        return f"{name}{{{items}}}"

    def to_prometheus(self) -> str:
        out: list[str] = []
        for key, val in self._counters.items():
            out.append(f"{key} {val}")
        for key, vals in self._histograms.items():
            if not vals:
                continue
            n = len(vals)
            total = sum(vals)
            mean = total / n
            sorted_vals = sorted(vals)
            p50 = sorted_vals[n // 2]
            p95 = sorted_vals[min(n - 1, int(n * 0.95))]
            out.append(f"{key}_count {n}")
            out.append(f"{key}_sum {total:.6f}")
            out.append(f'{key}_mean {{quantile="0.5"}} {p50:.6f}')
            out.append(f'{key}_mean {{quantile="0.95"}} {p95:.6f}')
            out.append(f"{key}_mean {mean:.6f}")
        for name, val in self._gauges.items():
            out.append(f"{name} {val}")
        return "\n".join(out) + "\n"


# Singleton
metrics = Metrics()


# ── Audit log ────────────────────────────────────────────────────
class AuditLog:
    """Append-only audit log para eventos de seguridad (auth, writes).

    Persiste en MariaDB `mm_audit_log` si está disponible; fallback a JSONL file.
    """

    def __init__(self, path: str = "/var/log/mcp-memoria/audit.jsonl"):
        self.path = path

    def record(self, event: str, actor: str = "anonymous", **details: Any) -> None:
        import json as _json
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "event": event,
            "actor": actor,
            **details,
        }
        try:
            import os as _os
            _os.makedirs(_os.path.dirname(self.path), exist_ok=True)
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(_json.dumps(entry, ensure_ascii=False) + "\n")
        except OSError:
            pass  # best-effort


audit = AuditLog()


# ── Decorator para observabilidad de tools ──────────────────────
def instrument(tool_name: str):
    """Decorador que mide latencia + cuenta llamadas de cada tool."""

    def decorator(func):
        import functools

        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            t0 = time.time()
            try:
                result = await func(*args, **kwargs)
                metrics.inc("tool_calls_total", {"tool": tool_name, "status": "ok"})
                return result
            except Exception as e:
                metrics.inc("tool_calls_total", {"tool": tool_name, "status": "error"})
                raise
            finally:
                elapsed_ms = (time.time() - t0) * 1000
                metrics.observe("tool_duration_ms", elapsed_ms, {"tool": tool_name})

        return wrapper

    return decorator