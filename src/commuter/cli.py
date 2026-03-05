from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table
from rich import box

from . import bundle as bundle_mod
from . import config as config_mod
from . import git_utils
from . import lineage as lineage_mod
from . import pathmap
from .backends.claude_code import ClaudeCodeBackend

console = Console()
err_console = Console(stderr=True)

BACKEND = ClaudeCodeBackend()


# ---------------------------------------------------------------------------
# Root group
# ---------------------------------------------------------------------------

@click.group()
@click.version_option(package_name="commuter")
def cli():
    """Portable AI coding session transfer between machines."""


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------

@cli.command("list")
def cmd_list():
    """List all Claude Code sessions on this machine."""
    sessions = BACKEND.discover()

    if not sessions:
        console.print("[yellow]No sessions found.[/yellow]")
        return

    table = Table(box=box.SIMPLE_HEAD, show_edge=False)
    table.add_column("ID", style="cyan", no_wrap=True)
    table.add_column("PROJECT", style="", max_width=40)
    table.add_column("LAST ACTIVE", style="green", no_wrap=True)
    table.add_column("MSGS", justify="right", style="dim")
    table.add_column("SUMMARY / FIRST PROMPT", style="dim")

    now = datetime.now(timezone.utc)

    for s in sessions:
        short_id = s.session_id[:7]
        proj = _shorten_path(s.project_dir)
        age = _relative_time(s.last_activity, now) if s.last_activity else "unknown"
        msgs = str(s.message_count)
        summary = s.summary or s.first_prompt or ""
        if len(summary) > 60:
            summary = summary[:57] + "..."
        table.add_row(short_id, proj, age, msgs, summary)

    console.print(table)


# ---------------------------------------------------------------------------
# export
# ---------------------------------------------------------------------------

@cli.command("export")
@click.argument("session_id", required=False)
@click.option("-o", "--output", required=True, type=click.Path(), help="Output bundle file path")
@click.option("--latest", is_flag=True, help="Export the most recently active session")
@click.option("--compress", is_flag=True, help="Gzip compress the output bundle")
@click.option("-v", "--verbose", is_flag=True)
def cmd_export(session_id, output, latest, compress, verbose):
    """Export a session to a portable bundle file."""
    if not session_id and not latest:
        # Default to latest
        latest = True

    if latest:
        info = BACKEND.latest_session()
        if not info:
            err_console.print("[red]No sessions found.[/red]")
            sys.exit(1)
        session_id = info.session_id
        if verbose:
            console.print(f"  Using latest session: {session_id[:7]}")

    console.print(f"  Exporting session [cyan]{session_id[:7]}[/cyan]...")

    try:
        data = BACKEND.export_session(session_id)
    except ValueError as e:
        err_console.print(f"[red]✗ {e}[/red]")
        sys.exit(1)

    conversation = data["conversation"]
    lineage_hash = lineage_mod.compute(conversation)
    git_snapshot = git_utils.get_snapshot(data["project_dir"])

    bndl = bundle_mod.create(
        backend=BACKEND.name,
        session_id=data["session_id"],
        project_dir=data["project_dir"],
        conversation=conversation,
        config=data["config"],
        git_snapshot=git_snapshot,
        lineage_hash=lineage_hash,
        backend_version=data.get("backend_version"),
    )

    output_path = Path(output)
    bundle_mod.write(bndl, output_path, compress=compress)

    msg_count = bndl["session"]["message_count"]
    size_kb = output_path.stat().st_size // 1024
    console.print(f"  [green]✓[/green] Exported session [cyan]{session_id[:7]}[/cyan] ({msg_count} messages, {size_kb}KB)")

    if git_snapshot.get("branch"):
        dirty = git_snapshot.get("dirty_files", [])
        dirty_note = f" ({len(dirty)} dirty files)" if dirty else ""
        console.print(
            f"  [green]✓[/green] Git snapshot: branch [bold]{git_snapshot['branch']}[/bold]"
            f" @ {git_snapshot['commit'][:7] if git_snapshot.get('commit') else 'unknown'}"
            + dirty_note
        )

    console.print(f"  [green]✓[/green] Saved to [bold]{output_path.resolve()}[/bold]")


