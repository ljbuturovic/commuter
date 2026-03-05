# commuter: Portable AI Coding Session Transfer

## Problem

Claude Code's Remote Control feature lets you view a session from another device, but the session always runs on the original host machine. If that machine sleeps, loses network, or you want to work with local files on a different machine, you're stuck.

**Goal:** Enable true session migration between machines that share a synced filesystem (via Git, Dropbox, Syncthing, etc.). Export a coding session on Machine A, import it on Machine B, and continue working with full local file access on Machine B.

The initial implementation targets Claude Code. The architecture should be tool-agnostic so that future backends can support Codex CLI, Gemini CLI, and other AI coding tools.

## User Experience Walkthrough

### First-time setup (once per machine pair)

```bash
# Install on BOTH machines
pip install commuter

# On each machine, tell it where your projects live
# Machine A (home desktop, Linux):
commuter config set path-map "/home/ljubomir/projects" "/Users/ljubomir/projects"

# Machine B (work laptop, macOS): same command
commuter config set path-map "/home/ljubomir/projects" "/Users/ljubomir/projects"
```

That's it for setup. The path map tells the tool how to translate paths between your machines. If your paths are identical on both machines, you can skip this step entirely.

### Daily workflow: Morning at home

You start working on your project at home:

```bash
cd ~/projects/trivertiy-ml
claude

# ... work with Claude Code for an hour, build a new feature,
# debug a test failure, get deep into a conversation ...
```

Time to leave for work. You want to continue this session on your office laptop.

```bash
# See what sessions are available
commuter list

  ID        PROJECT                    LAST ACTIVE    SUMMARY
  a1b2c3d   ~/projects/trivertiy-ml    2 min ago      "Debug failing test in classifier module"
  e4f5g6h   ~/projects/learnio         3 days ago     "Add new math lesson generator"

# Export the session you want to take with you
commuter export a1b2c3d -o ~/Dropbox/session.json

  ✓ Exported session a1b2c3d (47 messages, 12KB)
  ✓ Git snapshot: branch feature/new-classifier @ a1b2c3d (2 dirty files)
  ✓ Saved to /home/ljubomir/Dropbox/session.json
```

### Commute

Your session file syncs to Dropbox automatically. You can check on your phone that it arrived if you're anxious, but there's nothing to do.

### Arrive at office

```bash
# Dropbox has already synced the file. Import it:
commuter import ~/Dropbox/session.json

  ✓ Detected project: /home/ljubomir/projects/trivertiy-ml
  ✓ Mapped to local path: /Users/ljubomir/projects/trivertiy-ml
  ✓ Git check: branch feature/new-classifier @ a1b2c3d ✓ (matches export)
  ⚠ 2 dirty files in export not present locally — did you commit before leaving?
    - src/model.py
    - tests/test_model.py
  ✓ Restored conversation (47 messages)
  ✓ Restored project config (.claude/settings.json, CLAUDE.md)

  Launching Claude Code with restored session...
```

Claude Code opens. It has the full conversation context — it remembers everything you discussed, the files you edited, the decisions you made. But now it's running locally on your office laptop, reading and writing your local files.

You pick up exactly where you left off:

```
You: Let's continue with the test fix. What was the last error we saw?
Claude: We were debugging the assertion failure in test_classifier.py line 42...
```

### End of day: Back home (round-trip)

You worked all day at the office. Now you want to continue at home tonight.

```bash
# At office, leaving:
commuter export --latest -o ~/Dropbox/session.json

  ✓ Exported session a1b2c3d (112 messages, 28KB)
  ✓ Saved to /Users/ljubomir/Dropbox/session.json
```

Commute home. At your home desktop:

```bash
commuter import ~/Dropbox/session.json

  ✓ Detected project: /Users/ljubomir/projects/trivertiy-ml
  ✓ Mapped to local path: /home/ljubomir/projects/trivertiy-ml
  ✓ Session continuity: imported session is a continuation of local session a1b2c3d
    Local: 47 messages (exported 10h ago)
    Imported: 112 messages (last active 20 min ago)
  ✓ Replacing local session with imported version
  ✓ Restored conversation (112 messages)

  Launching Claude Code with restored session...
```

When the imported session is a **continuation** of an existing local session (the imported conversation starts with the same messages as the local one, just has more), the tool replaces it automatically without prompting. This is the expected round-trip case.

Use `--replace` to force replacement when continuity can't be auto-detected:

```bash
commuter import ~/Dropbox/session.json --replace
```

### Shortcut version (stretch goal)

If you configure a shared transfer directory:

```bash
commuter config set transfer-dir ~/Dropbox/.commuter/

# Then every day:
commuter push       # exports latest session to transfer dir
commuter pull       # imports from transfer dir, replaces if continuation
```

Push/pull defaults to `--replace` behavior since the entire point is frictionless round-trips.

### Error cases the user might hit

**Git state mismatch:**
```bash
commuter import ~/Dropbox/session.json

  ⚠ WARNING: Git state differs from export
    Export: feature/new-classifier @ a1b2c3d
    Local:  main @ f7g8h9i
  Continue anyway? Claude will have context from a different branch. [y/N]
```

