import gzip
import json
import tempfile
from pathlib import Path

import pytest

from commuter import bundle as bundle_mod


SAMPLE_CONV = [
    {"type": "user", "uuid": "u1", "timestamp": "2026-03-01T09:00:00.000Z",
     "message": {"role": "user", "content": "Hello"}},
    {"type": "assistant", "uuid": "a1", "timestamp": "2026-03-01T09:00:05.000Z",
     "message": {"role": "assistant", "content": [{"type": "text", "text": "Hi"}]}},
]


def _make_bundle(**kwargs):
    defaults = dict(
        backend="claude-code",
        session_id="test-session-id",
        project_dir="/home/user/projects/myapp",
        conversation=SAMPLE_CONV,
        config={},
        git_snapshot={"branch": "main", "commit": "abc1234", "dirty_files": []},
        lineage_hash="sha256:abc",
        backend_version="2.1.69",
    )
    defaults.update(kwargs)
    return bundle_mod.create(**defaults)


def test_create_structure():
    b = _make_bundle()
    assert b["tool"] == "commuter"
    assert b["version"] == "1.0"
    assert b["backend"] == "claude-code"
    assert "exported_at" in b
    assert "source" in b
    assert b["session"]["id"] == "test-session-id"
    assert b["session"]["project_dir"] == "/home/user/projects/myapp"
    assert b["session"]["message_count"] == 2
    assert b["session"]["lineage_hash"] == "sha256:abc"
    assert b["session"]["conversation"] == SAMPLE_CONV


def test_create_timestamps():
    b = _make_bundle()
    assert b["session"]["started_at"] == "2026-03-01T09:00:00.000Z"
    assert b["session"]["last_activity"] == "2026-03-01T09:00:05.000Z"


def test_write_and_read_json():
    b = _make_bundle()
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        path = Path(f.name)
    try:
        bundle_mod.write(b, path)
        loaded = bundle_mod.read(path)
        assert loaded["session"]["id"] == "test-session-id"
        assert loaded["session"]["conversation"] == SAMPLE_CONV
    finally:
        path.unlink(missing_ok=True)


def test_write_and_read_gzip():
    b = _make_bundle()
    with tempfile.NamedTemporaryFile(suffix=".json.gz", delete=False) as f:
        path = Path(f.name)
    try:
        bundle_mod.write(b, path, compress=True)
        assert _is_gzip(path)
        loaded = bundle_mod.read(path)
        assert loaded["session"]["id"] == "test-session-id"
    finally:
        path.unlink(missing_ok=True)


def test_validate_valid():
    b = _make_bundle()
    assert bundle_mod.validate(b) == []


def test_validate_wrong_tool():
    b = _make_bundle()
    b["tool"] = "other"
    errors = bundle_mod.validate(b)
    assert any("Not a commuter bundle" in e for e in errors)


def test_validate_missing_session():
    b = _make_bundle()
    del b["session"]
    errors = bundle_mod.validate(b)
    assert any("session" in e.lower() for e in errors)


def test_validate_missing_conversation():
    b = _make_bundle()
    del b["session"]["conversation"]
    errors = bundle_mod.validate(b)
    assert any("conversation" in e.lower() for e in errors)


def test_roundtrip_preserves_all_data():
    b = _make_bundle(
        config={"claude_md": "# Instructions\nBe helpful."},
        git_snapshot={"branch": "feature/x", "commit": "deadbeef", "dirty_files": ["src/x.py"]},
    )
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        path = Path(f.name)
    try:
        bundle_mod.write(b, path)
        loaded = bundle_mod.read(path)
        assert loaded["git_snapshot"]["branch"] == "feature/x"
        assert loaded["git_snapshot"]["dirty_files"] == ["src/x.py"]
        assert loaded["session"]["config"]["claude_md"] == "# Instructions\nBe helpful."
    finally:
        path.unlink(missing_ok=True)


def _is_gzip(path: Path) -> bool:
    with open(path, "rb") as f:
        return f.read(2) == b"\x1f\x8b"