# ---------------------------------------------------------------------------
# import
# ---------------------------------------------------------------------------

@cli.command("import")
@click.argument("bundle_file", type=click.Path(exists=True))
@click.option("--project-dir", type=click.Path(), help="Override local project directory")
@click.option("--replace", is_flag=True, help="Force replace existing session without prompting")
@click.option("--no-launch", is_flag=True, help="Import but do not launch Claude Code")
@click.option("--dry-run", is_flag=True, help="Show what would happen without making changes")
@click.option("-v", "--verbose", is_flag=True)
def cmd_import(bundle_file, project_dir, replace, no_launch, dry_run, verbose):
    """Import a session bundle and resume it in Claude Code."""
    if dry_run:
        console.print("  [yellow]Dry run — no changes will be made.[/yellow]")

    # Load and validate bundle
    try:
        bndl = bundle_mod.read(bundle_file)
    except Exception as e:
        err_console.print(f"[red]✗ Could not read bundle: {e}[/red]")
        sys.exit(1)

    errors = bundle_mod.validate(bndl)
    if errors:
        for e in errors:
            err_console.print(f"[red]✗ {e}[/red]")
        sys.exit(1)

    session = bndl["session"]
    src_project_dir = session["project_dir"]

    # Resolve local project directory
    if not project_dir:
        project_dir = _resolve_project_dir(src_project_dir)

    if not project_dir:
        err_console.print(f"[red]✗ Project path {src_project_dir} not found[/red]")
        err_console.print("[red]✗ No path mapping matched[/red]")
        err_console.print(
            f"  Specify local project directory:\n"
            f"    commuter import {bundle_file} --project-dir /path/to/project"
        )
        sys.exit(1)

    if not Path(project_dir).exists():
        err_console.print(f"[red]✗ Project directory not found: {project_dir}[/red]")
        sys.exit(1)

    mapped = pathmap.translate(src_project_dir)
    if mapped != src_project_dir:
        console.print(f"  [green]✓[/green] Detected project: {src_project_dir}")
        console.print(f"  [green]✓[/green] Mapped to local path: {project_dir}")
    else:
        console.print(f"  [green]✓[/green] Detected project: {project_dir}")

    # Git state check
    git_snapshot = bndl.get("git_snapshot", {})
    if git_snapshot.get("branch"):
        current_git = git_utils.get_snapshot(project_dir)
        matches, warnings = git_utils.compare(current_git, git_snapshot)
        if matches:
            console.print(
                f"  [green]✓[/green] Git check: branch [bold]{git_snapshot['branch']}[/bold]"
                f" @ {git_snapshot['commit'][:7] if git_snapshot.get('commit') else 'unknown'} ✓ (matches export)"
            )
        else:
            console.print(f"  [yellow]⚠[/yellow] WARNING: Git state differs from export")
            for w in warnings:
                console.print(f"    {w}")
            if not replace and not dry_run:
                if not click.confirm("  Continue anyway? Claude will have context from a different state.", default=False):
                    sys.exit(0)

    # Check dirty files from export
    dirty = git_snapshot.get("dirty_files", [])
    if dirty:
        console.print(
            f"  [yellow]⚠[/yellow] {len(dirty)} dirty file(s) in export not present locally"
            " — did you commit before leaving?"
        )
        for f in dirty:
            console.print(f"    - {f}")

    # Check for existing local session
    imported_conv = session.get("conversation", [])
    session_id = session["id"]

    existing = _find_existing_session(project_dir, session_id)

    if existing and existing.session_id != session_id:
        # Different session exists for this project
        local_conv = _load_local_conversation(existing)
        if local_conv and lineage_mod.is_continuation(local_conv, imported_conv):
            console.print(
                f"  [green]✓[/green] Session continuity: imported session is a continuation of local session {existing.session_id[:7]}"
            )
            local_count = sum(1 for e in local_conv if e.get("type") in ("user", "assistant"))
            imp_count = session.get("message_count", len(imported_conv))
            console.print(f"    Local: {local_count} messages")
            console.print(f"    Imported: {imp_count} messages (last active {_relative_time(session.get('last_activity'))})")
            console.print(f"  [green]✓[/green] Replacing local session with imported version")
        else:
            # Diverged
            console.print(
                f"  [yellow]⚠[/yellow] A different session already exists for this project "
                f"(last active {_relative_time(existing.last_activity)})"
            )
            console.print("    Local session has divergent conversation history — this is not a continuation.")
            if not replace and not dry_run:
                if not click.confirm("  Overwrite local session with imported one?", default=False):
                    sys.exit(0)

    console.print(f"  [green]✓[/green] Restored conversation ({session.get('message_count', len(imported_conv))} messages)")

    cfg = session.get("config", {})
    if cfg:
        parts = []
        if "settings_json" in cfg:
            parts.append(".claude/settings.json")
        if "claude_md" in cfg:
            parts.append("CLAUDE.md")
        if "commands" in cfg:
            parts.append(".claude/commands/")
        if parts:
            console.print(f"  [green]✓[/green] Restored project config ({', '.join(parts)})")

    # Write session to disk
    try:
        written_id = BACKEND.import_session(bndl, project_dir, dry_run=dry_run)
    except Exception as e:
        err_console.print(f"[red]✗ Import failed: {e}[/red]")
        sys.exit(1)

    if no_launch or dry_run:
        if dry_run:
            console.print(f"  [dim]Would launch: claude --resume {written_id}[/dim]")
        return

    console.print()
    console.print("  Launching Claude Code with restored session...")
    BACKEND.launch(written_id, project_dir)


