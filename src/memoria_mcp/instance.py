"""instance.py — Identidad de instancia de mcp-memoria."""
from __future__ import annotations

import json
import logging
import os
import socket
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

log = logging.getLogger("memoria_instance")

INSTANCE_DIR = Path(
    os.environ.get(
        "MCP_INSTANCE_DIR",
        str(Path.home() / ".mcp-memoria"),
    )
)
INSTANCE_FILE = INSTANCE_DIR / "instance.json"


def _get_tailscale_ip() -> Optional[str]:
    try:
        out = subprocess.run(
            ["tailscale", "ip", "-4"],
            capture_output=True,
            text=True,
            timeout=2,
        )
        if out.returncode == 0:
            ip = out.stdout.strip().split("\n")[0]
            if ip:
                return ip
    except (FileNotFoundError, subprocess.TimeoutExpired, Exception):
        pass
    return None


def get_or_create_instance() -> dict:
    INSTANCE_DIR.mkdir(parents=True, exist_ok=True)
    if INSTANCE_FILE.exists():
        try:
            data = json.loads(INSTANCE_FILE.read_text(encoding="utf-8"))
            data["last_seen_at"] = datetime.now(timezone.utc).isoformat()
            INSTANCE_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
            return data
        except (json.JSONDecodeError, OSError) as e:
            log.warning("instance_file_corrupt", extra={"error": str(e)})
    hostname = socket.gethostname()[:64]
    tailscale_ip = _get_tailscale_ip()
    now = datetime.now(timezone.utc).isoformat()
    data = {
        "instance_id": str(uuid.uuid4()),
        "hostname": hostname,
        "tailscale_ip": tailscale_ip,
        "created_at": now,
        "last_seen_at": now,
    }
    INSTANCE_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
    log.info("instance_created",
             extra={"instance_id": data["instance_id"], "hostname": hostname})
    return data


def get_instance() -> Optional[dict]:
    if not INSTANCE_FILE.exists():
        return None
    try:
        return json.loads(INSTANCE_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        log.warning("instance_file_read_failed", extra={"error": str(e)})
        return None