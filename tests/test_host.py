"""Tests for `commuter host` — direct ssh/scp transport, no transfer directory.

`host` selects the current directory's session (same physical-dir logic as
`push`), builds the same commuter bundle as push, scp's that bundle to the
remote host, and runs the normal importer there so `claude --continue` resumes
it with the same semantics as pull.
"""
import json
from pathlib import Path
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


def _fake_run_factory(calls, copied_bundles=None, *, scp_rc=0, import_rc=0):
    """Return a subprocess.run stand-in that records calls and fakes returncodes."""
    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        if cmd[:1] == ["git"]:
            return SimpleNamespace(returncode=0, stdout=b"")
        if cmd[:1] == ["scp"]:
            if copied_bundles is not None and scp_rc == 0:
                copied_bundles.append(json.loads(Path(cmd[2]).read_text()))
            return SimpleNamespace(returncode=scp_rc, stdout=b"")
        if cmd[:1] == ["ssh"]:
            return SimpleNamespace(returncode=import_rc, stdout=b"")
        return SimpleNamespace(returncode=0, stdout=b"")
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


def test_host_copies_bundle_and_runs_remote_import(tmp_path, monkeypatch):
    cwd, _encoded = _setup(tmp_path, monkeypatch)
    calls = []
    copied_bundles = []
    monkeypatch.setattr(
        cli_mod.subprocess,
        "run",
        _fake_run_factory(calls, copied_bundles),
    )

    result = CliRunner().invoke(cli_mod.cli, ["host", "basel"])
    assert result.exit_code == 0, result.output

    session_id = "aaaaaaaa-0000-0000-0000-000000000001"
    remote_path = f"/tmp/commuter-{session_id}.json"

    # No remote Claude storage preflight: remote import creates/updates it.
    assert not any(c[:3] == ["ssh", "basel", "test"] for c in calls)

    scp = [c for c in calls if c[0] == "scp"]
    assert len(scp) == 1
    assert scp[0][1] == "-q"
    assert scp[0][-1] == f"basel:{remote_path}"

    ssh = [c for c in calls if c[0] == "ssh"]
    assert ssh == [
        [
            "ssh",
            "basel",
            'PATH="$HOME/.local/bin:$PATH" '
            f"commuter import {remote_path} --replace --no-launch",
        ]
    ]

    assert len(copied_bundles) == 1
    bundle = copied_bundles[0]
    assert bundle["tool"] == "commuter"
    assert bundle["session"]["id"] == session_id
    assert bundle["session"]["project_dir"] == str(cwd)


def test_host_passes_remote_project_dir_override(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    calls = []
    monkeypatch.setattr(cli_mod.subprocess, "run", _fake_run_factory(calls))

    result = CliRunner().invoke(
        cli_mod.cli,
        ["host", "basel", "--project-dir", "/remote/cvic"],
    )
    assert result.exit_code == 0, result.output

    ssh = [c for c in calls if c[0] == "ssh"]
    assert ssh == [[
        "ssh",
        "basel",
        'PATH="$HOME/.local/bin:$PATH" commuter import '
        "/tmp/commuter-aaaaaaaa-0000-0000-0000-000000000001.json "
        "--replace --no-launch --project-dir /remote/cvic",
    ]]
    assert "cd /remote/cvic && claude --continue" in result.output


def test_host_errors_when_scp_fails(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    calls = []
    monkeypatch.setattr(
        cli_mod.subprocess,
        "run",
        _fake_run_factory(calls, scp_rc=1),
    )

    result = CliRunner().invoke(cli_mod.cli, ["host", "basel"])
    assert result.exit_code != 0
    assert "Failed to copy bundle" in result.output
    assert not any(c[0] == "ssh" for c in calls)


def test_host_reports_remote_import_failure(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    calls = []
    monkeypatch.setattr(
        cli_mod.subprocess,
        "run",
        _fake_run_factory(calls, import_rc=1),
    )

    result = CliRunner().invoke(cli_mod.cli, ["host", "basel"])
    assert result.exit_code != 0
    assert "Remote import failed" in result.output
    assert any(c[0] == "scp" for c in calls)
    assert any(c[0] == "ssh" for c in calls)


def test_host_reports_connection_failure(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    calls = []
    monkeypatch.setattr(
        cli_mod.subprocess,
        "run",
        _fake_run_factory(calls, scp_rc=255),
    )

    result = CliRunner().invoke(cli_mod.cli, ["host", "basel"])
    assert result.exit_code != 0
    assert "Could not connect" in result.output
    assert any(c[0] == "scp" for c in calls)
    assert not any(c[0] == "ssh" for c in calls)


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