**Project not found:**
```bash
commuter import ~/Dropbox/session.json

  ✗ Project path /home/ljubomir/projects/trivertiy-ml not found
  ✗ No path mapping matched
  Specify local project directory:
    commuter import ~/Dropbox/session.json --project-dir /path/to/project
```

**Unrelated session already exists (NOT a continuation):**
```bash
commuter import ~/Dropbox/session.json

  ⚠ A different session already exists for this project (last active 15 min ago)
    Local session has divergent conversation history — this is not a continuation.
  Overwrite local session with imported one? [y/N]
```

## Assumptions

- The project filesystem is already replicated across machines (Git, Dropbox, or similar). The tool does NOT handle file sync.
- Claude Code is installed on both machines.
- The user has the same Claude Code authentication on both machines.
- Paths to the project directory may differ between machines (e.g., `/home/user/projects/foo` on Linux vs `/Users/user/projects/foo` on macOS).

## Architecture

A standalone Python CLI tool distributed via PyPI. No dependency on Claude Code internals beyond the session storage format. The tool operates in three phases: discover, export, import.

The session discovery, export, and import logic should be isolated behind a **backend interface** so that future backends (Codex CLI, Gemini CLI, etc.) can be added without changing the CLI or bundle format. The initial implementation provides only the Claude Code backend.

## Core Features

### 1. Session Discovery

```bash
commuter list
```

- Discover and list all Claude Code sessions on the current machine.
- Show: session ID, project directory, last activity timestamp, conversation summary (first/last message preview).
- Research where Claude Code stores session data. Likely locations:
  - `~/.claude/` or `~/.config/claude-code/`
  - Project-local `.claude/` directory
  - Check both, document findings.

### 2. Session Export

```bash
commuter export [session-id] -o session-bundle.json
commuter export --latest -o session-bundle.json
```

Export a session into a portable JSON bundle containing:

- **Conversation history**: The full message log (user messages, assistant responses, tool calls and results).
- **Project path**: The original absolute path to the working directory.
- **Project config**: Contents of relevant config files (`.claude/settings.json`, `CLAUDE.md`, `.claude/commands/` if present).
- **Git state** (if applicable): Current branch, commit hash, dirty file list (as a reference snapshot, not the files themselves).
- **Environment metadata**: OS, Claude Code version, timestamp, hostname.
- **Session config**: Any session-specific settings (model, permissions, MCP server configs).
- **Lineage info**: A hash of the first N messages in the conversation, used to detect whether an imported session is a continuation of a local one (see Session Continuity below).

The bundle should be a single JSON file, human-readable, reasonably compact. Use gzip compression as an option for large sessions.

```bash
commuter export --latest -o session-bundle.json.gz --compress
```

### 3. Session Import

```bash
commuter import session-bundle.json [--project-dir /path/to/local/project]
```

- Reconstruct the session on the target machine.
- If `--project-dir` is not specified, attempt to auto-detect: check if the original path exists, then try common path substitutions (see Path Mapping below).
- Inject the conversation history so Claude Code can resume with full context.
- Restore project config files to the local `.claude/` directory (with confirmation prompt if files already exist).
- Validate that the local project state is compatible: warn if the git branch or commit differs from the export snapshot.
- Launch Claude Code with the restored session using `--resume` or `--continue` (determine which flag is appropriate).

**Flags:**
- `--replace`: Force replacement of an existing local session without prompting.
- `--no-launch`: Import the session but don't launch Claude Code.
- `--dry-run`: Show what would happen without making changes.

### 4. Session Continuity Detection

When importing, the tool checks whether a session for the same project already exists locally. If it does, it computes whether the imported session is a **continuation** of the local one:

- Compute a hash of the first N messages (e.g., first 10) in both the local and imported conversations.
- If the hashes match and the imported session has MORE messages, it's a continuation → replace automatically.
- If the hashes don't match, the sessions have diverged → prompt for confirmation (unless `--replace` is set).
- If no local session exists for that project → import directly, no prompt needed.

This makes the daily home → office → home round-trip seamless: no confirmation prompts, no flags needed.

### 5. Path Mapping

```bash
commuter config set path-map "/home/ljubomir/projects" "/Users/ljubomir/projects"
commuter config set path-map "/home/ljubomir/Dropbox" "/Users/ljubomir/Dropbox"
```

- Store path mappings in `~/.config/commuter/config.json`.
- Applied automatically during import to translate paths in the session bundle.
- Bidirectional: the tool infers direction based on which side matches the imported path.
- Support multiple mappings, applied in order of specificity (longest prefix first).

### 6. Session Transfer Shortcut (stretch goal)

```bash
# On source machine:
commuter push              # exports latest to configured transfer dir

# On target machine:
commuter pull              # imports from transfer dir, auto-replaces continuations
```

