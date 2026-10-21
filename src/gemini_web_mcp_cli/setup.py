"""MCP server setup commands for AI tool clients.

Configures the gemini-web-mcp server in various AI tool config files,
so the tools can use Gemini via MCP protocol.

Usage:
    gemcli setup add cursor
    gemcli setup add claude-code
    gemcli setup list
    gemcli setup remove cursor
"""

import json
import os
import platform
import shutil
import subprocess
from pathlib import Path

import rich_click as click
from rich.console import Console
from rich.prompt import Confirm, Prompt
from rich.syntax import Syntax
from rich.table import Table

from gemini_web_mcp_cli.core.json_io import read_json_dict, write_json_file
from gemini_web_mcp_cli.skill import TOOL_CONFIGS, _is_tool_installed

console = Console()

# MCP server command - the binary that clients will execute
MCP_SERVER_CMD = "gemini-web-mcp"
MCP_SERVER_KEY = "gemini-web-mcp"


def _is_configured(config: dict, key: str = MCP_SERVER_KEY) -> bool:
    """Check if gemini-web-mcp is already in an mcpServers config."""
    servers = config.get("mcpServers", {})
    return key in servers


def _add_mcp_server(config: dict, key: str = MCP_SERVER_KEY, extra: dict | None = None) -> dict:
    """Add gemini-web-mcp to an mcpServers config dict."""
    config.setdefault("mcpServers", {})
    # Use full binary path so GUI apps (Claude Desktop) can find it
    cmd = shutil.which(MCP_SERVER_CMD) or MCP_SERVER_CMD
    entry = {"command": cmd, "args": []}
    if extra:
        entry.update(extra)
    config["mcpServers"][key] = entry
    return config


def _remove_mcp_server(config: dict, key: str = MCP_SERVER_KEY) -> bool:
    """Remove gemini-web-mcp from an mcpServers config dict. Returns True if removed."""
    servers = config.get("mcpServers", {})
    if key in servers:
        del servers[key]
        return True
    return False


# ── Config paths (platform-specific) ───────────────────────────────────────


def _claude_desktop_config_path() -> Path:
    system = platform.system()
    if system == "Darwin":
        return (
            Path.home() / "Library" / "Application Support" / "Claude"
            / "claude_desktop_config.json"
        )
    elif system == "Windows":
        return Path(os.environ.get("APPDATA", "")) / "Claude" / "claude_desktop_config.json"
    else:
        return Path.home() / ".config" / "claude" / "claude_desktop_config.json"


def _gemini_cli_config_path() -> Path:
    return Path.home() / ".gemini" / "settings.json"


def _cursor_config_path() -> Path:
    system = platform.system()
    if system == "Darwin":
        return Path.home() / ".cursor" / "mcp.json"
    elif system == "Windows":
        return Path(os.environ.get("APPDATA", "")) / "Cursor" / "User" / "mcp.json"
    else:
        return Path.home() / ".config" / "cursor" / "mcp.json"


def _windsurf_config_path() -> Path:
    system = platform.system()
    if system == "Darwin":
        return Path.home() / ".codeium" / "windsurf" / "mcp_config.json"
    elif system == "Windows":
        return Path(os.environ.get("APPDATA", "")) / "Codeium" / "windsurf" / "mcp_config.json"
    else:
        return Path.home() / ".config" / "codeium" / "windsurf" / "mcp_config.json"


def _cline_config_path() -> Path:
    return Path.home() / ".cline" / "data" / "settings" / "cline_mcp_settings.json"


def _antigravity_config_path() -> Path:
    return Path.home() / ".gemini" / "antigravity" / "mcp_config.json"


# ── Client registry ────────────────────────────────────────────────────────


