"""Regression tests for `commuter push` session selection.

The key invariant: push must select the session by the directory its transcript
file physically lives in (how Claude Code maps sessions to projects), not by the
`cwd` recorded inside the transcript. After a folder rename those diverge, and
push must still pick the same session `claude --continue` would resume.
"""
import json

from click.testing import CliRunner

import commuter.backends.claude_code as cc
from commuter import cli as cli_mod
from commuter import config as config_mod
from commuter.pathmap import encode_project_path


def _write_session(project_dir, session_id, cwd_field, ts):
    """Write a minimal valid transcript for one session into project_dir."""
    project_dir.mkdir(parents=True, exist_ok=True)
    entry = {
        "type": "user",
        "message": {"content": f"prompt for {session_id[:4]}"},
        "timestamp": ts,
        "version": "2.1.0",
        "cwd": cwd_field,
        "sessionId": session_id,
    }
    (project_dir / f"{session_id}.jsonl").write_text(json.dumps(entry) + "\n")


def test_push_selects_by_physical_dir_after_rename(tmp_path, monkeypatch):
    projects = tmp_path / "projects"
    # The current working directory (post-rename folder).
    cwd = tmp_path / "cvic"
    cwd.mkdir()
    encoded_cwd = encode_project_path(str(cwd))

    # Both transcripts physically live in the cwd's project dir, but the recent
    # one still records an OLD internal cwd (the pre-rename "krunic" path).
    proj_dir = projects / encoded_cwd
    _write_session(proj_dir, "aaaaaaaa-0000-0000-0000-000000000001",
                   cwd_field="/home/user/krunic", ts="2026-07-13T10:00:00Z")
    _write_session(proj_dir, "bbbbbbbb-0000-0000-0000-000000000002",
                   cwd_field=str(cwd), ts="2026-06-01T10:00:00Z")

    transfer = tmp_path / "transfer"
    monkeypatch.setattr(cc, "PROJECTS_DIR", projects)
    monkeypatch.setattr(config_mod, "get_transfer_dir", lambda: transfer)
    monkeypatch.chdir(cwd)

    result = CliRunner().invoke(cli_mod.cli, ["push"])
    assert result.exit_code == 0, result.output

    pending = list((transfer / "pending").glob("*.json"))
    assert len(pending) == 1
    bundle = json.loads(pending[0].read_text())

    # Must push the physically-present, most-recent session — the one whose
    # internal cwd is stale — not the older session whose cwd happens to match.
    assert bundle["session"]["id"] == "aaaaaaaa-0000-0000-0000-000000000001"
    # And it must be tagged with the current directory, not the stale cwd.
    assert bundle["session"]["project_dir"] == str(cwd)
