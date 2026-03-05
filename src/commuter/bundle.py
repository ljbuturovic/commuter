from __future__ import annotations

import getpass
import gzip
import json
import platform
import socket
from datetime import datetime, timezone
from pathlib import Path

BUNDLE_VERSION = "1.0"
TOOL_NAME = "commuter"


def create(
    *,
    backend: str,
    session_id: str,
    project_dir: str,
    conversation: list[dict],
    config: dict,
    git_snapshot: dict,
    lineage_hash: str,
    backend_version: str | None = None,
) -> dict:
    now = datetime.now(timezone.utc).isoformat()

    started_at = conversation[0].get("timestamp", now) if conversation else now
    last_activity = conversation[-1].get("timestamp", now) if conversation else now
    message_count = sum(1 for e in conversation if e.get("type") in ("user", "assistant"))

    return {
        "version": BUNDLE_VERSION,
        "tool": TOOL_NAME,
        "backend": backend,
        "exported_at": now,
        "source": {
            "hostname": socket.gethostname(),
            "os": platform.system(),
            "backend_version": backend_version,
            "username": getpass.getuser(),
        },
        "session": {
            "id": session_id,
            "project_dir": project_dir,
            "started_at": started_at,
            "last_activity": last_activity,
            "message_count": message_count,
            "lineage_hash": lineage_hash,
            "conversation": conversation,
            "config": config,
        },
        "git_snapshot": git_snapshot,
    }


def write(bundle: dict, path: Path | str, compress: bool = False) -> None:
    path = Path(path)
    data = json.dumps(bundle, ensure_ascii=False, indent=2).encode()
    if compress:
        with gzip.open(path, "wb") as f:
            f.write(data)
    else:
        path.write_bytes(data)


def read(path: Path | str) -> dict:
    path = Path(path)
    if _is_gzip(path):
        with gzip.open(path, "rb") as f:
            return json.loads(f.read())
    return json.loads(path.read_text())


def validate(bundle: dict) -> list[str]:
    """Return list of validation errors; empty list means valid."""
    errors: list[str] = []
    if bundle.get("tool") != TOOL_NAME:
        errors.append(f"Not a commuter bundle (tool={bundle.get('tool')!r})")
    if "version" not in bundle:
        errors.append("Missing version field")
    sess = bundle.get("session")
    if not sess:
        errors.append("Missing session data")
    else:
        if "id" not in sess:
            errors.append("Missing session.id")
        if "conversation" not in sess:
            errors.append("Missing session.conversation")
        if "project_dir" not in sess:
            errors.append("Missing session.project_dir")
    return errors


def _is_gzip(path: Path) -> bool:
    try:
        with open(path, "rb") as f:
            return f.read(2) == b"\x1f\x8b"
    except OSError:
        return False