CLIENT_REGISTRY = {
    "claude-code": {
        "name": "Claude Code",
        "description": "Anthropic CLI (claude command)",
        "config_fn": None,  # Uses claude mcp add
    },
    "gemini-cli": {
        "name": "Gemini CLI",
        "description": "Google Gemini CLI",
        "config_fn": _gemini_cli_config_path,
        "key": "gemini-web",
        "extra": {"trust": True},
    },
    "cursor": {
        "name": "Cursor",
        "description": "Cursor AI editor",
        "config_fn": _cursor_config_path,
    },
    "windsurf": {
        "name": "Windsurf",
        "description": "Codeium Windsurf editor",
        "config_fn": _windsurf_config_path,
    },
    "cline": {
        "name": "Cline CLI",
        "description": "Cline CLI terminal agent",
        "config_fn": _cline_config_path,
    },
    "antigravity": {
        "name": "Antigravity",
        "description": "Google Antigravity AI IDE",
        "config_fn": _antigravity_config_path,
        "key": "gemini-web",
    },
    "codex": {
        "name": "Codex",
        "description": "OpenAI Codex CLI agent",
        "config_fn": None,  # Uses codex mcp add
    },
}

VALID_CLIENTS = list(CLIENT_REGISTRY.keys())


# ── Setup implementations ──────────────────────────────────────────────────


