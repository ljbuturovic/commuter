"""Tests for `commuter from` (pull over ssh/scp) and `export --from-cwd`.

`from` is the mirror of `to`: it runs `commuter export --from-cwd` on the remote
(so the remote picks the session for the project dir), copies the bundle back,
and imports it locally. `--from-cwd` is the selection primitive that makes the
remote side pick the same session `push`/`to` would.
"""
import json
import re
from pathlib import Path
from types import SimpleNamespace

from click.testing import CliRunner

import commuter.backends.claude_code as cc
from commuter import cli as cli_mod
from commuter.pathmap import encode_project_path


# --------------------------------------------------------------------------- #
# `commuter from`
# --------------------------------------------------------------------------- #

def _fake_run_factory(calls, *, export_rc=0, scp_rc=0):
    """subprocess.run stand-in: fakes the remote export, scp-down, and remote rm."""
    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        if cmd[0] == "ssh" and "commuter export" in cmd[2]:
            return SimpleNamespace(returncode=export_rc, stdout=b"")
        if cmd[0] == "scp":
            # Download: cmd = ["scp", "-q", "host:/tmp/...json", localdest]
            if scp_rc == 0 and ":" in cmd[2]:
                Path(cmd[3]).write_text(json.dumps({
                    "tool": "commuter",
                    "session": {"id": "aaaa", "project_dir": "/x"},
                }))
            return SimpleNamespace(returncode=scp_rc, stdout=b"")
        if cmd[0] == "ssh" and "rm -f" in cmd[2]:
            return SimpleNamespace(returncode=0, stdout=b"")
        return SimpleNamespace(returncode=0, stdout=b"")
    return fake_run


def test_from_exports_remotely_copies_back_and_imports(tmp_path, monkeypatch):
    cwd = tmp_path / "cvic"
    cwd.mkdir()
    monkeypatch.chdir(cwd)
    calls = []
    monkeypatch.setattr(cli_mod.subprocess, "run", _fake_run_factory(calls))
    imported = []
    monkeypatch.setattr(cli_mod, "cmd_import", lambda **kw: imported.append(kw))

    result = CliRunner().invoke(cli_mod.cli, ["from", "ljubljana"])
    assert result.exit_code == 0, result.output

    # Remote export selects by cwd, run in the project directory on the remote.
    ssh_export = [c for c in calls if c[0] == "ssh" and "commuter export" in c[2]]
    assert len(ssh_export) == 1
    assert "commuter export --from-cwd -o /tmp/commuter-from-" in ssh_export[0][2]
    assert f"cd {cwd} &&" in ssh_export[0][2]

    # Bundle is copied back from the remote, then the remote temp is cleaned up.
    scp = [c for c in calls if c[0] == "scp"]
    assert len(scp) == 1
    assert re.fullmatch(r"ljubljana:/tmp/commuter-from-[0-9a-f]+\.json", scp[0][2])
    assert any(c[0] == "ssh" and "rm -f" in c[2] for c in calls)

    # Imported locally with the same flags pull uses.
    assert len(imported) == 1
    assert imported[0]["replace"] is True
    assert imported[0]["no_launch"] is True
    assert "Pulled session from ljubljana" in result.output


def test_from_uses_project_dir_override_for_remote(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    calls = []
    monkeypatch.setattr(cli_mod.subprocess, "run", _fake_run_factory(calls))
    monkeypatch.setattr(cli_mod, "cmd_import", lambda **kw: None)

    result = CliRunner().invoke(
        cli_mod.cli, ["from", "ljubljana", "--project-dir", "/remote/cvic"]
    )
    assert result.exit_code == 0, result.output
    ssh_export = [c for c in calls if c[0] == "ssh" and "commuter export" in c[2]]
    assert "cd /remote/cvic &&" in ssh_export[0][2]


def test_from_reports_remote_export_failure(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    calls = []
    monkeypatch.setattr(cli_mod.subprocess, "run",
                        _fake_run_factory(calls, export_rc=1))
    monkeypatch.setattr(cli_mod, "cmd_import", lambda **kw: None)

    result = CliRunner().invoke(cli_mod.cli, ["from", "ljubljana"])
    assert result.exit_code != 0
    assert "Remote export failed" in result.output
    assert not any(c[0] == "scp" for c in calls)


def test_from_reports_connection_failure(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    calls = []
    monkeypatch.setattr(cli_mod.subprocess, "run",
                        _fake_run_factory(calls, export_rc=255))
    monkeypatch.setattr(cli_mod, "cmd_import", lambda **kw: None)

    result = CliRunner().invoke(cli_mod.cli, ["from", "ljubljana"])
    assert result.exit_code != 0
    assert "Could not connect" in result.output
    assert not any(c[0] == "scp" for c in calls)


# --------------------------------------------------------------------------- #
# `commuter export --from-cwd`
# --------------------------------------------------------------------------- #

def _write_session(project_dir, session_id, ts):
    project_dir.mkdir(parents=True, exist_ok=True)
    entry = (
        '{"type": "user", "message": {"content": "hi"}, '
        f'"timestamp": "{ts}", "sessionId": "{session_id}", "cwd": "x"}}\n'
    )
    (project_dir / f"{session_id}.jsonl").write_text(entry)


def test_export_from_cwd_selects_session_for_directory(tmp_path, monkeypatch):
    projects = tmp_path / "projects"
    cwd = tmp_path / "cvic"
    cwd.mkdir()
    encoded = encode_project_path(str(cwd))
    _write_session(projects / encoded, "aaaaaaaa-0000-0000-0000-000000000001",
                   "2026-07-13T10:00:00Z")
    monkeypatch.setattr(cc, "PROJECTS_DIR", projects)
    monkeypatch.chdir(cwd)

    out = tmp_path / "bundle.json"
    result = CliRunner().invoke(cli_mod.cli, ["export", "--from-cwd", "-o", str(out)])
    assert result.exit_code == 0, result.output

    bundle = json.loads(out.read_text())
    assert bundle["session"]["id"] == "aaaaaaaa-0000-0000-0000-000000000001"
    assert bundle["session"]["project_dir"] == str(cwd)


def test_export_from_cwd_conflicts_with_latest(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    out = tmp_path / "bundle.json"
    result = CliRunner().invoke(
        cli_mod.cli, ["export", "--from-cwd", "--latest", "-o", str(out)]
    )
    assert result.exit_code != 0
    assert "cannot be combined" in result.output
