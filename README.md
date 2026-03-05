# 🚂 commuter

**Take your AI coding sessions to work and back.**

Commuter transfers Claude Code sessions between machines. Start a session on your home desktop, export it, commute, import it on your office laptop — and pick up exactly where you left off, with full local file access.

No cloud dependency. No VPN. No SSH tunnels. Just a JSON file in your Dropbox.

```bash
pipx install commuter
```

---

## Why?

Claude Code's [Remote Control](https://code.claude.com/docs/en/remote-control) lets you *view* a session from your phone — but the session runs on the original machine. If that machine sleeps, loses Wi-Fi, or you need local file access on a different computer, you're out of luck.

Commuter solves this by **migrating the session itself** — conversation history, project config, everything — so the AI picks up right where you left off on the new machine.

## The daily workflow

**Morning at home:**

```bash
cd ~/projects/my-app
claude
# ... work for an hour ...

# Time to leave
commuter export --latest -o ~/Dropbox/session.json

  ✓ Exported session a1b2c3d (47 messages, 12KB)
  ✓ Git snapshot: branch feature/auth @ a1b2c3d
  ✓ Saved to ~/Dropbox/session.json
```

**Arrive at office:**

```bash
commuter import ~/Dropbox/session.json

  ✓ Mapped to local path: /Users/you/projects/my-app
  ✓ Git check: feature/auth @ a1b2c3d ✓
  ✓ Restored conversation (47 messages)

  Launching Claude Code with restored session...
```

Claude remembers everything. You continue:

```
You: Let's continue with the auth module. Where were we?
Claude: We were adding OAuth2 support to the login endpoint...
```

**End of day — back home:**

```bash
commuter export --latest -o ~/Dropbox/session.json
# commute home...
commuter import ~/Dropbox/session.json

  ✓ Session continuity detected: 47 → 112 messages
  ✓ Replacing local session with imported version
  Launching Claude Code with restored session...
```

Round-trips are seamless. Commuter detects that the imported session is a continuation of the local one and replaces it automatically — no prompts, no flags.

## Setup

### Install

```bash
pipx install commuter
```

Or if you prefer pip: `pip install commuter`

### Path mapping (if your machines have different paths)

```bash
# Tell commuter how paths map between your machines
commuter config set path-map "/home/you/projects" "/Users/you/projects"
```

If both machines use the same paths, skip this step.

### Prerequisites

- Python 3.10+
- [pipx](https://pipx.pypa.io/) (recommended) or pip
- Claude Code installed on both machines
- A shared filesystem between machines (Git, Dropbox, Syncthing, Google Drive, USB stick — anything that moves a file from A to B)

## Commands

| Command | Description |
|---------|-------------|
| `commuter list` | Show all Claude Code sessions on this machine |
| `commuter export <id> -o file.json` | Export a session to a portable bundle |
| `commuter export --latest -o file.json` | Export the most recent session |
| `commuter import file.json` | Import a session and launch Claude Code |
| `commuter config set path-map "A" "B"` | Set up path translation between machines |
| `commuter push` | Export current directory's session to transfer dir |
| `commuter pull` | Import all pending sessions from transfer dir |

### Import flags

| Flag | Description |
|------|-------------|
| `--project-dir PATH` | Override auto-detected project directory |
| `--replace` | Force-replace existing session without prompting |
| `--no-launch` | Import without launching Claude Code |
| `--dry-run` | Preview what would happen |

### Push / pull shortcut

For an even faster workflow, configure a shared transfer directory once:

```bash
commuter config set transfer-dir ~/Dropbox/.commuter/
```

Then, from each project you want to transfer:

```bash
cd ~/projects/my-app  &&  commuter push
cd ~/projects/other   &&  commuter push
```

`push` exports the session for the **current directory**. Run it once per project you're taking with you.

On the other machine, a single `pull` picks up everything:

```bash
commuter pull

  ✓ Restored conversation (47 messages)    # my-app
  ✓ Restored conversation (31 messages)    # other

  Imported 2 session(s). To resume:
    cd ~/projects/my-app  && claude --continue
    cd ~/projects/other   && claude --continue
```

## How it works

Commuter exports a session as a single JSON bundle containing:

- Full conversation history (messages, tool calls, results)
- Project directory path
- Project config (`.claude/settings.json`, `CLAUDE.md`)
- Git state snapshot (branch, commit, dirty files)
- Environment metadata

On import, it restores the session into Claude Code's local storage, translates paths if needed, validates the git state, and launches Claude Code with the restored conversation.

### Session continuity

Commuter tracks session lineage by hashing the first N messages. When you import a session that's a continuation of one already on this machine (same beginning, more messages), it replaces automatically. Divergent sessions prompt for confirmation.

This makes the home → office → home round-trip work without friction.

### Architecture

```
commuter/
└── backends/
    └── claude_code.py    # Claude Code backend
    └── (future: codex, gemini, etc.)
```

The Claude Code-specific logic is isolated behind a backend interface. Adding support for other AI coding tools (Codex CLI, Gemini CLI) is a matter of writing a new backend — the CLI and bundle format stay the same.

## Requirements

Commuter assumes **your project files are already synced** between machines. It transfers the *session* (conversation + config), not the *codebase*. Use Git, Dropbox, Syncthing, or whatever you normally use to keep your code in sync.

## FAQ

**Does my home machine need to stay on?**
No. That's the whole point. Unlike Remote Control, commuter migrates the session entirely to the new machine. Your home desktop can sleep, shut down, or catch fire (please don't) — the session continues independently on the target machine.

**What if I forget to commit before leaving?**
Commuter warns you. It snapshots the git state on export and checks it on import. If there are dirty files that aren't present on the target machine, you'll see a warning. The session still imports — you just might need to sync those files.

**What if my git branches are different on the two machines?**
Commuter warns you and asks for confirmation. Claude will have context from the original branch, which might be confusing if you're now on a different one.

**Can I use this without Dropbox?**
Yes. Dropbox is just an example. You can use any method to move the JSON file between machines: a USB drive, `scp`, email it to yourself, AirDrop, carrier pigeon with a flash drive. Commuter doesn't care how the file gets there.

**Does it work with Codex CLI / Gemini CLI / Cursor?**
Not yet. The architecture supports multiple backends, but only Claude Code is implemented today. PRs welcome.

## Contributing

Contributions welcome. The most impactful areas:

- **New backends** — add support for Codex CLI, Gemini CLI, or other tools
- **Bug reports** — especially around edge cases in session discovery and import
- **Platform testing** — tested on Linux ↔ macOS; Windows support is untested

## Credits

Conceived and directed by Ljubomir Buturovic. Built with [Claude Code](https://code.claude.com). Jokes by Claude

## License

MIT