def _setup_claude_code() -> bool:
    """Add MCP to Claude Code via `claude mcp add`."""
    claude_cmd = shutil.which("claude")
    if not claude_cmd:
        console.print("[yellow]Warning:[/yellow] 'claude' command not found in PATH")
        console.print("  Install Claude Code: https://docs.anthropic.com/en/docs/claude-code")
        return False

    try:
        result = subprocess.run(
            [claude_cmd, "mcp", "add", "-s", "user", MCP_SERVER_KEY, "--", MCP_SERVER_CMD],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            console.print("[green]Added to Claude Code (user scope)[/green]")
            return True
        elif "already exists" in result.stderr.lower():
            console.print("[green]Already configured in Claude Code[/green]")
            return True
        else:
            console.print(f"[yellow]Warning:[/yellow] {result.stderr.strip()}")
            return False
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
        console.print(f"[yellow]Warning:[/yellow] Could not run claude command: {e}")
        return False


def _setup_json_client(client_id: str) -> bool:
    """Add MCP to a JSON config-based client."""
    info = CLIENT_REGISTRY[client_id]
    config_fn = info["config_fn"]
    key = info.get("key", MCP_SERVER_KEY)
    extra = info.get("extra")

    config_path = config_fn()
    config = read_json_dict(config_path)

    if _is_configured(config, key):
        console.print(f"[green]Already configured in {info['name']}[/green]")
        return True

    _add_mcp_server(config, key=key, extra=extra)
    write_json_file(config_path, config, trailing_newline=True)
    console.print(f"[green]Added to {info['name']}[/green]")
    console.print(f"  [dim]{config_path}[/dim]")
    return True


def _setup_codex() -> bool:
    """Add MCP to Codex via `codex mcp add`."""
    codex_cmd = shutil.which("codex")
    if not codex_cmd:
        console.print(
            "[yellow]Warning:[/yellow] 'codex' command not found in PATH"
        )
        return False

    server_cmd = shutil.which(MCP_SERVER_CMD) or MCP_SERVER_CMD
    try:
        result = subprocess.run(
            [codex_cmd, "mcp", "add", MCP_SERVER_KEY, "--", server_cmd],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            console.print("[green]Added to Codex[/green]")
            return True
        elif "already exists" in result.stderr.lower():
            console.print("[green]Already configured in Codex[/green]")
            return True
        else:
            console.print(
                f"[yellow]Warning:[/yellow] {result.stderr.strip()}"
            )
            return False
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
        console.print(f"[yellow]Warning:[/yellow] {e}")
        return False


def _remove_claude_code() -> bool:
    """Remove MCP from Claude Code."""
    claude_cmd = shutil.which("claude")
    if not claude_cmd:
        console.print("[yellow]Warning:[/yellow] 'claude' command not found")
        return False

    try:
        result = subprocess.run(
            [claude_cmd, "mcp", "remove", "-s", "user", MCP_SERVER_KEY],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            console.print("[green]Removed from Claude Code[/green]")
            return True
        else:
            console.print(f"[yellow]Note:[/yellow] {result.stderr.strip()}")
            return False
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
        console.print(f"[yellow]Warning:[/yellow] {e}")
        return False


def _remove_codex() -> bool:
    """Remove MCP from Codex."""
    codex_cmd = shutil.which("codex")
    if not codex_cmd:
        console.print("[yellow]Warning:[/yellow] 'codex' command not found")
        return False

    try:
        result = subprocess.run(
            [codex_cmd, "mcp", "remove", MCP_SERVER_KEY],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            console.print("[green]Removed from Codex[/green]")
            return True
        else:
            console.print(
                f"[yellow]Note:[/yellow] {result.stderr.strip()}"
            )
            return False
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
        console.print(f"[yellow]Warning:[/yellow] {e}")
        return False


def _remove_json_client(client_id: str) -> bool:
    """Remove MCP from a JSON config-based client."""
    info = CLIENT_REGISTRY[client_id]
    config_fn = info["config_fn"]
    key = info.get("key", MCP_SERVER_KEY)

    config_path = config_fn()
    if not config_path.exists():
        console.print(f"[dim]No config file found for {info['name']}.[/dim]")
        return False

    config = read_json_dict(config_path)
    if _remove_mcp_server(config, key):
        write_json_file(config_path, config, trailing_newline=True)
        console.print(f"[green]Removed from {info['name']}[/green]")
        return True
    else:
        console.print(f"[dim]Gemini Web MCP was not configured in {info['name']}.[/dim]")
        return False


def _find_mcp_server_path() -> str | None:
    """Find the full path to the gemini-web-mcp binary."""
    return shutil.which(MCP_SERVER_CMD)


def _prompt_numbered(prompt_text: str, options: list[tuple[str, str]], default: int = 1) -> str:
    """Show a numbered prompt and return the chosen option value."""
    console.print(f"{prompt_text}")
    for i, (_value, label) in enumerate(options, 1):
        marker = " [dim](default)[/dim]" if i == default else ""
        console.print(f"  [cyan]{i}[/cyan]) {label}{marker}")

    valid = [str(i) for i in range(1, len(options) + 1)]
    choice = Prompt.ask("Choose", choices=valid, default=str(default), show_choices=False)
    return options[int(choice) - 1][0]


def _setup_json() -> None:
    """Interactive flow to generate MCP JSON config for any tool."""
    console.print("[bold]Generate MCP JSON config[/bold]\n")
    console.print("This generates a JSON snippet you can paste into any tool's MCP config.\n")

    config_type = _prompt_numbered("Config type:", [
        ("uvx", "uvx (no install required)"),
        ("regular", "Regular (uses installed binary)"),
    ])

    use_full_path = False
    if config_type == "regular":
        path_choice = _prompt_numbered("\nCommand format:", [
            ("name", f"Command name ({MCP_SERVER_CMD})"),
            ("full", "Full path to binary"),
        ])
        use_full_path = path_choice == "full"

    config_scope = _prompt_numbered("\nConfig scope:", [
        ("existing", "Add to existing config (server entry only)"),
        ("new", "New config file (includes mcpServers wrapper)"),
    ])

    # Build the server entry
    if config_type == "uvx":
        server_entry = {
            "command": "uvx",
            "args": ["--from", "gemini-web-mcp-cli", MCP_SERVER_CMD],
        }
    else:
        if use_full_path:
            binary_path = _find_mcp_server_path()
            if not binary_path:
                console.print(
                    f"\n[yellow]Warning:[/yellow] {MCP_SERVER_CMD} not found in PATH, "
                    "using command name instead"
                )
                binary_path = MCP_SERVER_CMD
            server_entry = {"command": binary_path}
        else:
            server_entry = {"command": MCP_SERVER_CMD}

    if config_scope == "new":
        output = {"mcpServers": {MCP_SERVER_KEY: server_entry}}
    else:
        output = {MCP_SERVER_KEY: server_entry}

    json_str = json.dumps(output, indent=2)

    console.print()
    console.print(Syntax(json_str, "json", theme="monokai", padding=1))
    console.print()

    if platform.system() == "Darwin":
        if Confirm.ask("Copy to clipboard?", default=True):
            try:
                subprocess.run(
                    ["pbcopy"],
                    input=json_str.encode(),
                    check=True,
                    timeout=5,
                )
                console.print("[green]✓[/green] Copied to clipboard")
            except (subprocess.SubprocessError, OSError):
                console.print("[yellow]Warning:[/yellow] Could not copy to clipboard")

# ── Tool detection & status ─────────────────────────────────────────────────


def _detect_tool(client_id: str) -> bool:
    """Check if an AI tool is installed/present on the system.

    Delegates to skill.py's TOOL_CONFIGS registry for shared keys;
    handles setup-only clients (windsurf) inline.
    """
    if client_id in TOOL_CONFIGS:
        return _is_tool_installed(client_id)
    if client_id == "windsurf":
        return _windsurf_config_path().parent.exists()
    return False


def _is_already_configured(client_id: str) -> bool:
    """Check if MCP is already configured for a client."""
    try:
        if client_id == "claude-code":
            claude_cmd = shutil.which("claude")
            if claude_cmd:
                result = subprocess.run(
                    [claude_cmd, "mcp", "list"],
                    capture_output=True, text=True, timeout=5,
                )
                return MCP_SERVER_KEY in result.stdout.lower()
            return False
        elif client_id == "codex":
            codex_cmd = shutil.which("codex")
            if codex_cmd:
                result = subprocess.run(
                    [codex_cmd, "mcp", "list"],
                    capture_output=True, text=True, timeout=5,
                )
                return MCP_SERVER_KEY in result.stdout.lower()
            return False
        else:
            info = CLIENT_REGISTRY[client_id]
            config_fn = info.get("config_fn")
            if not config_fn:
                return False
            key = info.get("key", MCP_SERVER_KEY)
            config = read_json_dict(config_fn())
            return _is_configured(config, key)
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass
    return False


# ── Multi-tool setup / remove ──────────────────────────────────────────────


def _setup_all() -> None:
    """Interactive multi-tool setup. Scans system for AI tools and lets user choose."""
    console.print("\n[bold]Scanning for AI tools...[/bold]\n")

    detected = []  # (client_id, info, is_configured, has_auto)
    not_found = []

    for client_id, info in CLIENT_REGISTRY.items():
        is_present = _detect_tool(client_id)
        has_auto = (
            info.get("config_fn") is not None
            or client_id in ("claude-code", "codex")
        )
        if is_present:
            already = _is_already_configured(client_id) if has_auto else False
            detected.append((client_id, info, already, has_auto))
        else:
            not_found.append((client_id, info))

    # Display results table
    table = Table(title="Detected AI Tools")
    table.add_column("#", justify="right", style="cyan", width=3)
    table.add_column("Tool", style="bold")
    table.add_column("Status", justify="center")

    configurable = []
    for i, (client_id, info, already, has_auto) in enumerate(detected):
        num = str(i + 1)
        if already:
            table.add_row(num, info["name"], "[green]✓ configured[/green]")
        else:
            table.add_row(num, info["name"], "[yellow]detected[/yellow]")
            configurable.append(i)

    console.print(table)

    if not_found:
        names = ", ".join(info["name"] for _, info in not_found)
        console.print(f"\n[dim]Not found: {names}[/dim]")

    if not configurable:
        if detected:
            console.print("\n[green]All detected tools are already configured! ✓[/green]")
        else:
            console.print("\n[yellow]No supported AI tools detected on your system.[/yellow]")
            console.print(
                "[dim]Use 'gemcli setup add <client>' to configure a specific tool.[/dim]"
            )
        return

    # Interactive selection
    unconfigured_names = [
        f"{detected[i][1]['name']} ({detected[i][0]})"
        for i in configurable
    ]
    console.print(f"\n[bold]Unconfigured tools:[/bold] {', '.join(unconfigured_names)}")
    console.print()

    choice = Prompt.ask(
        "Configure which tools? [cyan]all[/cyan] / comma-separated numbers / [cyan]none[/cyan]",
        default="all",
    ).strip().lower()

    if choice in ("none", "n"):
        console.print("Cancelled.")
        return

    if choice in ("all", "a", "yes", "y"):
        selected_indices = configurable
    else:
        try:
            nums = [int(n.strip()) for n in choice.split(",")]
            selected_indices = []
            for n in nums:
                idx = n - 1
                if idx in configurable:
                    selected_indices.append(idx)
                else:
                    console.print(f"[yellow]Skipping #{n} — already configured or invalid[/yellow]")
        except ValueError:
            console.print(
                "[red]Invalid input. Use 'all', 'none', or comma-separated numbers.[/red]"
            )
            return

    if not selected_indices:
        console.print("[dim]Nothing to configure.[/dim]")
        return

    # Execute setup
    console.print()
    success_count = 0
    for idx in selected_indices:
        client_id = detected[idx][0]
        if client_id == "claude-code":
            if _setup_claude_code():
                success_count += 1
        elif client_id == "codex":
            if _setup_codex():
                success_count += 1
        elif CLIENT_REGISTRY[client_id].get("config_fn"):
            if _setup_json_client(client_id):
                success_count += 1

    console.print(f"\n[green]✓ Configured {success_count} tool(s)[/green]")
    if success_count > 0:
        console.print("[dim]Restart the configured tools to activate the MCP server.[/dim]")


def _remove_all() -> None:
    """Remove MCP from all configured tools with explicit confirmation."""
    console.print("\n[bold]Scanning for configured tools...[/bold]\n")

    configured = []
    for client_id, info in CLIENT_REGISTRY.items():
        has_auto = (
            info.get("config_fn") is not None
            or client_id in ("claude-code", "codex")
        )
        if not has_auto:
            continue
        if _is_already_configured(client_id):
            configured.append((client_id, info))

    if not configured:
        console.print("[dim]No tools have Gemini Web MCP configured.[/dim]")
        return

    # Show what will be removed
    table = Table(title="Configured Tools")
    table.add_column("#", justify="right", style="cyan", width=3)
    table.add_column("Tool", style="bold")

    for i, (client_id, info) in enumerate(configured):
        table.add_row(str(i + 1), info["name"])

    console.print(table)

    # Confirm removal
    console.print()
    console.print("[bold red]⚠  WARNING:[/bold red] This will remove the Gemini Web MCP server")
    console.print(f"from [bold]{len(configured)}[/bold] tool(s) listed above.")
    console.print()

    if not Confirm.ask(
        "[bold]Are you sure you want to remove MCP from ALL configured tools?[/bold]",
        default=False,
    ):
        console.print("Cancelled.")
        return

    # Execute removal
    console.print()
    removed_count = 0
    for client_id, info in configured:
        if client_id == "claude-code":
            if _remove_claude_code():
                removed_count += 1
        elif client_id == "codex":
            if _remove_codex():
                removed_count += 1
        else:
            if _remove_json_client(client_id):
                removed_count += 1

    console.print(f"\n[green]✓ Removed from {removed_count} tool(s)[/green]")
    if removed_count > 0:
        console.print("[dim]Restart the affected tools to apply changes.[/dim]")


# ── Click commands ──────────────────────────────────────────────────────────


@click.group()
def setup():
    """Configure Gemini Web MCP server for AI tools."""
    pass


@setup.command("add")
@click.argument("client")
def setup_add(client):
    """Add Gemini Web MCP server to an AI tool.

    Supported clients: claude-code, gemini-cli, cursor,
    windsurf, cline, antigravity, codex, json, all.

    \b
    Examples:
      gemcli setup add cursor
      gemcli setup add claude-code
      gemcli setup add json
      gemcli setup add all
    """
    if client == "json":
        _setup_json()
        return

    if client == "all":
        _setup_all()
        return

    if client not in CLIENT_REGISTRY:
        valid = ", ".join(list(CLIENT_REGISTRY.keys()) + ["json", "all"])
        console.print(f"[red]Error:[/red] Unknown client '{client}'")
        console.print(f"Available clients: {valid}")
        raise SystemExit(1)

    info = CLIENT_REGISTRY[client]
    console.print(f"\n[bold]{info['name']}[/bold] -- Adding Gemini Web MCP\n")

    if client == "codex":
        success = _setup_codex()
    elif client == "claude-code":
        success = _setup_claude_code()
    else:
        success = _setup_json_client(client)

    if success:
        console.print(f"\n[dim]Restart {info['name']} to activate the MCP server.[/dim]")


@setup.command("remove")
@click.argument("client")
def setup_remove(client):
    """Remove Gemini Web MCP server from an AI tool.

    \b
    Examples:
      gemcli setup remove cursor
      gemcli setup remove claude-code
      gemcli setup remove all
    """
    if client == "all":
        _remove_all()
        return

    if client not in CLIENT_REGISTRY:
        valid = ", ".join(list(CLIENT_REGISTRY.keys()) + ["all"])
        console.print(f"[red]Error:[/red] Unknown client '{client}'")
        console.print(f"Available clients: {valid}")
        raise SystemExit(1)

    if client == "codex":
        _remove_codex()
    elif client == "claude-code":
        _remove_claude_code()
    else:
        _remove_json_client(client)


@setup.command("list")
def setup_list():
    """Show supported AI tools and their MCP configuration status."""
    table = Table(title="Gemini Web MCP Server Configuration")
    table.add_column("Client", style="cyan")
    table.add_column("Description")
    table.add_column("MCP Status", justify="center")
    table.add_column("Config Path", style="dim")

    for client_id, info in CLIENT_REGISTRY.items():
        status = "[dim]-[/dim]"
        config_path_str = ""

        if client_id == "claude-code":
            claude_cmd = shutil.which("claude")
            if claude_cmd:
                try:
                    result = subprocess.run(
                        [claude_cmd, "mcp", "list"],
                        capture_output=True, text=True, timeout=5,
                    )
                    if MCP_SERVER_KEY in result.stdout.lower():
                        status = "[green]yes[/green]"
                except (subprocess.TimeoutExpired, OSError):
                    status = "[dim]?[/dim]"
                config_path_str = "claude mcp list"
            else:
                config_path_str = "not installed"
        elif client_id == "codex":
            codex_cmd = shutil.which("codex")
            if codex_cmd:
                try:
                    result = subprocess.run(
                        [codex_cmd, "mcp", "list"],
                        capture_output=True, text=True, timeout=5,
                    )
                    if MCP_SERVER_KEY in result.stdout.lower():
                        status = "[green]yes[/green]"
                except (subprocess.TimeoutExpired, OSError):
                    status = "[dim]?[/dim]"
                config_path_str = "codex mcp list"
            else:
                config_path_str = "not installed"
        else:
            config_fn = info["config_fn"]
            key = info.get("key", MCP_SERVER_KEY)
            path = config_fn()
            config = read_json_dict(path)
            if _is_configured(config, key):
                status = "[green]yes[/green]"
            config_path_str = str(path).replace(str(Path.home()), "~")

        table.add_row(info["name"], info["description"], status, config_path_str)

    console.print(table)
    console.print("\n[dim]Add:    gemcli setup add <client>[/dim]")
    console.print("[dim]Remove: gemcli setup remove <client>[/dim]")