# ---------------------------------------------------------------------------
# config
# ---------------------------------------------------------------------------

@cli.group("config")
def cmd_config():
    """Manage commuter configuration."""


@cmd_config.command("set")
@click.argument("key")
@click.argument("value", nargs=-1, required=True)
def config_set(key, value):
    """Set a configuration value.

    \b
    Keys:
      path-map <from> <to>    Add a path mapping between machines
      transfer-dir <path>     Set the shared transfer directory
    """
    if key == "path-map":
        if len(value) != 2:
            err_console.print("[red]✗ path-map requires exactly two arguments: <from> <to>[/red]")
            sys.exit(1)
        config_mod.add_path_map(value[0], value[1])
        console.print(f"  [green]✓[/green] Path map added: {value[0]} → {value[1]}")
    elif key == "transfer-dir":
        if len(value) != 1:
            err_console.print("[red]✗ transfer-dir requires exactly one argument[/red]")
            sys.exit(1)
        config_mod.set_transfer_dir(value[0])
        console.print(f"  [green]✓[/green] Transfer directory set: {value[0]}")
    else:
        err_console.print(f"[red]✗ Unknown config key: {key!r}[/red]")
        err_console.print("  Valid keys: path-map, transfer-dir")
        sys.exit(1)


@cmd_config.command("show")
def config_show():
    """Show current configuration."""
    maps = config_mod.get_path_maps()
    transfer_dir = config_mod.get_transfer_dir()

    if maps:
        console.print("[bold]Path maps:[/bold]")
        for from_path, to_path in maps:
            console.print(f"  {from_path} → {to_path}")
    else:
        console.print("[dim]No path maps configured.[/dim]")

    if transfer_dir:
        console.print(f"[bold]Transfer directory:[/bold] {transfer_dir}")
    else:
        console.print("[dim]No transfer directory configured.[/dim]")


# ---------------------------------------------------------------------------
# push / pull (stretch goal)
# ---------------------------------------------------------------------------

@cli.command("push")
@click.option("-v", "--verbose", is_flag=True)
def cmd_push(verbose):
    """Export the latest session to the configured transfer directory."""
    transfer_dir = config_mod.get_transfer_dir()
    if not transfer_dir:
        err_console.print("[red]✗ No transfer directory configured.[/red]")
        err_console.print("  Run: commuter config set transfer-dir ~/Dropbox/.commuter/")
        sys.exit(1)

    info = BACKEND.latest_session()
    if not info:
        err_console.print("[red]No sessions found.[/red]")
        sys.exit(1)

    pending_dir = transfer_dir / "pending"
    pending_dir.mkdir(parents=True, exist_ok=True)

    output_path = pending_dir / f"{info.session_id}.json"

    data = BACKEND.export_session(info.session_id)
    conversation = data["conversation"]
    lineage_hash = lineage_mod.compute(conversation)
    git_snapshot = git_utils.get_snapshot(data["project_dir"])

    bndl = bundle_mod.create(
        backend=BACKEND.name,
        session_id=data["session_id"],
        project_dir=data["project_dir"],
        conversation=conversation,
        config=data["config"],
        git_snapshot=git_snapshot,
        lineage_hash=lineage_hash,
        backend_version=data.get("backend_version"),
    )

    bundle_mod.write(bndl, output_path)

    msg_count = bndl["session"]["message_count"]
    size_kb = output_path.stat().st_size // 1024
    console.print(
        f"  [green]✓[/green] Pushed session [cyan]{info.session_id[:7]}[/cyan]"
        f" ({msg_count} messages, {size_kb}KB) → {output_path}"
    )


