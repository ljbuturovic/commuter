"""Tests for `commuter host` — direct ssh/scp transfer, no transfer directory.

`host` selects the current directory's session (same physical-dir logic as
`push`), requires the project's session directory to already exist on the remote
(never creating it), and scp's the transcript straight in so `claude --continue`
resumes it there.
"""
import subprocess
from types import SimpleNamespace

from click.testing import CliRunner

import commuter.backends.claude_code as cc
from commuter import cli as cli_mod
from commuter.pathmap import encode_project_path


def _write_session(project_dir, session_id, ts):
    project_dir.mkdir(parents=True, exist_ok=True)
    entry = (
        '{"type": "user", "message": {"content": "hi"}, '
        f'"timestamp": "{ts}", "sessionId": "{session_id}", "cwd": "x"}}\n'
    )
    (project_dir / f"{session_id}.jsonl").write_text(entry)


def _fake_run_factory(calls, *, test_dir_rc=0):
    """Return a subprocess.run stand-in that records calls and fakes returncodes."""
    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        if cmd[:1] == ["ssh"] and "test" in cmd:
            return SimpleNamespace(returncode=test_dir_rc)
        if cmd[:1] == ["scp"]:
            return SimpleNamespace(returncode=0)
        return SimpleNamespace(returncode=0)
    return fake_run


def _setup(tmp_path, monkeypatch):
    projects = tmp_path / "projects"
    cwd = tmp_path / "cvic"
    cwd.mkdir()
    encoded = encode_project_path(str(cwd))
    _write_session(projects / encoded, "aaaaaaaa-0000-0000-0000-000000000001",
                   "2026-07-13T10:00:00Z")
    monkeypatch.setattr(cc, "PROJECTS_DIR", projects)
    monkeypatch.chdir(cwd)
    return cwd, encoded


def test_host_copies_transcript_when_remote_dir_exists(tmp_path, monkeypatch):
    cwd, encoded = _setup(tmp_path, monkeypatch)
    calls = []
    monkeypatch.setattr(cli_mod.subprocess, "run", _fake_run_factory(calls))

    result = CliRunner().invoke(cli_mod.cli, ["host", "basel"])
    assert result.exit_code == 0, result.output

    remote_dir = f".claude/projects/{encoded}"
    remote_path = f"{remote_dir}/aaaaaaaa-0000-0000-0000-000000000001.jsonl"
    # Existence is checked, and the transcript is scp'd to the same encoded dir.
    assert ["ssh", "basel", "test", "-d", remote_dir] in calls
    scp = [c for c in calls if c[0] == "scp"]
    assert len(scp) == 1
    assert scp[0][-1] == f"basel:{remote_path}"
    # No -p: a fresh mtime is what makes `claude --continue` pick it.
    assert "-p" not in scp[0]


def test_host_errors_and_skips_copy_when_remote_dir_missing(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    calls = []
    monkeypatch.setattr(cli_mod.subprocess, "run",
                        _fake_run_factory(calls, test_dir_rc=1))

    result = CliRunner().invoke(cli_mod.cli, ["host", "basel"])
    assert result.exit_code != 0
    assert "no session directory" in result.output
    # Must NOT create the dir and must NOT copy anything.
    assert not any(c[0] == "scp" for c in calls)
    assert not any("mkdir" in c for c in calls)


def test_host_reports_connection_failure(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    calls = []
    monkeypatch.setattr(cli_mod.subprocess, "run",
                        _fake_run_factory(calls, test_dir_rc=255))

    result = CliRunner().invoke(cli_mod.cli, ["host", "basel"])
    assert result.exit_code != 0
    assert "Could not connect" in result.output
    assert not any(c[0] == "scp" for c in calls)


def test_host_no_session_for_cwd(tmp_path, monkeypatch):
    projects = tmp_path / "projects"
    projects.mkdir()
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.setattr(cc, "PROJECTS_DIR", projects)
    monkeypatch.chdir(empty)
    calls = []
    monkeypatch.setattr(cli_mod.subprocess, "run", _fake_run_factory(calls))

    result = CliRunner().invoke(cli_mod.cli, ["host", "basel"])
    assert result.exit_code != 0
    assert "No session found" in result.output
    assert calls == []
