"""Skill installer commands for Gemini Web MCP CLI.

Installs skill documentation into AI tools so they know how to use
the gemcli CLI and gemini-web-mcp MCP server.

Usage:
    gemcli skill install claude-code
    gemcli skill uninstall cursor
    gemcli skill list
    gemcli skill update
    gemcli skill show
"""

import os
import re
import shutil
from pathlib import Path
from typing import Optional, Required, TypedDict

import rich_click as click
from rich.console import Console
from rich.table import Table

from gemini_web_mcp_cli import __version__

console = Console()

# Skill name used in directory names and markers
SKILL_NAME = "gemini-web-skill"
OLD_SKILL_NAME = "gemini-skill"
START_MARKER = f"<!-- {SKILL_NAME}-start -->"
END_MARKER = f"<!-- {SKILL_NAME}-end -->"
OLD_START_MARKER = f"<!-- {OLD_SKILL_NAME}-start -->"
OLD_END_MARKER = f"<!-- {OLD_SKILL_NAME}-end -->"
VERSION_PREFIX = "<!-- gemini-version:"


# ── Tool configuration mapping ──────────────────────────────────────────

_HOME = Path.home()

_AGENTS_USER = _HOME / ".agents" / "skills" / SKILL_NAME
_AGENTS_PROJECT = Path(f".agents/skills/{SKILL_NAME}")

_HERMES_HOME = Path(os.environ.get("HERMES_HOME") or _HOME / ".hermes")


class ToolConfig(TypedDict, total=False):
    user: Path
    project: Path
    format: Required[str]
    description: Required[str]
    binary: str
    root_dirs: list[Path]


TOOL_CONFIGS: dict[str, ToolConfig] = {
    "claude-code": {
        "user": _HOME / ".claude" / "skills" / SKILL_NAME,
        "project": Path(f".claude/skills/{SKILL_NAME}"),
        "format": "skill.md",
        "description": "Claude Code CLI and Desktop",
        "binary": "claude",
        "root_dirs": [_HOME / ".claude"],
    },
    "cursor": {
        "user": _HOME / ".cursor" / "skills" / SKILL_NAME,
        "project": Path(f".cursor/skills/{SKILL_NAME}"),
        "format": "skill.md",
        "description": "Cursor AI editor",
        "binary": "cursor",
        "root_dirs": [_HOME / ".cursor"],
    },
    "codex": {
        "user": _AGENTS_USER,
        "project": _AGENTS_PROJECT,
        "format": "skill.md",
        "description": "OpenAI Codex CLI agent",
        "binary": "codex",
        "root_dirs": [_HOME / ".codex", _HOME / ".agents"],
    },
    "opencode": {
        "user": _HOME / ".config" / "opencode" / "skills" / SKILL_NAME,
        "project": Path(f".opencode/skills/{SKILL_NAME}"),
        "format": "skill.md",
        "description": "OpenCode AI assistant",
        "binary": "opencode",
        "root_dirs": [_HOME / ".config" / "opencode"],
    },
    "gemini-cli": {
        "user": _AGENTS_USER,
        "project": _AGENTS_PROJECT,
        "format": "skill.md",
        "description": "Google Gemini CLI",
        "binary": "gemini",
        "root_dirs": [_HOME / ".agents", _HOME / ".gemini"],
    },
    "antigravity": {
        "user": _HOME / ".gemini" / "antigravity" / "skills" / SKILL_NAME,
        "project": _AGENTS_PROJECT,
        "format": "skill.md",
        "description": "Antigravity agent framework",
        "root_dirs": [_HOME / ".gemini" / "antigravity"],
    },
    "cline": {
        "user": _HOME / ".cline" / "skills" / SKILL_NAME,
        "project": Path(f".cline/skills/{SKILL_NAME}"),
        "format": "skill.md",
        "description": "Cline CLI terminal agent",
        "binary": "cline",
        "root_dirs": [_HOME / ".cline"],
    },
    "openclaw": {
        "user": _HOME / ".openclaw" / "workspace" / "skills" / SKILL_NAME,
        "project": Path(f".openclaw/workspace/skills/{SKILL_NAME}"),
        "format": "skill.md",
        "description": "OpenClaw AI agent framework",
        "binary": "openclaw",
        "root_dirs": [_HOME / ".openclaw"],
    },
    "alef-agent": {
        "user": _HOME / ".alef-agent" / "workspace" / "skills" / SKILL_NAME,
        "project": Path(f".alef-agent/workspace/skills/{SKILL_NAME}"),
        "format": "skill.md",
        "description": "Alef Agent framework",
        "root_dirs": [_HOME / ".alef-agent"],
    },
    "hermes": {
        "user": _HERMES_HOME / "skills" / SKILL_NAME,
        "project": Path(f".hermes/skills/{SKILL_NAME}"),
        "format": "skill.md",
        "description": "Hermes Agent (NousResearch)",
        "binary": "hermes",
        "root_dirs": [_HERMES_HOME],
    },
    "other": {
        "project": Path("./gemini-web-skill-export"),
        "format": "all",
        "description": "Export all formats for manual installation",
    },
}

