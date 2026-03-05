from __future__ import annotations

import hashlib
import json

# Number of first user messages to include in the lineage hash
N_MESSAGES = 10


def compute(conversation: list[dict]) -> str:
    """Compute a lineage hash from the first N user messages in a conversation."""
    user_messages = [e for e in conversation if e.get("type") == "user"][:N_MESSAGES]
    canonical = json.dumps(
        [{"content": m["message"]["content"]} for m in user_messages],
        sort_keys=True,
        ensure_ascii=False,
    )
    return "sha256:" + hashlib.sha256(canonical.encode()).hexdigest()


def is_continuation(local_conv: list[dict], imported_conv: list[dict]) -> bool:
    """Return True if imported is a strict continuation of local.

    A continuation means: same starting messages, imported has more messages.
    Compares the same number of leading user messages from both sides.
    """
    if len(imported_conv) <= len(local_conv):
        return False

    local_users = [e for e in local_conv if e.get("type") == "user"]
    imported_users = [e for e in imported_conv if e.get("type") == "user"]

    n = min(N_MESSAGES, len(local_users))
    if n == 0:
        return False

    def _hash_n(msgs: list[dict], count: int) -> str:
        canonical = json.dumps(
            [{"content": m["message"]["content"]} for m in msgs[:count]],
            sort_keys=True,
            ensure_ascii=False,
        )
        return hashlib.sha256(canonical.encode()).hexdigest()

    return _hash_n(local_users, n) == _hash_n(imported_users, n)
