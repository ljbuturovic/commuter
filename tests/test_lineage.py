import pytest
from commuter.lineage import compute, is_continuation


def _make_conv(prompts: list[str]) -> list[dict]:
    """Build a minimal conversation list from a list of user prompts."""
    entries = []
    for i, prompt in enumerate(prompts):
        entries.append({
            "type": "user",
            "uuid": f"uuid-{i:04d}",
            "message": {"role": "user", "content": prompt},
        })
        entries.append({
            "type": "assistant",
            "uuid": f"uuid-{i:04d}-a",
            "message": {"role": "assistant", "content": [{"type": "text", "text": f"Reply {i}"}]},
        })
    return entries


def test_compute_same_input_same_hash():
    conv = _make_conv(["Hello", "What is the issue?"])
    assert compute(conv) == compute(conv)


def test_compute_different_input_different_hash():
    conv1 = _make_conv(["Hello"])
    conv2 = _make_conv(["Goodbye"])
    assert compute(conv1) != compute(conv2)


def test_compute_hash_prefix():
    conv = _make_conv(["Hello"])
    h = compute(conv)
    assert h.startswith("sha256:")
    assert len(h) == len("sha256:") + 64


def test_is_continuation_true():
    local = _make_conv(["msg1", "msg2", "msg3"])
    imported = _make_conv(["msg1", "msg2", "msg3", "msg4", "msg5"])
    assert is_continuation(local, imported) is True


def test_is_continuation_false_diverged():
    local = _make_conv(["msg1", "msg2", "msg3"])
    imported = _make_conv(["msg1", "different", "msg3", "msg4"])
    assert is_continuation(local, imported) is False


def test_is_continuation_false_same_length():
    conv = _make_conv(["msg1", "msg2"])
    assert is_continuation(conv, conv) is False


def test_is_continuation_false_imported_shorter():
    local = _make_conv(["msg1", "msg2", "msg3"])
    imported = _make_conv(["msg1", "msg2"])
    assert is_continuation(local, imported) is False


def test_is_continuation_uses_only_first_n(monkeypatch):
    import commuter.lineage as lineage_mod
    monkeypatch.setattr(lineage_mod, "N_MESSAGES", 2)

    # Even if messages beyond N differ, continuation should be detected
    local = _make_conv(["msg1", "msg2"])
    imported = _make_conv(["msg1", "msg2", "msg3"])
    assert is_continuation(local, imported) is True