VALID_TOOLS = list(TOOL_CONFIGS.keys())


def _is_tool_installed(tool: str) -> bool:
    """Check PATH for the tool's binary or existence of its config directories."""
    config = TOOL_CONFIGS.get(tool, {})
    binary = config.get("binary")
    if binary and shutil.which(binary):
        return True
    return any(d.exists() for d in (config.get("root_dirs") or []))


# ── Helpers ──────────────────────────────────────────────────────────────


def get_data_dir() -> Path:
    """Get the package data directory containing skill files."""
    import gemini_web_mcp_cli

    package_dir = Path(gemini_web_mcp_cli.__file__).parent
    data_dir = package_dir / "data"

    if not data_dir.exists():
        console.print(f"[red]Error:[/red] Data directory not found: {data_dir}")
        raise SystemExit(1)

    return data_dir


def check_install_status(tool: str, level: str = "user") -> tuple[bool, Optional[Path]]:
    """Check if skill is installed for a tool.

    Returns:
        (is_installed, install_path)
    """
    if tool not in TOOL_CONFIGS:
        return False, None

    config = TOOL_CONFIGS[tool]

    # Get install path
    if level == "user" and "user" in config:
        install_path = config["user"]
    elif level == "project" and "project" in config:
        install_path = config["project"]
    else:
        return False, None

    # Check format
    if config["format"] == "skill.md":
        skill_file = install_path / "SKILL.md"
        return skill_file.exists(), install_path
    elif config["format"] == "agents.md":
        if not install_path.exists():
            return False, install_path
        content = install_path.read_text(encoding="utf-8")
        return START_MARKER in content, install_path
    elif config["format"] == "all":
        return install_path.exists(), install_path

    return False, None


