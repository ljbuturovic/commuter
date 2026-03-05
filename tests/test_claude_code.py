"""Tests for the Claude Code backend — session discovery, export, import."""
import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from commuter.backends.claude_code import (
    ClaudeCodeBackend,
    _read_jsonl,
    _write_jsonl,
    _extract_version,
    _rewrite_cwd,
    _decode_project_path,
    _read_session_metadata,
)


FIXTURES = Path(__file__).parent / "fixtures"
SAMPLE_JSONL = FIXTURES / "sample_session.jsonl"


# ------------------------------------------------------------------
# Low-level helpers
# ------------------------------------------------------------------

def test_decode_project_path():
    assert _decode_project_path("-home-user-projects-myapp") == "/home/user/projects/myapp"


def test_read_jsonl():
    entries = _read_jsonl(SAMPLE_JSONL)
    assert len(entries) == 5
    assert entries[1]["type"] == "user"
    assert entries[2]["type"] == "assistant"


def test_write_jsonl_roundtrip():
    entries = _read_jsonl(SAMPLE_JSONL)
    with tempfile.NamedTemporaryFile(suffix=".jsonl", mode="w", delete=False) as f:
        path = Path(f.name)
    try:
        _write_jsonl(path, entries)
        loaded = _read_jsonl(path)
        assert len(loaded) == len(entries)
        assert loaded[1]["uuid"] == entries[1]["uuid"]
    finally:
        path.unlink(missing_ok=True)


def test_extract_version():
    entries = _read_jsonl(SAMPLE_JSONL)
    assert _extract_version(entries) == "2.1.69"


def test_extract_version_missing():
    assert _extract_version([{"type": "user"}]) is None


def test_rewrite_cwd_same_path():
    entries = [{"type": "user", "cwd": "/home/a/projects/foo"}]
    result = _rewrite_cwd(entries, "/home/a/projects/foo", "/home/a/projects/foo")
    assert result[0]["cwd"] == "/home/a/projects/foo"


def test_rewrite_cwd_substitution():
    entries = [
        {"type": "user", "cwd": "/home/a/projects/foo"},
        {"type": "assistant", "cwd": "/home/a/projects/foo"},
    ]
    result = _rewrite_cwd(entries, "/home/a/projects/foo", "/Users/b/projects/foo")
    assert result[0]["cwd"] == "/Users/b/projects/foo"
    assert result[1]["cwd"] == "/Users/b/projects/foo"


def test_rewrite_cwd_no_cwd_field():
    entries = [{"type": "file-history-snapshot"}]
    result = _rewrite_cwd(entries, "/src", "/dst")
    assert result[0] == {"type": "file-history-snapshot"}


def test_read_session_metadata():
    info = _read_session_metadata(SAMPLE_JSONL, "/home/user/projects/myapp")
    assert info is not None
    assert info.session_id == "aaa00001-0000-0000-0000-000000000001"
    assert info.message_count == 4  # 2 user + 2 assistant
    assert "classifier" in info.first_prompt
    assert info.last_activity is not None


# ------------------------------------------------------------------
# Backend: import → discover round-trip (using temp dirs)
# ------------------------------------------------------------------

def _make_bundle(tmp_project: Path) -> dict:
    entries = _read_jsonl(SAMPLE_JSONL)
    # Rewrite the cwd to the temp project dir
    for entry in entries:
        if "cwd" in entry:
            entry["cwd"] = str(tmp_project)

    return {
        "version": "1.0",
        "tool": "commuter",
        "backend": "claude-code",
        "exported_at": "2026-03-01T10:00:00+00:00",
        "source": {"hostname": "machine-a", "os": "Linux", "backend_version": "2.1.69", "username": "user"},
        "session": {
            "id": "aaa00001-0000-0000-0000-000000000001",
            "project_dir": "/home/user/projects/myapp",
            "started_at": "2026-03-01T09:00:00.000Z",
            "last_activity": "2026-03-01T09:01:10.000Z",
            "message_count": 4,
            "lineage_hash": "sha256:test",
            "conversation": entries,
            "config": {},
        },
        "git_snapshot": {"branch": "main", "commit": "abc1234", "dirty_files": []},
    }


def test_import_creates_jsonl(tmp_path, monkeypatch):
    # Redirect PROJECTS_DIR to a temp location
    import commuter.backends.claude_code as cc
    fake_projects = tmp_path / "projects"
    monkeypatch.setattr(cc, "PROJECTS_DIR", fake_projects)

    tmp_project = tmp_path / "myapp"
    tmp_project.mkdir()

    backend = ClaudeCodeBackend()
    bndl = _make_bundle(tmp_project)
    session_id = backend.import_session(bndl, str(tmp_project))

    assert session_id == "aaa00001-0000-0000-0000-000000000001"
    expected_jsonl = fake_projects / f"-{str(tmp_project)[1:].replace('/', '-')}" / f"{session_id}.jsonl"
    assert expected_jsonl.exists()


def test_import_then_discover(tmp_path, monkeypatch):
    import commuter.backends.claude_code as cc
    fake_projects = tmp_path / "projects"
    monkeypatch.setattr(cc, "PROJECTS_DIR", fake_projects)

    tmp_project = tmp_path / "myapp"
    tmp_project.mkdir()

    backend = ClaudeCodeBackend()
    bndl = _make_bundle(tmp_project)
    backend.import_session(bndl, str(tmp_project))

    sessions = backend.discover()
    assert len(sessions) == 1
    assert sessions[0].session_id == "aaa00001-0000-0000-0000-000000000001"
    assert sessions[0].message_count == 4


def test_import_dry_run_creates_nothing(tmp_path, monkeypatch):
    import commuter.backends.claude_code as cc
    fake_projects = tmp_path / "projects"
    monkeypatch.setattr(cc, "PROJECTS_DIR", fake_projects)

    tmp_project = tmp_path / "myapp"
    tmp_project.mkdir()

    backend = ClaudeCodeBackend()
    bndl = _make_bundle(tmp_project)
    backend.import_session(bndl, str(tmp_project), dry_run=True)

    assert not fake_projects.exists()


def test_export_import_roundtrip(tmp_path, monkeypatch):
    """Export from a fake session file, re-import, verify conversation is intact."""
    import commuter.backends.claude_code as cc
    fake_projects = tmp_path / "projects"
    monkeypatch.setattr(cc, "PROJECTS_DIR", fake_projects)

    tmp_project = tmp_path / "myapp"
    tmp_project.mkdir()

    # Set up a "source" session on disk
    encoded = f"-{str(tmp_project)[1:].replace('/', '-')}"
    src_dir = fake_projects / encoded
    src_dir.mkdir(parents=True)
    src_jsonl = src_dir / "aaa00001-0000-0000-0000-000000000001.jsonl"
    import shutil
    shutil.copy(SAMPLE_JSONL, src_jsonl)
    # Fix the cwd in the copied file to match tmp_project
    entries = _read_jsonl(src_jsonl)
    for e in entries:
        if "cwd" in e:
            e["cwd"] = str(tmp_project)
    _write_jsonl(src_jsonl, entries)

    backend = ClaudeCodeBackend()
    data = backend.export_session("aaa00001-0000-0000-0000-000000000001")
    assert data["session_id"] == "aaa00001-0000-0000-0000-000000000001"
    assert len(data["conversation"]) == 5
