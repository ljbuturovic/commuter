from __future__ import annotations

import json
from pathlib import Path

CONFIG_DIR = Path.home() / ".config" / "commuter"
CONFIG_FILE = CONFIG_DIR / "config.json"


def _load() -> dict:
    if not CONFIG_FILE.exists():
        return {}
    return json.loads(CONFIG_FILE.read_text())


def _save(cfg: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2) + "\n")


def get(key: str, default=None):
    return _load().get(key, default)


def get_path_maps() -> list[tuple[str, str]]:
    """Return list of (from, to) path mapping tuples."""
    return [tuple(m) for m in _load().get("path-maps", [])]


def add_path_map(from_path: str, to_path: str) -> None:
    cfg = _load()
    maps = cfg.get("path-maps", [])
    # Replace existing mapping with same from_path
    maps = [m for m in maps if m[0] != from_path]
    maps.append([from_path, to_path])
    cfg["path-maps"] = maps
    _save(cfg)


def get_transfer_dir() -> Path | None:
    val = _load().get("transfer-dir")
    return Path(val).expanduser() if val else None


def set_transfer_dir(path: str) -> None:
    cfg = _load()
    cfg["transfer-dir"] = str(Path(path).expanduser())
    _save(cfg)