@cli.command("pull")
@click.option("--no-launch", is_flag=True)
@click.option("--dry-run", is_flag=True)
@click.option("-v", "--verbose", is_flag=True)
def cmd_pull(no_launch, dry_run, verbose):
    """Import the latest session from the configured transfer directory."""
    transfer_dir = config_mod.get_transfer_dir()
    if not transfer_dir:
        err_console.print("[red]✗ No transfer directory configured.[/red]")
        err_console.print("  Run: commuter config set transfer-dir ~/Dropbox/.commuter/")
        sys.exit(1)

    pending_dir = transfer_dir / "pending"
    if not pending_dir.exists():
        err_console.print(f"[red]✗ No pending sessions in {pending_dir}[/red]")
        sys.exit(1)

    bundles = sorted(pending_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not bundles:
        err_console.print(f"[red]✗ No bundle files found in {pending_dir}[/red]")
        sys.exit(1)

    bundle_file = bundles[0]
    if verbose:
        console.print(f"  Found bundle: {bundle_file.name}")

    # Delegate to import logic with --replace behavior
    ctx = click.get_current_context()
    ctx.invoke(
        cmd_import,
        bundle_file=str(bundle_file),
        project_dir=None,
        replace=True,
        no_launch=no_launch,
        dry_run=dry_run,
        verbose=verbose,
    )

    # Move to history after successful import
    if not dry_run:
        history_dir = transfer_dir / "history"
        history_dir.mkdir(parents=True, exist_ok=True)
        dest = history_dir / bundle_file.name
        bundle_file.rename(dest)
        if verbose:
            console.print(f"  [dim]Moved bundle to history: {dest}[/dim]")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _shorten_path(path: str) -> str:
    home = str(Path.home())
    if path.startswith(home):
        return "~" + path[len(home):]
    return path


def _relative_time(ts, now: datetime | None = None) -> str:
    if ts is None:
        return "unknown"
    if isinstance(ts, str):
        try:
            ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except ValueError:
            return ts
    if now is None:
        now = datetime.now(timezone.utc)
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    delta = now - ts
    secs = int(delta.total_seconds())
    if secs < 60:
        return f"{secs}s ago"
    if secs < 3600:
        return f"{secs // 60}m ago"
    if secs < 86400:
        return f"{secs // 3600}h ago"
    return f"{secs // 86400}d ago"


def _resolve_project_dir(src_project_dir: str) -> str | None:
    """Try to find the local project directory for a bundle's source path."""
    # 1. Direct path exists
    if Path(src_project_dir).exists():
        return src_project_dir

    # 2. Apply configured path maps
    mapped = pathmap.translate(src_project_dir)
    if mapped != src_project_dir and Path(mapped).exists():
        return mapped

    return None


def _find_existing_session(project_dir: str, session_id: str):
    """Find a session for a given project dir, ignoring sessions with matching ID."""
    encoded = pathmap.encode_project_path(project_dir)
    project_storage = Path.home() / ".claude" / "projects" / encoded

    if not project_storage.exists():
        return None

    sessions = BACKEND.discover()
    for s in sessions:
        if pathmap.encode_project_path(s.project_dir) == encoded:
            if s.session_id != session_id:
                return s
    return None


def _load_local_conversation(session_info) -> list[dict] | None:
    if not session_info or not session_info.jsonl_path:
        return None
    try:
        from .backends.claude_code import _read_jsonl
        return _read_jsonl(session_info.jsonl_path)
    except OSError:
        return None