def _content_hash() -> str:
    """Hash the packaged skill content (SKILL.md, AGENTS_SECTION.md, references).

    Used to detect content changes that a version bump alone would miss, so
    `gemcli skill update` refreshes installs even within the same version.
    """
    import hashlib

    data_dir = get_data_dir()
    digest = hashlib.sha256()
    for path in sorted(data_dir.rglob("*")):
        if path.is_file():
            digest.update(str(path.relative_to(data_dir)).encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()[:12]


def _inject_version_to_frontmatter(skill_path: Path) -> None:
    """Inject the current package version + content hash into the frontmatter."""
    content = skill_path.read_text(encoding="utf-8")
    version_line = f'\nversion: "{__version__}"'
    hash_line = f"\ncontent-hash: \"{_content_hash()}\""
    if content.startswith("---"):
        end_idx = content.index("---", 3)
        frontmatter = content[3:end_idx]
        # Remove any existing version/hash lines
        frontmatter = re.sub(r"\nversion:.*", "", frontmatter)
        frontmatter = re.sub(r"\ncontent-hash:.*", "", frontmatter)
        # Add version before closing ---
        frontmatter = frontmatter.rstrip() + version_line + hash_line + "\n"
        content = "---" + frontmatter + "---" + content[end_idx + 3 :]
    else:
        # No frontmatter — prepend one with version
        content = f"---{version_line}{hash_line}\n---\n\n" + content
    skill_path.write_text(content, encoding="utf-8")


def _get_installed_version(tool: str, level: str) -> Optional[str]:
    """Read the version from an installed skill. Returns None if not found."""
    config = TOOL_CONFIGS[tool]
    install_path = config.get(level)
    if not install_path:
        return None

    format_type = config["format"]

    if format_type == "agents.md":
        if not install_path.exists():
            return None
        try:
            content = install_path.read_text(encoding="utf-8")
            match = re.search(r"<!-- gemini-version: ([\d.]+) -->", content)
            return match.group(1) if match else None
        except (OSError, UnicodeDecodeError):
            return None
    elif format_type == "skill.md":
        skill_file = install_path / "SKILL.md"
    elif format_type == "all":
        skill_file = install_path / "gemini-web-skill" / "SKILL.md"
    else:
        return None

    if not skill_file.exists():
        return None

    try:
        content = skill_file.read_text(encoding="utf-8")
        match = re.search(r'version:\s*"([^"]*)"', content)
        return match.group(1) if match else None
    except (OSError, UnicodeDecodeError):
        return None


def _get_installed_hash(tool: str, level: str) -> Optional[str]:
    """Read the installed skill's content hash. Returns None if not found."""
    config = TOOL_CONFIGS[tool]
    install_path = config.get(level)
    if not install_path:
        return None

    format_type = config["format"]
    try:
        if format_type == "agents.md":
            if not install_path.exists():
                return None
            content = install_path.read_text(encoding="utf-8")
            match = re.search(r"<!-- gemini-content: ([0-9a-f]+) -->", content)
            return match.group(1) if match else None
        if format_type == "skill.md":
            skill_file = install_path / "SKILL.md"
        elif format_type == "all":
            skill_file = install_path / "gemini-web-skill" / "SKILL.md"
        else:
            return None
        if not skill_file.exists():
            return None
        content = skill_file.read_text(encoding="utf-8")
        match = re.search(r'content-hash:\s*"([0-9a-f]+)"', content)
        return match.group(1) if match else None
    except (OSError, UnicodeDecodeError):
        return None


def _inject_version_to_agents_md(agents_path: Path) -> None:
    """Inject version + content hash comments into the Gemini AGENTS.md section."""
    try:
        content = agents_path.read_text(encoding="utf-8")
        marker = (
            f"<!-- gemini-version: {__version__} -->\n"
            f"<!-- gemini-content: {_content_hash()} -->"
        )

        content = re.sub(r"<!-- gemini-version: [\d.]+ -->\n?", "", content)
        content = re.sub(r"<!-- gemini-content: [0-9a-f]+ -->\n?", "", content)

        if START_MARKER in content:
            content = content.replace(
                START_MARKER,
                f"{START_MARKER}\n{marker}",
            )
            agents_path.write_text(content, encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        pass


# ── Legacy migration ─────────────────────────────────────────────────────


def _migrate_skill_dir(old_path: Path, new_path: Path, label: str) -> bool:
    """Move old_path → new_path if old_path exists. Returns True if acted."""
    if not old_path.exists():
        return False
    if new_path.exists():
        shutil.rmtree(old_path)
        console.print(f"[dim]Removed legacy {old_path} (new path already exists)[/dim]")
    else:
        new_path.parent.mkdir(parents=True, exist_ok=True)
        old_path.rename(new_path)
        console.print(f"[green]✓[/green] Migrated {label}: {old_path.name} → {new_path.name}")
    return True


def _migrate_legacy_installs() -> int:
    """Detect old installs and migrate them to current paths.

    Handles:
    - cc-claw → alef-agent (tool renamed)
    - gemini-skill → gemini-web-skill (all tools)

    Returns the number of migrations performed.
    """
    migrated = 0

    old = _HOME / ".cc-claw/workspace/skills/gemini-web-skill"
    new = _HOME / ".alef-agent/workspace/skills/gemini-web-skill"
    if _migrate_skill_dir(old, new, "cc-claw → alef-agent"):
        migrated += 1

    for tool, config in TOOL_CONFIGS.items():
        if tool == "other":
            continue

        fmt = config["format"]

        for level in ("user", "project"):
            new_path = config.get(level)
            if not new_path:
                continue

            if fmt == "skill.md":
                old_path = new_path.parent / OLD_SKILL_NAME
                if _migrate_skill_dir(old_path, new_path, f"{tool} ({level})"):
                    migrated += 1

            elif fmt == "agents.md":
                if not new_path.exists():
                    continue
                try:
                    content = new_path.read_text(encoding="utf-8")
                    if OLD_START_MARKER in content or OLD_END_MARKER in content:
                        content = content.replace(OLD_START_MARKER, START_MARKER)
                        content = content.replace(OLD_END_MARKER, END_MARKER)
                        new_path.write_text(content, encoding="utf-8")
                        console.print(
                            f"[green]✓[/green] Migrated {tool} ({level}): "
                            f"updated markers in {new_path.name}"
                        )
                        migrated += 1
                except (OSError, UnicodeDecodeError):
                    pass

    return migrated


# ── Install functions ────────────────────────────────────────────────────


def install_skill_md(install_path: Path) -> None:
    """Install SKILL.md format to a directory."""
    data_dir = get_data_dir()

    # Create directory
    install_path.mkdir(parents=True, exist_ok=True)

    # Copy SKILL.md
    skill_src = data_dir / "SKILL.md"
    skill_dst = install_path / "SKILL.md"
    shutil.copy2(skill_src, skill_dst)

    # Inject current version into frontmatter
    _inject_version_to_frontmatter(skill_dst)

    # Copy references directory
    ref_src = data_dir / "references"
    ref_dst = install_path / "references"
    if ref_dst.exists():
        shutil.rmtree(ref_dst)
    shutil.copytree(ref_src, ref_dst)

    console.print(f"[green]✓[/green] Installed SKILL.md (v{__version__}) to {install_path}")
    console.print("  [dim]• SKILL.md")
    console.print("  [dim]• references/IMAGE_PROMPTING_GUIDE.md")
    console.print("  [dim]• references/command_reference.md")
    console.print("  [dim]• references/troubleshooting.md")
    console.print("  [dim]• references/workflows.md")


def install_agents_md(install_path: Path) -> None:
    """Install/update AGENTS.md format (append with markers)."""
    data_dir = get_data_dir()
    section_src = data_dir / "AGENTS_SECTION.md"
    section_content = section_src.read_text(encoding="utf-8")

    # Read existing AGENTS.md or create new
    if install_path.exists():
        content = install_path.read_text(encoding="utf-8")

        if START_MARKER in content:
            # Update existing section
            start_idx = content.find(START_MARKER)
            end_idx = content.find(END_MARKER)

            if start_idx != -1 and end_idx != -1:
                before = content[:start_idx]
                after = content[end_idx + len(END_MARKER) :]
                content = before + section_content + after
            else:
                content = content.rstrip() + "\n\n" + section_content + "\n"
        else:
            content = content.rstrip() + "\n\n" + section_content + "\n"
    else:
        install_path.parent.mkdir(parents=True, exist_ok=True)
        content = section_content + "\n"

    install_path.write_text(content, encoding="utf-8")

    # Inject version marker
    _inject_version_to_agents_md(install_path)

    console.print(f"[green]✓[/green] Updated AGENTS.md at {install_path}")
    console.print("  [dim]• Gemini section appended with markers")


def install_all_formats(install_path: Path) -> None:
    """Export all skill formats to a directory."""
    data_dir = get_data_dir()

    # Remove existing directory
    if install_path.exists():
        shutil.rmtree(install_path)

    install_path.mkdir(parents=True, exist_ok=True)

    # Copy SKILL.md format (with references)
    skill_dir = install_path / "gemini-web-skill"
    skill_dir.mkdir()
    shutil.copy2(data_dir / "SKILL.md", skill_dir / "SKILL.md")
    shutil.copytree(data_dir / "references", skill_dir / "references")

    # Copy AGENTS.md section
    shutil.copy2(data_dir / "AGENTS_SECTION.md", install_path / "AGENTS_SECTION.md")

    # Create README
    readme_content = """# Gemini Web MCP Skill Export

This directory contains Gemini Web MCP skill files in multiple formats.

## Formats Available

### gemini-web-skill/
- `SKILL.md` - Main skill file for Claude Code, Cursor, OpenCode, Gemini CLI, Antigravity
- `references/` - Additional reference documentation

### AGENTS_SECTION.md
- Section format for Codex AGENTS.md (copy/paste into your AGENTS.md)

## Installation

### Claude Code
```bash
cp -r gemini-web-skill ~/.claude/skills/
```

### Cursor
```bash
cp -r gemini-web-skill ~/.cursor/skills/
```

### OpenCode
```bash
cp -r gemini-web-skill ~/.config/opencode/skills/
```

### Gemini CLI
```bash
cp -r gemini-web-skill ~/.agents/skills/
```

### Antigravity
```bash
cp -r gemini-web-skill ~/.agents/skills/
```

### Codex
```bash
cp -r gemini-web-skill ~/.agents/skills/
```

### Alef Agent
```bash
cp -r gemini-web-skill ~/.alef-agent/workspace/skills/
```

### Hermes Agent
```bash
cp -r gemini-web-skill ~/.hermes/skills/
```

## Automated Installation

Instead of manual copying, use:
```bash
gemcli skill install <tool>
```

Where `<tool>` is: claude-code, cursor, codex, opencode, gemini-cli, antigravity, hermes, cline,
openclaw, alef-agent, or other.
"""

    (install_path / "README.md").write_text(readme_content, encoding="utf-8")

    console.print(f"[green]✓[/green] Exported all formats to {install_path}")
    console.print(
        "  [dim]• gemini-web-skill/ (skill directory for Claude Code, Cursor, OpenCode, etc.)"
    )
    console.print("  [dim]• AGENTS_SECTION.md (for Codex)")
    console.print("  [dim]• README.md (installation instructions)")


# ── Update helper ────────────────────────────────────────────────────────


def _update_single_tool(tool: str, level: str) -> bool:
    """Update a single tool's skill at the given level. Returns True if updated."""
    config = TOOL_CONFIGS[tool]
    install_path = config.get(level)
    if not install_path:
        return False

    format_type = config["format"]

    try:
        if format_type == "skill.md":
            install_skill_md(install_path)
        elif format_type == "agents.md":
            install_agents_md(install_path)
        elif format_type == "all":
            install_all_formats(install_path)
        return True
    except Exception as e:
        console.print(f"[red]Error updating {tool} ({level}):[/red] {e}")
        return False


# ── Click command group ─────────────────────────────────────────────────


@click.group()
def skill():
    """Install Gemini skills for AI tools."""
    pass


@skill.command("install")
@click.argument("tool", type=click.Choice(VALID_TOOLS))
@click.option(
    "--level",
    "-l",
    type=click.Choice(["user", "project"]),
    default="user",
    help="Install at user level (~/) or project level (./)",
)
def skill_install(tool: str, level: str) -> None:
    """Install Gemini skill for an AI tool.

    Examples:
        gemcli skill install claude-code
        gemcli skill install alef-agent
        gemcli skill install codex --level project
        gemcli skill install other
    """
    _migrate_legacy_installs()
    config = TOOL_CONFIGS[tool]

    # Check level support
    if level == "user" and "user" not in config:
        if tool == "other":
            level = "project"
            console.print("[dim]Note: 'other' exports to current directory (project level)[/dim]")
        else:
            console.print(
                f"[red]Error:[/red] Tool '{tool}' does not support user-level installation"
            )
            console.print("Use --level project instead")
            raise SystemExit(1)

    # Get install path
    install_path = config.get(level)
    if not install_path:
        install_path = config.get("project")

    # Validate that the tool is installed for user-level installs
    if level == "user" and install_path:
        tool_detected = _is_tool_installed(tool)

        if not tool_detected:
            console.print(
                f"[yellow]Warning:[/yellow] {tool} does not appear to be installed on your system."
            )
            console.print("[dim](No binary on PATH and no config directory found)[/dim]")
            console.print()
            console.print("Options:")
            console.print("  1. Create the directory and install anyway")
            console.print("  2. Use --level project to install in current directory")
            console.print("  3. Cancel")
            console.print()

            choice = click.prompt("Choose an option", type=int, default=2)

            if choice == 1:
                console.print(f"[dim]Creating {install_path}...[/dim]")
                install_path.mkdir(parents=True, exist_ok=True)
            elif choice == 2:
                console.print("[dim]Switching to project-level installation...[/dim]")
                level = "project"
                install_path = config.get("project")
                if not install_path:
                    console.print(
                        f"[red]Error:[/red] Tool '{tool}' does not support project-level "
                        "installation"
                    )
                    raise SystemExit(1)
            else:
                console.print("Cancelled.")
                raise SystemExit(0)

    # Check if already installed
    is_installed, _ = check_install_status(tool, level)
    if is_installed:
        console.print(f"[yellow]![/yellow] Skill already installed for {tool} at {level} level")
        if not click.confirm("Overwrite existing installation?"):
            console.print("Cancelled.")
            raise SystemExit(0)

    # Install based on format
    format_type = config["format"]

    try:
        if format_type == "skill.md":
            install_skill_md(install_path)
        elif format_type == "agents.md":
            install_agents_md(install_path)
        elif format_type == "all":
            install_all_formats(install_path)

        console.print(f"\n[green]✓[/green] Successfully installed skill for [cyan]{tool}[/cyan]")
        console.print(f"  Level: {level}")
        console.print(f"  Path: {install_path}")

    except Exception as e:
        console.print(f"\n[red]✗ Installation failed:[/red] {e}")
        raise SystemExit(1)


@skill.command("uninstall")
@click.argument("tool", type=click.Choice(VALID_TOOLS))
@click.option(
    "--level",
    "-l",
    type=click.Choice(["user", "project"]),
    default="user",
    help="Uninstall from user or project level",
)
def skill_uninstall(tool: str, level: str) -> None:
    """Remove installed Gemini skill.

    Examples:
        gemcli skill uninstall claude-code
        gemcli skill uninstall codex --level project
    """
    _migrate_legacy_installs()
    is_installed, install_path = check_install_status(tool, level)

    if not is_installed:
        console.print(f"[yellow]![/yellow] Skill not installed for {tool} at {level} level")
        raise SystemExit(0)

    # Confirm deletion
    if not click.confirm(f"Remove skill from {install_path}?"):
        console.print("Cancelled.")
        raise SystemExit(0)

    config = TOOL_CONFIGS[tool]
    format_type = config["format"]

    try:
        if format_type == "skill.md":
            if install_path.exists():
                shutil.rmtree(install_path)
            console.print(f"[green]✓[/green] Removed {install_path}")

        elif format_type == "agents.md":
            if install_path.exists():
                content = install_path.read_text(encoding="utf-8")
                start_idx = content.find(START_MARKER)
                end_idx = content.find(END_MARKER)

                if start_idx != -1 and end_idx != -1:
                    before = content[:start_idx].rstrip()
                    after = content[end_idx + len(END_MARKER) :].lstrip()

                    if before and after:
                        content = before + "\n\n" + after
                    elif before:
                        content = before
                    elif after:
                        content = after
                    else:
                        content = ""

                    install_path.write_text(content, encoding="utf-8")
                    console.print(
                        f"[green]✓[/green] Removed Gemini section from {install_path}"
                    )
                else:
                    console.print(f"[yellow]![/yellow] Markers not found in {install_path}")

        elif format_type == "all":
            if install_path.exists():
                shutil.rmtree(install_path)
            console.print(f"[green]✓[/green] Removed {install_path}")

    except Exception as e:
        console.print(f"\n[red]✗ Uninstall failed:[/red] {e}")
        raise SystemExit(1)


@skill.command("list")
def skill_list() -> None:
    """Show available tools and installation status."""
    _migrate_legacy_installs()
    table = Table(title="Gemini Skill Installation Status")
    table.add_column("Tool", style="cyan")
    table.add_column("Description")
    table.add_column("User", justify="center")
    table.add_column("Project", justify="center")

    has_outdated = False

    for tool, config in TOOL_CONFIGS.items():
        if tool == "other":
            continue

        # Check user level
        if "user" in config:
            is_installed, _ = check_install_status(tool, "user")
            if is_installed:
                installed_ver = _get_installed_version(tool, "user")
                if installed_ver is None:
                    user_status = "[yellow]✓ (unknown)[/yellow]"
                    has_outdated = True
                elif installed_ver != __version__:
                    user_status = f"[yellow]✓ (v{installed_ver})[/yellow]"
                    has_outdated = True
                elif _get_installed_hash(tool, "user") != _content_hash():
                    user_status = f"[yellow]✓ (v{installed_ver}, stale)[/yellow]"
                    has_outdated = True
                else:
                    user_status = "[green]✓[/green]"
            else:
                user_status = "[dim]-[/dim]"
        else:
            user_status = "[dim]N/A[/dim]"

        # Check project level
        if "project" in config:
            is_installed, _ = check_install_status(tool, "project")
            if is_installed:
                installed_ver = _get_installed_version(tool, "project")
                if installed_ver is None:
                    project_status = "[yellow]✓ (unknown)[/yellow]"
                    has_outdated = True
                elif installed_ver != __version__:
                    project_status = f"[yellow]✓ (v{installed_ver})[/yellow]"
                    has_outdated = True
                elif _get_installed_hash(tool, "project") != _content_hash():
                    project_status = f"[yellow]✓ (v{installed_ver}, stale)[/yellow]"
                    has_outdated = True
                else:
                    project_status = "[green]✓[/green]"
            else:
                project_status = "[dim]-[/dim]"
        else:
            project_status = "[dim]N/A[/dim]"

        table.add_row(tool, config["description"], user_status, project_status)

    console.print(table)
    console.print("\n[dim]Legend: ✓ = installed, - = not installed, N/A = not applicable[/dim]")
    if has_outdated:
        console.print(
            f"[yellow]Some skills are outdated (current: v{__version__}). "
            "Run 'gemcli skill update' to update all.[/yellow]"
        )


@skill.command("update")
@click.argument("tool", required=False, default=None)
def skill_update(tool: Optional[str]) -> None:
    """Update outdated skills to the current version.

    Examples:
        gemcli skill update              # Update all outdated
        gemcli skill update claude-code   # Update just Claude Code
    """
    if tool and tool not in TOOL_CONFIGS:
        valid = ", ".join(TOOL_CONFIGS.keys())
        console.print(f"[red]Error:[/red] Unknown tool '{tool}'")
        console.print(f"Valid tools: {valid}")
        raise SystemExit(1)

    _migrate_legacy_installs()
    tools_to_check = {tool: TOOL_CONFIGS[tool]} if tool else TOOL_CONFIGS
    updated = 0
    skipped = 0
    already_current = 0

    for t, config in tools_to_check.items():
        for level in ("user", "project"):
            if level not in config:
                continue

            is_installed, _ = check_install_status(t, level)
            if not is_installed:
                continue

            installed_ver = _get_installed_version(t, level)
            installed_hash = _get_installed_hash(t, level)
            if installed_ver == __version__ and installed_hash == _content_hash():
                already_current += 1
                if tool:
                    console.print(
                        f"[green]✓[/green] {t} ({level}) is already at v{__version__}"
                    )
                continue

            old_ver = installed_ver or "unknown"
            console.print(f"\n[bold]Updating {t} ({level}):[/bold] v{old_ver} → v{__version__}")
            if _update_single_tool(t, level):
                updated += 1
            else:
                skipped += 1

    # Summary
    console.print()
    if updated == 0 and already_current > 0 and skipped == 0:
        console.print(f"[green]All installed skills are already at v{__version__} ✓[/green]")
    elif updated > 0:
        console.print(f"[green]✓ Updated {updated} skill(s) to v{__version__}[/green]")
        if skipped > 0:
            console.print(f"[yellow]{skipped} skill(s) failed to update[/yellow]")
    elif skipped > 0:
        console.print(f"[red]✗ {skipped} skill(s) failed to update[/red]")
    else:
        if tool:
            console.print(
                f"[dim]{tool} is not installed. "
                f"Use 'gemcli skill install {tool}' first.[/dim]"
            )
        else:
            console.print("[dim]No installed skills found to update.[/dim]")


@skill.command("show")
def skill_show() -> None:
    """Display the Gemini skill content."""
    data_dir = get_data_dir()
    skill_file = data_dir / "SKILL.md"

    if not skill_file.exists():
        console.print("[red]Error:[/red] SKILL.md not found")
        raise SystemExit(1)

    content = skill_file.read_text(encoding="utf-8")
    console.print(content)
