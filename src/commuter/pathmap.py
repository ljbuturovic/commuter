from __future__ import annotations

from pathlib import Path

from . import config


def translate(path: str, maps: list[tuple[str, str]] | None = None) -> str:
    """Translate a path using configured mappings, trying both directions.

    Returns the original path unchanged if no mapping matches.
    """
    if maps is None:
        maps = config.get_path_maps()

    # Build all directional pairs (both A→B and B→A) sorted longest-prefix first
    all_pairs: list[tuple[str, str]] = []
    for from_path, to_path in maps:
        all_pairs.append((from_path, to_path))
        all_pairs.append((to_path, from_path))
    all_pairs.sort(key=lambda p: len(p[0]), reverse=True)

    for from_path, to_path in all_pairs:
        if path == from_path:
            return to_path
        if path.startswith(from_path + "/"):
            return to_path + path[len(from_path):]

    return path


def encode_project_path(project_dir: str | Path) -> str:
    """Encode a project directory path as used by Claude Code for its storage dir name.

    Example: /home/user/projects/foo -> -home-user-projects-foo
    """
    return str(Path(project_dir).resolve()).replace("/", "-")
