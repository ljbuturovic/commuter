from __future__ import annotations

import subprocess
from pathlib import Path


def get_snapshot(project_dir: str | Path) -> dict:
    """Capture current git state for a project directory."""
    cwd = str(project_dir)
    result: dict = {"branch": None, "commit": None, "dirty_files": []}

    try:
        result["branch"] = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd)
        result["commit"] = _run(["git", "rev-parse", "HEAD"], cwd)
        dirty = _run(["git", "status", "--porcelain"], cwd)
        if dirty:
            result["dirty_files"] = [
                line[3:].strip() for line in dirty.splitlines() if line.strip()
            ]
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass  # Not a git repo or git not installed

    return result


def compare(current: dict, exported: dict) -> tuple[bool, list[str]]:
    """Compare current git state against an exported snapshot.

    Returns (matches: bool, warnings: list[str]).
    'matches' is True only if branch and commit both agree.
    """
    warnings: list[str] = []
    matches = True

    cur_branch = current.get("branch")
    exp_branch = exported.get("branch")
    if cur_branch != exp_branch:
        matches = False
        warnings.append(
            f"Branch: local={cur_branch!r}  export={exp_branch!r}"
        )

    cur_commit = current.get("commit")
    exp_commit = exported.get("commit")
    if cur_commit and exp_commit and cur_commit != exp_commit:
        matches = False
        warnings.append(
            f"Commit: local={cur_commit[:7]}  export={exp_commit[:7]}"
        )

    dirty = exported.get("dirty_files", [])
    if dirty:
        warnings.append(
            f"{len(dirty)} dirty file(s) in export not present locally: "
            + ", ".join(dirty)
        )

    return matches, warnings


def _run(cmd: list[str], cwd: str) -> str:
    return subprocess.check_output(cmd, cwd=cwd, stderr=subprocess.DEVNULL).decode().strip()