- Requires `transfer-dir` to be configured: `commuter config set transfer-dir ~/Dropbox/.commuter/`
- `push` exports the most recent session to `<transfer-dir>/pending/`.
- `pull` imports from `<transfer-dir>/pending/` and moves the bundle to `<transfer-dir>/history/` after successful import.
- `pull` defaults to `--replace` behavior for continuations.
- History directory provides an audit trail and rollback capability.

## CLI Design

- Built with `click` or `argparse` (prefer `click`).
- Colored terminal output using `rich` for session listings and status messages.
- Confirmation prompts before overwriting existing config or sessions (unless auto-detected as continuation).
- `--dry-run` flag on import to show what would be changed without doing it.
- `--verbose` / `-v` flag for debug output.
- `--quiet` / `-q` flag for script-friendly output.

## Session Bundle Schema

```json
{
  "version": "1.0",
  "tool": "commuter",
  "backend": "claude-code",
  "exported_at": "2026-03-03T10:30:00Z",
  "source": {
    "hostname": "home-desktop",
    "os": "Linux",
    "backend_version": "1.x.x",
    "username": "ljubomir"
  },
  "session": {
    "id": "abc123",
    "project_dir": "/home/ljubomir/projects/trivertiy-ml",
    "started_at": "2026-03-03T09:00:00Z",
    "last_activity": "2026-03-03T10:25:00Z",
    "message_count": 47,
    "lineage_hash": "sha256:abcdef1234...",
    "conversation": [
      // Full conversation history array
    ],
    "config": {
      "settings_json": {},
      "claude_md": "contents of CLAUDE.md",
      "commands": {}
    }
  },
  "git_snapshot": {
    "branch": "feature/new-classifier",
    "commit": "a1b2c3d",
    "dirty_files": ["src/model.py", "tests/test_model.py"]
  }
}
```

## Research Tasks (Do First)

Before writing code, investigate and document:

1. **Where does Claude Code store session/conversation data?** Check `~/.claude/`, `~/.config/claude-code/`, project `.claude/` dirs, and any SQLite databases or JSON files.
2. **What format is the conversation history in?** Need to understand the schema to export/import it correctly.
3. **What CLI flags does Claude Code support for resuming sessions?** Test `--resume`, `--continue`, and any other relevant flags. Determine if there's a way to inject conversation history programmatically.
4. **Is the session data self-contained or does it reference external state?** (e.g., API-side session IDs that can't be transferred)

If Claude Code stores sessions server-side and there's no local conversation log, the approach needs to change: we'd capture the conversation via a wrapper/proxy instead. Document findings before proceeding with implementation.

## Tech Stack

- Python 3.10+
- `click` for CLI
- `rich` for terminal formatting
- No other heavy dependencies
- Standard library for JSON, gzip, pathlib, hashlib, etc.

## Distribution

- Package name: `commuter`
- Published to PyPI
- Installable via: `pip install commuter`
- Entry point: `commuter` command
- License: MIT

## Project Structure

```
commuter/
├── pyproject.toml
├── README.md
├── LICENSE
├── src/
│   └── commuter/
│       ├── __init__.py
│       ├── cli.py              # Click CLI entry point
│       ├── config.py           # User config management
│       ├── bundle.py           # Bundle schema, validation, versioning
│       ├── pathmap.py          # Path mapping config and translation
│       ├── lineage.py          # Session continuity detection
│       ├── git_utils.py        # Git state snapshot
│       └── backends/
│           ├── __init__.py     # Backend interface / base class
│           └── claude_code.py  # Claude Code: discover, export, import
├── tests/
│   ├── test_cli.py
│   ├── test_bundle.py
│   ├── test_pathmap.py
│   ├── test_lineage.py
│   ├── test_claude_code.py
│   └── fixtures/               # Sample session data for testing
└── .claude/
    └── CLAUDE.md               # This file, for Claude Code context
```

## Testing

- Use `pytest`.
- Mock Claude Code session data in fixtures (based on findings from Research Tasks).
- Test path mapping with Linux ↔ macOS path patterns.
- Test path mapping bidirectionality (A→B and B→A with same config).
- Test git snapshot validation (matching vs. diverged states).
- Test bundle schema validation and version compatibility.
- Test export → import round-trip preserves all data.
- Test session continuity detection: continuation (auto-replace), divergence (prompt), no existing session (direct import).
- Test push/pull with mock transfer directory.

## Out of Scope (for now)

- File synchronization between machines (user's responsibility).
- Multi-user session sharing.
- Running process migration (only conversation + config state).
- MCP server auto-configuration on the target machine (document what MCP servers were active; user sets them up).
- Non-Claude-Code backends (architecture supports them; implementation is future work).

## Success Criteria

1. Export a session on Machine A where I've been working for 30+ minutes with Claude Code.
2. Import it on Machine B (which has the same project via Git/Dropbox).
3. Claude Code on Machine B has full conversation context and continues working seamlessly, with local file access on Machine B.
4. Export from Machine B at end of day, import back on Machine A — round-trip works without prompts.
5. The whole transfer takes under 30 seconds.
