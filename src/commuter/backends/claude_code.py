from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from . import Backend, SessionInfo
from ..pathmap import encode_project_path, translate

CLAUDE_DIR = Path.home() / ".claude"
PROJECTS_DIR = CLAUDE_DIR / "projects"
BACKEND_NAME = "claude-code"


class ClaudeCodeBackend(Backend):
    name = BACKEND_NAME

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------

    def discover(self) -> list[SessionInfo]:
        sessions: list[SessionInfo] = []

        if not PROJECTS_DIR.exists():
            return sessions

        for project_dir in PROJECTS_DIR.iterdir():
            if not project_dir.is_dir():
                continue

            decoded_path = _decode_project_path(project_dir.name)

            # Build a lookup of index metadata keyed by session_id.
            # The index is supplementary (provides summaries) but NOT authoritative —
            # it can be stale. We always scan *.jsonl files directly.
            index = _read_sessions_index(project_dir)
            index_meta: dict[str, dict] = {}
            if index:
                for entry in index.get("entries", []):
                    index_meta[entry["sessionId"]] = entry

            for jsonl_path in project_dir.glob("*.jsonl"):
                info = _read_session_metadata(jsonl_path, decoded_path)
                if not info:
                    continue
                # Enrich with index metadata if available
                meta = index_meta.get(info.session_id)
                if meta:
                    info.summary = meta.get("summary", "")
                    info.first_prompt = meta.get("firstPrompt", "") or info.first_prompt
                    info.project_dir = meta.get("projectPath", "") or info.project_dir
                sessions.append(info)

        sessions.sort(key=lambda s: s.last_activity or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
        return sessions

    def find_session(self, session_id: str) -> SessionInfo | None:
        """Find a session by full or partial UUID."""
        for s in self.discover():
            if s.session_id == session_id or s.session_id.startswith(session_id):
                return s
        return None

    def latest_session(self) -> SessionInfo | None:
        sessions = self.discover()
        return sessions[0] if sessions else None

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------

    def export_session(self, session_id: str) -> dict:
        info = self.find_session(session_id)
        if not info:
            raise ValueError(f"Session not found: {session_id}")

        conversation = _read_jsonl(info.jsonl_path)
        backend_version = _extract_version(conversation)
        project_config = _read_project_config(info.project_dir)

        return {
            "session_id": info.session_id,
            "project_dir": info.project_dir,
            "conversation": conversation,
            "config": project_config,
            "backend_version": backend_version,
        }

    # ------------------------------------------------------------------
    # Import
    # ------------------------------------------------------------------

    def import_session(
        self,
        bundle: dict,
        project_dir: str,
        *,
        dry_run: bool = False,
    ) -> str:
        session = bundle["session"]
        session_id = session["id"]
        conversation = session["conversation"]

        # Rewrite cwd fields using path mapping so historical paths point locally
        src_project_dir = session["project_dir"]
        conversation = _rewrite_cwd(conversation, src_project_dir, project_dir)

        encoded = encode_project_path(project_dir)
        target_dir = PROJECTS_DIR / encoded
        target_jsonl = target_dir / f"{session_id}.jsonl"

        if dry_run:
            return session_id

        target_dir.mkdir(parents=True, exist_ok=True)
        target_dir.chmod(0o700)

        _write_jsonl(target_jsonl, conversation)
        target_jsonl.chmod(0o600)

        _update_sessions_index(target_dir, session, project_dir, target_jsonl)

        # Restore project config files
        project_config = session.get("config", {})
        _restore_project_config(project_dir, project_config, dry_run=dry_run)

        return session_id

    # ------------------------------------------------------------------
    # Launch
    # ------------------------------------------------------------------

    def launch(self, session_id: str, project_dir: str) -> None:
        os.execvp("claude", ["claude", "--resume", session_id])


# ------------------------------------------------------------------
# Internal helpers
# ------------------------------------------------------------------

def _decode_project_path(encoded: str) -> str:
    """Convert -home-user-projects-foo back to /home/user/projects/foo."""
    # The encoding is: each '/' in the original path was replaced by '-'
    # The leading '/' became a leading '-'
    # So we just replace '-' back to '/' — but only word boundaries, not dashes inside names.
    # Actually the encoding is unambiguous only if we know the original was an absolute path.
    # We restore by replacing '-' with '/' for the leading char, then splitting on '-'.
    # The real encoding is simply str.replace('/', '-'), so we reverse with replace('-', '/').
    # This is lossy for paths that contain '-', but it's what Claude Code does.
    return encoded.replace("-", "/")


def _read_sessions_index(project_dir: Path) -> dict | None:
    index_file = project_dir / "sessions-index.json"
    if not index_file.exists():
        return None
    try:
        return json.loads(index_file.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def _read_session_metadata(jsonl_path: Path, project_dir: str) -> SessionInfo | None:
    """Read just enough of a JSONL file to build a SessionInfo."""
    session_id = jsonl_path.stem  # fallback; overridden by entry content below
    first_prompt = ""
    last_ts: datetime | None = None
    message_count = 0
    version: str | None = None

    try:
        with open(jsonl_path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue

                # Prefer sessionId from entry content over filename stem
                if entry.get("sessionId") and session_id == jsonl_path.stem:
                    session_id = entry["sessionId"]

                etype = entry.get("type")
                if etype in ("user", "assistant"):
                    message_count += 1
                    if etype == "user" and not first_prompt:
                        content = entry.get("message", {}).get("content", "")
                        if isinstance(content, str):
                            first_prompt = content[:120]
                        elif isinstance(content, list):
                            for block in content:
                                if isinstance(block, dict) and block.get("type") == "text":
                                    first_prompt = block.get("text", "")[:120]
                                    break

                ts_str = entry.get("timestamp")
                if ts_str:
                    try:
                        ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                        if last_ts is None or ts > last_ts:
                            last_ts = ts
                    except ValueError:
                        pass

                if not version and entry.get("version"):
                    version = entry["version"]
                    proj = entry.get("cwd", project_dir)
    except OSError:
        return None

    if message_count == 0:
        return None

    return SessionInfo(
        session_id=session_id,
        project_dir=proj if "proj" in dir() else project_dir,
        last_activity=last_ts,
        message_count=message_count,
        first_prompt=first_prompt,
        jsonl_path=jsonl_path,
    )


def _read_jsonl(path: Path) -> list[dict]:
    entries = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return entries


def _write_jsonl(path: Path, entries: list[dict]) -> None:
    with open(path, "w") as f:
        for entry in entries:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _extract_version(conversation: list[dict]) -> str | None:
    for entry in conversation:
        v = entry.get("version")
        if v:
            return v
    return None


def _read_project_config(project_dir: str) -> dict:
    """Read .claude/settings.json, CLAUDE.md, and .claude/commands/ from a project."""
    root = Path(project_dir)
    config: dict = {}

    settings = root / ".claude" / "settings.json"
    if settings.exists():
        try:
            config["settings_json"] = json.loads(settings.read_text())
        except (json.JSONDecodeError, OSError):
            pass

    claude_md = root / "CLAUDE.md"
    if claude_md.exists():
        try:
            config["claude_md"] = claude_md.read_text()
        except OSError:
            pass

    commands_dir = root / ".claude" / "commands"
    if commands_dir.is_dir():
        commands: dict[str, str] = {}
        for cmd_file in commands_dir.glob("*.md"):
            try:
                commands[cmd_file.name] = cmd_file.read_text()
            except OSError:
                pass
        if commands:
            config["commands"] = commands

    return config


def _restore_project_config(project_dir: str, config: dict, *, dry_run: bool) -> None:
    """Write project config files from a bundle's config dict."""
    if not config or dry_run:
        return

    root = Path(project_dir)
    claude_dir = root / ".claude"

    if "settings_json" in config:
        claude_dir.mkdir(exist_ok=True)
        (claude_dir / "settings.json").write_text(
            json.dumps(config["settings_json"], indent=2) + "\n"
        )

    if "claude_md" in config:
        (root / "CLAUDE.md").write_text(config["claude_md"])

    if "commands" in config:
        commands_dir = claude_dir / "commands"
        commands_dir.mkdir(parents=True, exist_ok=True)
        for name, content in config["commands"].items():
            (commands_dir / name).write_text(content)


def _rewrite_cwd(conversation: list[dict], src_dir: str, dst_dir: str) -> list[dict]:
    """Rewrite cwd fields in conversation entries from src_dir to dst_dir."""
    if src_dir == dst_dir:
        return conversation

    rewritten = []
    for entry in conversation:
        cwd = entry.get("cwd")
        if cwd:
            new_cwd = translate(cwd)
            # If translation via configured maps didn't change it, do direct substitution
            if new_cwd == cwd and cwd.startswith(src_dir):
                new_cwd = dst_dir + cwd[len(src_dir):]
            if new_cwd != cwd:
                entry = {**entry, "cwd": new_cwd}
        rewritten.append(entry)
    return rewritten


def _update_sessions_index(
    project_dir: Path,
    session: dict,
    local_project_path: str,
    jsonl_path: Path,
) -> None:
    """Update or create sessions-index.json after an import."""
    index_file = project_dir / "sessions-index.json"

    if index_file.exists():
        try:
            index = json.loads(index_file.read_text())
        except (json.JSONDecodeError, OSError):
            index = {"version": 1, "entries": []}
    else:
        index = {"version": 1, "entries": []}

    session_id = session["id"]
    conversation = session.get("conversation", [])

    # Remove any existing entry for this session_id
    index["entries"] = [e for e in index["entries"] if e.get("sessionId") != session_id]

    first_prompt = ""
    for entry in conversation:
        if entry.get("type") == "user":
            content = entry.get("message", {}).get("content", "")
            if isinstance(content, str):
                first_prompt = content[:200]
            elif isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        first_prompt = block.get("text", "")[:200]
                        break
            if first_prompt:
                break

    stat = jsonl_path.stat()
    index["entries"].append({
        "sessionId": session_id,
        "fullPath": str(jsonl_path),
        "fileMtime": int(stat.st_mtime * 1000),
        "firstPrompt": first_prompt or "No prompt",
        "summary": session.get("lineage_hash", ""),
        "messageCount": session.get("message_count", len(conversation)),
        "created": session.get("started_at", ""),
        "modified": session.get("last_activity", ""),
        "gitBranch": "",
        "projectPath": local_project_path,
        "isSidechain": False,
    })

    index["originalPath"] = local_project_path
    index_file.write_text(json.dumps(index, indent=2) + "\n")


def _parse_ts(ts_str: str | None) -> datetime | None:
    if not ts_str:
        return None
    try:
        return datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
    except ValueError:
        return None
