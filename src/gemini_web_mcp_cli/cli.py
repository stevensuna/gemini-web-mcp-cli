"""CLI entry point for gemcli.

Supports both verb-first and noun-first command styles:
    gemcli chat "hello"          (noun-first)
    gemcli gems list             (noun-first)
    gemcli list gems             (verb-first alias)

All commands call the service layer directly.
"""

from __future__ import annotations

import asyncio
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from typing import NoReturn

import rich_click as click
from loguru import logger
from rich.console import Console
from rich.markdown import Markdown

from gemini_web_mcp_cli import __version__
from gemini_web_mcp_cli.core.client import GeminiClient
from gemini_web_mcp_cli.core.exceptions import AuthError, GeminiError, TokenFactoryError
from gemini_web_mcp_cli.core.profiles import ProfileManager

console = Console()

# Exit code for auth failures that need a (manual) `gemcli login`.
EXIT_AUTH_REQUIRED = 3


def run_async(coro):
    """Run an async function synchronously."""
    return asyncio.run(coro)


def _pause_chrome_daemon_for_login(profile_name: str, chrome_profile_path: str | None):
    """Stop a matching persistent Chrome daemon before interactive login."""
    from gemini_web_mcp_cli.core.chrome_manager import (
        check_daemon_health,
        stop_chrome_daemon,
    )

    info, status = check_daemon_health()
    if not info or status not in {"running", "unresponsive", "zombie"}:
        return None

    same_profile = info.profile_name == profile_name
    from gemini_web_mcp_cli.core.chrome_manager import same_chrome_profile_path

    same_profile_path = same_chrome_profile_path(
        info.chrome_profile_path,
        chrome_profile_path,
    )
    if not same_profile and not same_profile_path:
        return None

    console.print(
        "[yellow]Stopping the Chrome daemon temporarily so login can open "
        "a visible browser window...[/yellow]"
    )
    if stop_chrome_daemon():
        return info

    return None


def _restart_chrome_daemon_after_login(info) -> None:
    """Restore a Chrome daemon that was stopped for login."""
    if info is None:
        return

    from gemini_web_mcp_cli.core.chrome_manager import start_chrome_daemon

    try:
        restarted = start_chrome_daemon(
            profile_name=info.profile_name,
            chrome_profile_path=info.chrome_profile_path,
            headless=info.headless,
            port=info.port,
        )
        console.print(
            f"[dim]Chrome daemon restarted on port {restarted.port}.[/dim]"
        )
    except TokenFactoryError as e:
        try:
            restarted = start_chrome_daemon(
                profile_name=info.profile_name,
                chrome_profile_path=info.chrome_profile_path,
                headless=info.headless,
                port=None,
            )
            console.print(
                "[dim]Chrome daemon restarted on port "
                f"{restarted.port}; the previous port was unavailable.[/dim]"
            )
        except TokenFactoryError as fallback_error:
            console.print(
                "[yellow]Login finished, but the Chrome daemon could not be "
                "restarted automatically: "
                f"{e}; fallback restart also failed: {fallback_error}[/yellow]"
            )


def _fail(e: Exception) -> NoReturn:
    """Print an error and exit non-zero so callers and scripts can detect failure.

    Auth errors exit with EXIT_AUTH_REQUIRED so automations can tell
    "re-login needed" apart from other failures.
    """
    if isinstance(e, AuthError):
        console.print(f"[red]Auth error: {e}[/red]")
        raise SystemExit(EXIT_AUTH_REQUIRED)
    console.print(f"[red]Error: {e}[/red]")
    raise SystemExit(1)


def _validate_model(model: str | None) -> None:
    """Reject unknown model names before auth, uploads, or Chrome startup.

    Applies to every command that takes --model: chat, research, image,
    video, and music. Model names belong to this web route, not
    Relay/Antigravity catalogs. The web picker currently lists 3.5 Flash-Lite,
    3.8 Flash, 3.1 Pro, and 4 Argon. Raises click.ClickException
    with a one-line message so the CLI exits cleanly without a traceback.
    """
    if not model:
        return
    from gemini_web_mcp_cli.core.constants import get_model

    try:
        get_model(model)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from None


def _handle_token_factory_error(e: Exception, command: str = "") -> None:
    """Print a detailed Token Factory error with troubleshooting guidance."""
    console.print(f"[red]Token Factory error: {e}[/red]")
    console.print(
        "[dim]Pro/Thinking, attachments, images, video and music need Chrome to "
        "capture a BotGuard token for this profile.[/dim]"
    )
    console.print("[dim]To diagnose (sends nothing, names the failing stage):[/dim]")
    console.print("[dim]  gemcli -p <profile> doctor --deep[/dim]")
    console.print("[dim]If it fails:[/dim]")
    console.print("[dim]  1. gemcli chrome status[/dim]")
    console.print("[dim]  2. gemcli chrome stop && gemcli chrome start[/dim]")
    console.print("[dim]  3. Try another profile: gemcli -p <other-profile> ...[/dim]")
    console.print(
        "[dim]In a background job (LaunchAgent, cron, SSH), start the Chrome daemon "
        "first from an interactive terminal: gemcli chrome start[/dim]"
    )
    if command == "chat":
        console.print(
            "[dim]  Tip: plain text chat (default Flash model, no files) can run "
            "without Chrome.[/dim]"
        )


def _print_version(ctx, param, value):
    """Callback for --version flag."""
    if not value or ctx.resilient_parsing:
        return
    console.print(f"gemcli version {__version__}")
    ctx.exit()


def _print_ai_docs(ctx, param, value):
    """Callback for --ai flag. Outputs AI-friendly documentation."""
    if not value or ctx.resilient_parsing:
        return
    click.echo(f"""# gemcli CLI - AI Assistant Guide

You are interacting with `gemcli`, a command-line interface for Google Gemini
(gemini.google.com). This documentation teaches you how to use the tool effectively.

## Version

gemcli version {__version__}

---

## CRITICAL: Authentication

Before ANY operation, ensure the user is authenticated.

### First-Time Setup
```bash
gemcli login                     # Opens Chrome; sign in, cookies are captured automatically
gemcli login --manual            # Paste cookies from Chrome DevTools instead
```
If NotebookLM MCP profiles exist, offers to reuse them.

### Check If Authenticated
```bash
gemcli login --check             # Validate the active profile
gemcli login --check --all       # Every profile, read-only (exit 3 if any needs sign-in)
```

### Exit Codes
`0` success, `1` failure, `3` authentication needed. On exit 3: run
`gemcli login --check --all` (read-only) first; retry once on a profile it
reports alive (`-p <profile>`); `stale` -> `gemcli -p <profile> keepalive run`.
Run `gemcli login --profile <name>` only in an interactive session with the
user present, never from a script/cron/LaunchAgent/pipeline (it stops the
Chrome daemon and opens a window nobody sees). Never loop on login; avoid
`--force` (it signs Chrome itself out of the account).

On exit 1, read the message:
- "Profile '...' is busy with another request": parallel jobs on one profile
  queue; retry, use `-p <other>`, or raise GEMCLI_PROFILE_LOCK_TIMEOUT.
- "Gemini did not read the attachment": the reply was withheld (usually
  invented). Retry once, then `gemcli -p <profile> doctor --deep`, then
  another profile.
- TokenFactoryError / "Not retrying without Chrome": run
  `gemcli -p <profile> doctor --deep` (names the failing stage), then
  `gemcli chrome status`.
- "Gemini returned an error instead of an answer": Gemini's generic failure
  reply (usually temporary). Retry once, then use another profile.
- "Chrome sent the prompt through a Gemini request that Token Factory does
  not recognise": the prompt may have been sent once; it was not retried.
  Don't resend blindly. Run `gemcli -p <profile> doctor --deep` and use
  another profile meanwhile.
Never stop/restart Chrome or delete lock files while other jobs may run.

### Keeping Sessions Alive
```bash
gemcli keepalive run                                # Renew every profile + probe token capture
gemcli keepalive run --recover                      # ...and try one-click re-sign-in
gemcli keepalive status                             # alive/stale/DEAD + token capture ok/failed
gemcli keepalive install-agent --every 4 --recover  # macOS: renew every 4 hours
gemcli -p <profile> doctor --deep                   # Prove uploads/media work (sends nothing)
```

---

## Chat
```bash
gemcli chat "What is quantum computing?"
gemcli chat "Explain this" -m gemini-3.1-pro
gemcli chat "Summarize" -o summary.md
gemcli chat "Analyze this" -f document.pdf
gemcli chat "Compare these" -f file1.md -f file2.md
```

## File Upload
```bash
gemcli chat "What is in this image?" -f screenshot.png
gemcli chat "Summarize this document" -f report.pdf
gemcli file upload document.pdf       # Upload and get identifier
```

## Image Generation (Nano Banana Pro / Nano Banana 2)
Requires Chrome for BotGuard token and tool activation. Run `gemcli chrome start` first.
```bash
gemcli image "A red panda in a bamboo forest"
gemcli image "Futuristic city" -o city.png
gemcli image "A vertical movie poster" -A 9:16 -o poster.png
```

Options:
- `--model, -m`: pro (Nano Banana Pro, default) or flash (Nano Banana 2)
- `--aspect, -A`: 1:1, 9:16, 3:4, 4:3, or 16:9
- `--output, -o`: Save to file

## Video Generation (Gemini Omni)
Requires Chrome for BotGuard token and tool activation. Run `gemcli chrome start` first.
Videos take 1-2 minutes; pass -o to wait and auto-download.
```bash
gemcli video "Ocean waves at sunset"
gemcli video "Dancing robot" -o robot.mp4
gemcli video "A vertical story" -O portrait -o story.mp4
gemcli video "A cinematic oner" -m pro -O landscape -o shot.mp4
gemcli video -T "Logo reveal" "NAIDA'S hair salon" -o logo.mp4
gemcli video "Animate this: the balloon drifts at sunrise" -f poster.png -o motion.mp4
```

Options:
- `--orientation, -O`: landscape (16:9, default) or portrait (9:16)
- `--model, -m`: flash (default), pro, lite, or thinking
- `--template, -T`: Create-videos template name (e.g. Anime, Logo reveal,
 8-bit adventure, Storybook)
- `--file, -f`: Reference image/video to upload (repeatable) - e.g. animate a still image.
  Reference generations can take up to ~15 minutes; the CLI waits up to 15 min with -o
- `--output, -o`: Save to file (.mp4)

## Music Generation (Lyria 3.5)
Generate music tracks with vocals, lyrics, instrumentals, and cover art.
Requires Chrome for BotGuard (music always needs Token Factory).
```bash
gemcli music "A comical R&B slow jam about a sock"
gemcli music "Cats playing video games" -s 8-bit -o track.mp3
gemcli music "A chill study beat" -g lo-fi -L short
gemcli music "An upbeat ad jingle" -V vocals -g pop -T "Brand jingle" -o jingle.mp3
gemcli music --list-styles                  # Show all 16 legacy style presets
```

Options:
- `--length, -L`: short or standard
- `--vocals, -V`: custom (from prompt), vocals (vocals on), or instrumental
- `--genre, -g`: pop, hip-hop and rap, rock, k-pop, latin, electronic, r&b,
  country, afrobeats, reggae, jazz and blues, classical, folk, lo-fi, acoustic,
  cinematic, ambient
- `--template, -T`: music template (e.g. Soundscape, Intro music, Brand jingle,
  Rap battle; 24 templates)
- `--style, -s`: legacy style preset (e.g., 8-bit, k-pop, cinematic, emo, afropop)
- `--output, -o`: Save to file (.mp3 for audio, .mp4 for video)
- `--format, -f`: Output format: audio (default) or video (MP4 with cover art)
- `--list-styles`: Show all available legacy style presets and exit

Available Style Presets: 90s-rap, latin-pop, folk-ballad, 8-bit, workout, reggaeton,
rnb-romance, kawaii-metal, cinematic, emo, afropop, forest-bath, k-pop,
birthday-roast, folk-a-cappella, bad-music.

Aliases: rap, latin, folk, chiptune, edm, rnb, r&b, kawaii, metal, orchestral,
ambient, kpop, birthday, roast, country, acappella, bad.

## Deep Research
```bash
gemcli research "Latest AI advances in 2026"
```

## Usage Limits
Check per-feature usage before generating. Requires Chrome for browser cookies (Token Factory).
```bash
gemcli limits
gemcli -p <profile> limits        # Check another account
```
Output starts with the Account/Profile, then grouped usage rows: the shared
plan pool (size depends on the plan; reset time per row) used by most features, plus
feature-specific rows for Video (Gemini Omni) and Deep Think. Live view:
https://gemini.google.com/usage
When a media tool is disabled (100% used), switch profiles to keep working:
```bash
gemcli -p <other-profile> video "A drone shot over a lake" -O landscape -o clip.mp4
gemcli profile switch <other-profile>
```

## Hack Claude (Launch Claude Code via Gemini)
```bash
gemcli hack claude                    # Launch with Gemini Flash (default)
gemcli hack claude --model gemini-pro # Use Gemini Pro
gemcli hack claude -p "fix this bug" # Pass args to Claude Code
```

## Gems (Custom System Prompts)
```bash
gemcli gems list
gemcli gems create --name "Reviewer" --prompt "You are a code reviewer..."
gemcli gems delete <gem_id>
```

## Profile Management
Profiles are separate Gemini accounts. Use -p to run any command as another
profile, or switch the default. Use this to flip accounts when quota runs out.
```bash
gemcli profile list              # List all profiles
gemcli profile switch <name>     # Switch active profile
gemcli profile create <name>     # Create new profile
gemcli profile delete <name>     # Delete profile
gemcli profile sources           # Show profile sources (gemcli + NotebookLM)
gemcli -p <name> limits          # Check another account's quota
gemcli -p <name> <command>       # Run any command as that profile
```

## MCP Setup (configure AI tools)
```bash
gemcli setup list                # Show configured clients
gemcli setup add cursor          # Add to Cursor
gemcli setup add codex            # Add to Codex
gemcli setup add all             # Interactive — detect and configure all tools
gemcli setup remove cursor       # Remove from Cursor
gemcli setup remove all          # Remove from all configured tools
```

## Configuration
```bash
gemcli config show               # Show all settings
gemcli config get active_profile # Get specific value
gemcli config set key value      # Set a value
```

## Diagnostics
```bash
gemcli doctor                    # Check installation and saved auth
gemcli doctor --verbose          # Detailed diagnostics
gemcli -p <profile> doctor --deep  # Live path: BotGuard token capture + tiny upload
```

## Environment
- GEMCLI_PROFILE_LOCK_TIMEOUT: seconds a job waits for a busy profile (300)
- GEMCLI_CHROME_START_TIMEOUT: seconds for the Chrome daemon to start (30)
- GEMCLI_BROWSER: browser name or path to a Chromium binary
- GEMCLI_ATTACHMENT_CHECK=0: return replies that say the file couldn't be opened

## Skills (teach AI tools to use gemcli)
```bash
gemcli skill list                # Show installation status
gemcli skill install claude-code # Install for Claude Code
gemcli skill install cursor      # Install for Cursor
gemcli skill update              # Update all outdated skills
gemcli skill show                # Display skill content
```

## Available Models
- gemini-3.8-flash (default fast model; gemini-3.7-flash still works)
- gemini-4-argon
- gemini-3.1-pro
- gemini-3.5-flash-lite

Short names: flash, lite, pro, argon, thinking. Thinking level is
`low`, `medium`, or `high` (`--thinking-level` or `/thinking`). High is the
old Extended thinking toggle (`--extended-thinking`). `--task` uses the
Chat/Task control.

These are the Gemini Web catalog. Relay/Antigravity model IDs are not
available here; every command that takes --model rejects unknown names with
a one-line error before authentication.

## Verb-First Aliases
These aliases let you use verb-first style:
```bash
gemcli list gems                 # = gemcli gems list
gemcli list profiles             # = gemcli profile list
gemcli list skills               # = gemcli skill list
gemcli create gem --name ...     # = gemcli gems create --name ...
gemcli delete gem <id>           # = gemcli gems delete <id>
gemcli install skill <tool>      # = gemcli skill install <tool>
gemcli update skill [tool]       # = gemcli skill update [tool]
```

## Global Options
- `--profile, -p`: Use a specific profile for this command
- `--verbose, -v`: Enable debug logging
- `--version`: Show version
- `--ai`: Output this AI-friendly documentation
""")
    ctx.exit()


# ── Global options ──────────────────────────────────────────────────────────


def _install_completion(ctx, param, value):
    """Callback for --install-completion flag."""
    if not value or ctx.resilient_parsing:
        return

    shell = os.environ.get("SHELL", "")
    if "zsh" in shell:
        script = 'eval "$(_GEMCLI_COMPLETE=zsh_source gemcli)"'
        rc_file = Path.home() / ".zshrc"
        shell_name = "zsh"
    elif "bash" in shell:
        script = 'eval "$(_GEMCLI_COMPLETE=bash_source gemcli)"'
        rc_file = Path.home() / ".bashrc"
        shell_name = "bash"
    elif "fish" in shell:
        script = '_GEMCLI_COMPLETE=fish_source gemcli | source'
        rc_file = Path.home() / ".config" / "fish" / "completions" / "gemcli.fish"
        shell_name = "fish"
    else:
        console.print(f"[yellow]Unknown shell: {shell}[/yellow]")
        console.print("Supported: bash, zsh, fish")
        ctx.exit(1)

    marker = "# gemcli completion"
    if rc_file.exists() and marker in rc_file.read_text(encoding="utf-8"):
        console.print(f"[green]Completion already installed in {rc_file}[/green]")
        ctx.exit()

    with open(rc_file, "a") as f:
        f.write(f"\n{marker}\n{script}\n")
    console.print(f"[green]Installed {shell_name} completion in {rc_file}[/green]")
    console.print(f"Restart your shell or run: source {rc_file}")
    ctx.exit()


def _show_completion(ctx, param, value):
    """Callback for --show-completion flag."""
    if not value or ctx.resilient_parsing:
        return

    shell = os.environ.get("SHELL", "")
    if "zsh" in shell:
        click.echo('eval "$(_GEMCLI_COMPLETE=zsh_source gemcli)"')
    elif "bash" in shell:
        click.echo('eval "$(_GEMCLI_COMPLETE=bash_source gemcli)"')
    elif "fish" in shell:
        click.echo('_GEMCLI_COMPLETE=fish_source gemcli | source')
    else:
        click.echo(f"# Unknown shell: {shell}")
        click.echo('# For bash: eval "$(_GEMCLI_COMPLETE=bash_source gemcli)"')
        click.echo('# For zsh:  eval "$(_GEMCLI_COMPLETE=zsh_source gemcli)"')
        click.echo('# For fish: _GEMCLI_COMPLETE=fish_source gemcli | source')
    ctx.exit()


@click.group()
@click.option("--profile", "-p", default=None, help="Profile to use (overrides active)")
@click.option("--verbose", is_flag=True, help="Enable verbose logging")
@click.option("--version", is_flag=True, callback=_print_version, expose_value=False,
              is_eager=True, help="Show version and exit")
@click.option("--ai", is_flag=True, callback=_print_ai_docs, expose_value=False,
              is_eager=True, help="Output AI-friendly documentation for this CLI")
@click.option("--install-completion", is_flag=True, callback=_install_completion,
              expose_value=False, is_eager=True,
              help="Install shell completion for the current shell")
@click.option("--show-completion", is_flag=True, callback=_show_completion,
              expose_value=False, is_eager=True,
              help="Show completion script for the current shell")
@click.pass_context
def cli(ctx, profile, verbose):
    """gemcli - CLI for the Gemini web interface."""
    ctx.ensure_object(dict)
    ctx.obj["profile"] = profile
    if not verbose:
        logger.remove()
        logger.add(sys.stderr, level="WARNING")


# ── Login ───────────────────────────────────────────────────────────────────


@cli.command()
@click.option("--profile", "-p", default=None, help="Profile name to login to")
@click.option("--check", is_flag=True, help="Only check if current auth is valid")
@click.option(
    "--manual", "-m", is_flag=True,
    help="Manually paste cookies instead of automated Chrome login",
)
@click.option(
    "--force", "-f", is_flag=True,
    help="Force a fresh login by clearing existing cookies",
)
@click.option(
    "--all", "all_profiles", is_flag=True,
    help="With --check: check every profile (read-only, no Chrome launched)",
)
@click.pass_context
def login(ctx, profile, check, manual, force, all_profiles):
    """Authenticate with Gemini.

    By default, launches Chrome and extracts cookies automatically (same as NotebookLM MCP).
    Use --manual to paste cookies from DevTools instead.
    Use --check to validate existing auth without re-login.
    Use --check --all to check every profile at once (exit 3 if any needs sign-in;
    "stale" means only the saved cookie copy is out of date).
    """
    if check and all_profiles:
        _run_health(None, recover=False, check_only=True, as_json=False)
        return

    pm = ProfileManager()
    profile_name = profile or ctx.obj.get("profile") or pm.get_active_profile()

    # --check: just validate auth, don't re-login
    if check:
        from gemini_web_mcp_cli.core.auth import AuthManager

        auth = AuthManager(pm, profile_name=profile_name)
        state = auth.load()

        if not state.is_valid:
            console.print("[red]Not authenticated.[/red] Run [bold]gemcli login[/bold].")
            raise SystemExit(1)

        console.print(f"[bold]Profile:[/bold] {profile_name}")
        if state.email:
            console.print(f"[bold]Account:[/bold] {state.email}")
        console.print(f"[bold]Has cookies:[/bold] {'yes' if state.cookies else 'no'}")
        console.print(f"[bold]Has token:[/bold] {'yes' if state.tokens.snlm0e else 'no'}")

        console.print("Validating tokens...")
        try:
            run_async(auth.refresh_tokens())
            if auth.state.email and not state.email:
                console.print(f"[bold]Account:[/bold] {auth.state.email}")
            console.print("[green]Authentication is valid.[/green]")
        except AuthError as e:
            console.print(f"[yellow]Tokens may be expired: {e}[/yellow]")
            console.print("Run [bold]gemcli login[/bold] to refresh.")
            raise SystemExit(1)
        except Exception as e:
            console.print(f"[red]Validation failed: {e}[/red]")
            console.print("Run [bold]gemcli login[/bold] to refresh.")
            raise SystemExit(1)
        return

    # First-run: detect NotebookLM MCP profiles and let the user decide
    chrome_profile_path = None
    if pm.is_first_run() and pm.has_nlm_profiles():
        nlm_profiles = pm._list_nlm_profiles()
        console.print(
            "\n[bold]NotebookLM MCP profiles detected![/bold]\n"
            "\nYou have existing NotebookLM MCP profiles that use the same\n"
            "Google account. You can reuse them or create a fresh profile.\n"
        )

        # Show numbered options for NLM profiles + fresh option
        for i, name in enumerate(nlm_profiles, 1):
            console.print(f"  [bold]{i})[/bold] Use NotebookLM profile: {name}")
        all_idx = len(nlm_profiles) + 1
        fresh_idx = len(nlm_profiles) + 2
        console.print(f"  [bold]{all_idx})[/bold] Use all NotebookLM profiles (import all)")
        console.print(f"  [bold]{fresh_idx})[/bold] Create a new profile just for Gemini\n")

        valid_choices = [str(i) for i in range(1, fresh_idx + 1)]
        while True:
            choice = click.prompt("Your choice", default="1")
            choice = choice.strip()
            if choice in valid_choices:
                break
            console.print(f"[red]Invalid choice. Please enter {', '.join(valid_choices)}[/red]")
        choice_num = int(choice)

        if choice_num <= len(nlm_profiles):
            # Use a specific NLM profile
            chosen = nlm_profiles[choice_num - 1]
            pm.set_active_profile(chosen)
            profile_name = chosen
            chrome_profile_path = pm.get_chrome_profile_path(chosen)
            console.print(f"\n[green]Using NotebookLM profile '{chosen}'.[/green]\n")
        elif choice_num == all_idx:
            # Import all -- set the first one as active
            profile_name = nlm_profiles[0]
            pm.set_active_profile(profile_name)
            chrome_profile_path = pm.get_chrome_profile_path(profile_name)
            console.print("\n[green]All NotebookLM profiles are now available:[/green]")
            for name in nlm_profiles:
                marker = " [green]<- active[/green]" if name == profile_name else ""
                console.print(f"  {name}{marker}")
            console.print()
        else:
            # Fresh profile
            profile_name = click.prompt("Profile name", default="default")
            console.print(f"\nCreating fresh profile: {profile_name}\n")

    # Get Chrome profile path if not already set
    if not chrome_profile_path:
        chrome_profile_path = pm.get_chrome_profile_path(profile_name)

    # ── Manual mode: paste cookies ──────────────────────────────────────
    if manual:
        console.print(
            f"[bold]Manual login for profile:[/bold] {profile_name}\n"
            "\nTo authenticate, provide your Gemini cookies:\n"
            "1. Open https://gemini.google.com in Chrome\n"
            "2. Open DevTools (F12) > Application > Cookies\n"
            "3. Copy the values of __Secure-1PSID and __Secure-1PSIDTS\n"
        )

        psid = click.prompt("__Secure-1PSID")
        psidts = click.prompt("__Secure-1PSIDTS")

        from gemini_web_mcp_cli.core.auth import AuthManager

        auth = AuthManager(pm, profile_name=profile_name)
        auth.save_cookies({"__Secure-1PSID": psid, "__Secure-1PSIDTS": psidts})

        console.print(f"\n[green]Cookies saved for profile '{profile_name}'.[/green]")
        console.print("Fetching tokens...")

        try:
            run_async(auth.refresh_tokens())
            console.print("[green]Authentication successful![/green]")
        except AuthError as e:
            console.print(f"[red]Token extraction failed: {e}[/red]")
        return

    # ── Automated mode: launch Chrome via CDP ───────────────────────────
    # Detect if this is a new/unauthenticated profile — if so, force a
    # visible Chrome window so the user can sign into a different account.
    auth_data = pm.load_auth(profile_name)
    is_new_profile = not auth_data or not auth_data.get("cookies", {}).get("__Secure-1PSID")

    if force:
        console.print(
            "[yellow]Force flag used: Clearing existing cookies "
            "to force a fresh login...[/yellow]"
        )
        is_new_profile = True
        pm.save_auth({}, profile_name)
        if chrome_profile_path:
            from pathlib import Path
            cookies_file = Path(chrome_profile_path) / "Default" / "Cookies"
            journal_file = Path(chrome_profile_path) / "Default" / "Cookies-journal"
            if cookies_file.exists():
                cookies_file.unlink()
            if journal_file.exists():
                journal_file.unlink()

    console.print(f"[bold]Profile:[/bold]        {profile_name}")
    if chrome_profile_path:
        console.print(f"[bold]Chrome profile:[/bold] {chrome_profile_path}")

    if is_new_profile:
        console.print()
        console.print(
            "[bold yellow]New profile — opening browser so you can sign in.[/bold yellow]\n"
            "Sign in with your Google account in the browser window.\n"
            "gemcli will detect the login automatically (up to 5 minutes).\n"
        )
    else:
        from gemini_web_mcp_cli.core.cdp import get_browser_display_name
        browser_name = get_browser_display_name()
        console.print()
        console.print(f"Launching {browser_name} to extract cookies automatically...\n")

    def _on_waiting():
        console.print(
            "[yellow]Waiting for you to log in...[/yellow]\n"
            "Sign in with your Google account in the browser window.\n"
            "gemcli will detect the login automatically (up to 5 minutes).\n"
        )

    from contextlib import ExitStack

    from gemini_web_mcp_cli.core.locks import ProfileBusy, profile_lock

    # Login stops this profile's Chrome daemon and opens its own Chrome, so it
    # waits for in-flight requests, and new ones queue until it is done.
    session_lock = ExitStack()
    try:
        session_lock.enter_context(profile_lock(profile_name))
    except ProfileBusy as e:
        _fail(e)
    paused_chrome_daemon = _pause_chrome_daemon_for_login(
        profile_name,
        chrome_profile_path,
    )
    try:
        try:
            from gemini_web_mcp_cli.core.cdp import extract_cookies_via_cdp

            result = extract_cookies_via_cdp(
                profile_name=profile_name,
                chrome_profile_path=chrome_profile_path,
                on_waiting_for_login=_on_waiting,
                force_new_session=is_new_profile,
            )

            cookies = result["cookies"]
            tokens = result.get("tokens", {})
            email = result.get("email", "")
            final_chrome_path = result.get("chrome_profile_path") or chrome_profile_path

            from gemini_web_mcp_cli.core.auth import AuthManager, AuthState, AuthTokens

            auth = AuthManager(pm, profile_name=profile_name)
            auth._state = AuthState(
                cookies=cookies,
                tokens=AuthTokens(
                    snlm0e=tokens.get("snlm0e", ""),
                    cfb2h=tokens.get("cfb2h", ""),
                    fdrfje=tokens.get("fdrfje", ""),
                ),
                chrome_profile_path=final_chrome_path,
                email=email,
            )
            auth.save()

            if tokens.get("snlm0e"):
                console.print("[green]Authentication successful![/green]")
                if email:
                    console.print(f"[dim]Account: {email}[/dim]")
                console.print(
                    f"[dim]Cookies and tokens saved for profile '{profile_name}'.[/dim]"
                )
            else:
                console.print("[yellow]Cookies saved but session token (SNlM0e) "
                              "not found.[/yellow]")
                console.print("Try [bold]gemcli login --force[/bold] to start a "
                              "fresh login session.")

        except AuthError as e:
            console.print(f"[red]Automated login failed: {e}[/red]")
            console.print("\nFalling back to manual mode...")
            console.print("You can also run [bold]gemcli login --manual[/bold] directly.\n")

            psid = click.prompt("__Secure-1PSID")
            psidts = click.prompt("__Secure-1PSIDTS")

            from gemini_web_mcp_cli.core.auth import AuthManager

            auth = AuthManager(pm, profile_name=profile_name)
            auth.save_cookies({"__Secure-1PSID": psid, "__Secure-1PSIDTS": psidts})

            console.print("Fetching tokens...")
            try:
                run_async(auth.refresh_tokens())
                console.print("[green]Authentication successful![/green]")
            except AuthError as e2:
                console.print(f"[red]Token extraction failed: {e2}[/red]")
    finally:
        _restart_chrome_daemon_after_login(paused_chrome_daemon)
        session_lock.close()


# ── Profile management ──────────────────────────────────────────────────────


@cli.group()
def profile():
    """Manage authentication profiles."""
    pass


@profile.command("list")
def profile_list():
    """List all profiles (shows both gemcli-native and NotebookLM shared)."""
    pm = ProfileManager()
    profiles = pm.list_profiles_detailed()
    active = pm.get_active_profile()

    if not profiles:
        console.print("No profiles found. Run [bold]gemcli login[/bold] to create one.")
        return

    for p in profiles:
        active_marker = " [green]<- active[/green]" if p.name == active else ""
        source_marker = " [dim](NotebookLM)[/dim]" if p.source == "nlm" else ""
        email_marker = ""
        auth_data = pm.load_auth(p.name)
        if auth_data.get("email"):
            email_marker = f" [dim]({auth_data['email']})[/dim]"
        console.print(f"  {p.name}{email_marker}{source_marker}{active_marker}")


@profile.command("switch")
@click.argument("name")
def profile_switch(name):
    """Switch the active profile."""
    pm = ProfileManager()
    try:
        pm.set_active_profile(name)
        console.print(f"[green]Switched to profile: {name}[/green]")
    except GeminiError as e:
        console.print(f"[red]{e}[/red]")


@profile.command("create")
@click.argument("name")
def profile_create(name):
    """Create a new empty profile."""
    pm = ProfileManager()
    try:
        pm.create_profile(name)
        console.print(f"[green]Created profile: {name}[/green]")
    except GeminiError as e:
        console.print(f"[red]{e}[/red]")


@profile.command("delete")
@click.argument("name")
@click.confirmation_option(prompt="Are you sure you want to delete this profile?")
def profile_delete(name):
    """Delete a profile."""
    pm = ProfileManager()
    try:
        pm.delete_profile(name)
        console.print(f"[green]Deleted profile: {name}[/green]")
    except GeminiError as e:
        console.print(f"[red]{e}[/red]")


@profile.command("rename")
@click.argument("old_name")
@click.argument("new_name")
def profile_rename(old_name, new_name):
    """Rename a profile.

    Renames the profile directory, Chrome profile, Token Factory profile,
    and updates auth.json and config.json as needed.

    Example:
        gemcli profile rename debug production
    """
    pm = ProfileManager()
    try:
        pm.rename_profile(old_name, new_name)
        console.print(f"[green]Renamed profile: {old_name} → {new_name}[/green]")
    except GeminiError as e:
        console.print(f"[red]{e}[/red]")


@profile.command("sources")
def profile_sources():
    """Show where profiles come from (gemcli-native vs NotebookLM shared)."""
    pm = ProfileManager()
    profiles = pm.list_profiles_detailed()

    if not profiles:
        console.print("No profiles found.")
        return

    gemcli_count = sum(1 for p in profiles if p.source == "gemcli")
    nlm_count = sum(1 for p in profiles if p.source == "nlm")

    console.print("\n[bold]Profile sources:[/bold]")
    console.print(f"  gemcli-native: {gemcli_count} profiles at ~/.gemini-web-mcp-cli/profiles/")
    console.print(f"  NotebookLM:    {nlm_count} profiles at ~/.notebooklm-mcp-cli/profiles/")
    console.print("\nNotebookLM profiles are live -- new NLM profiles automatically appear here.")


# ── Chat ────────────────────────────────────────────────────────────────────


CHAT_SLASH_COMMANDS_HELP = """
[bold]Slash commands:[/bold]
  /model <name>   Switch model (pro, flash, gemini-3.8-flash, gemini-4-argon, thinking)
  /model          Show current model
  /thinking on|off|low|medium|high   Set thinking level (on = high)
  /task on|off    Send later messages as a Task or a Chat
  /verify         Show server-confirmed model from last response
  /new            Start a new conversation
  /save <file>    Save conversation to file
  /history        Show conversation turns so far
  /help           Show this help
  /quit           Exit chat (also: Ctrl+C, Ctrl+D)
""".strip()


@cli.command()
@click.argument("prompt", required=False, default=None)
@click.option("--model", "-m", default=None,
              help="Model: pro, flash, gemini-3.8-flash, gemini-4-argon, thinking (or full name)")
@click.option(
    "--extended-thinking/--no-extended-thinking",
    default=None,
    help="Enable or disable Thinking level High (formerly Extended thinking).",
)
@click.option(
    "--thinking-level",
    type=click.Choice(["low", "medium", "high"], case_sensitive=False),
    default=None,
    help="Thinking level: low, medium, or high. Overrides --extended-thinking.",
)
@click.option(
    "--task",
    is_flag=True,
    help="Send the prompt as a Task (the agent mode on the Chat/Task control).",
)
@click.option("--gem", "gem_id", default=None,
              help="Chat with a specific gem by its ID (from 'gemcli gems list')")
@click.option("--output", "-o", default=None, help="Save response to file")
@click.option("--new", "new_conversation", is_flag=True, help="Force a new conversation")
@click.option(
    "--file", "-f", "files", multiple=True,
    help="Attach files to the prompt (can be used multiple times)"
)
@click.pass_context
def chat(ctx, prompt, model, extended_thinking, thinking_level, task, gem_id, output,
         new_conversation, files):
    """Chat with Gemini. Interactive mode if no prompt given.

    \b
    Single message:
        gemcli chat "What is 2+2?"
        gemcli chat "Explain this" -m pro
        gemcli chat "Summarize" -o summary.md
        gemcli chat "Analyze this" -f document.pdf
        gemcli chat "Hello" --gem <gem_id>
    \b
    Interactive mode:
        gemcli chat
        gemcli chat -m thinking
    \b
    In interactive mode, use /help to see slash commands.
    """
    profile_name = ctx.obj.get("profile")

    # Resolve model: explicit flag > config default > built-in default
    pm = ProfileManager()
    if not model:
        cfg = pm._read_config()
        model = cfg.get("default_model")

    # Model names belong to this web route, not Relay/Antigravity catalogs.
    # Reject locally before auth, uploads, or starting an interactive session.
    _validate_model(model)

    files_list = list(files) if files else None

    if prompt or files_list:
        # Single message mode (if files are provided without prompt, we still send)
        prompt = prompt or "Describe the attached files."
        _chat_single(
            profile_name,
            prompt,
            model,
            output,
            files_list,
            gem_id=gem_id,
            extended_thinking=extended_thinking,
            thinking_level=thinking_level,
            task=task,
        )
    else:
        # Interactive mode
        _chat_interactive(
            profile_name, model, extended_thinking, thinking_level, task=task
        )


def _chat_single(
    profile_name,
    prompt,
    model,
    output,
    files=None,
    gem_id=None,
    extended_thinking=None,
    thinking_level=None,
    task=False,
):
    """Send a single chat message."""

    async def _run():
        async with GeminiClient(profile_name=profile_name) as client:
            from gemini_web_mcp_cli.services.chat import ChatService

            svc = ChatService(client)

            if files:
                console.print(f"[dim]Uploading {len(files)} file(s)...[/dim]")

            if gem_id:
                console.print(f"[dim]Using gem: {gem_id}[/dim]")

            response = await svc.send(
                prompt,
                model=model,
                files=files,
                gem_id=gem_id,
                extended_thinking=extended_thinking,
                thinking_level=thinking_level,
                task=task,
            )

            if output:
                Path(output).write_text(response.text or "", encoding="utf-8")
                console.print(f"[green]Response saved to {output}[/green]")
            else:
                if response.text:
                    console.print(Markdown(response.text))
                else:
                    console.print("[yellow]No text in response.[/yellow]")

                if response.has_images:
                    images = response.candidates[0].generated_images
                    if images:
                        count = len(images)
                        console.print(
                            f"\n[bold magenta]Generated {count} image(s):[/bold magenta]"
                        )
                        for img in images:
                            try:
                                url = img[0][3][3] if isinstance(img, list) else str(img)
                                console.print(f"[link={url}]{url}[/link]")
                            except (IndexError, TypeError):
                                pass

    try:
        run_async(_run())
    except TokenFactoryError as e:
        _handle_token_factory_error(e, command="chat")
        raise SystemExit(1)
    except GeminiError as e:
        _fail(e)


def _chat_interactive(
    profile_name,
    initial_model,
    initial_extended_thinking=None,
    initial_thinking_level=None,
    task=False,
):
    """Interactive chat REPL with slash commands."""
    from gemini_web_mcp_cli.core.constants import get_model

    current_model = initial_model
    extended_thinking = initial_extended_thinking
    thinking_level = initial_thinking_level
    composer_task = task
    model_display = current_model or "default"
    history: list[dict] = []
    last_server_model_hash: str | None = None
    last_server_model_label: str | None = None

    async def _run():
        nonlocal current_model, extended_thinking, thinking_level, composer_task
        nonlocal model_display, history
        nonlocal last_server_model_hash, last_server_model_label

        async with GeminiClient(profile_name=profile_name) as client:
            from gemini_web_mcp_cli.services.chat import ChatService

            svc = ChatService(client)

            console.print("[bold]Gemini Interactive Chat[/bold]")
            console.print(f"Model: {model_display} | Type /help for commands | /quit to exit\n")

            while True:
                try:
                    user_input = console.input("[bold green]> [/bold green]").strip()
                except (EOFError, KeyboardInterrupt):
                    console.print("\n[dim]Goodbye![/dim]")
                    break

                if not user_input:
                    continue

                # ── Slash commands ──────────────────────────────────
                if user_input.startswith("/"):
                    parts = user_input.split(maxsplit=1)
                    cmd = parts[0].lower()
                    arg = parts[1].strip() if len(parts) > 1 else ""

                    if cmd in ("/quit", "/exit", "/q"):
                        console.print("[dim]Goodbye![/dim]")
                        break

                    elif cmd == "/help":
                        console.print(CHAT_SLASH_COMMANDS_HELP)

                    elif cmd == "/model":
                        if arg:
                            try:
                                get_model(arg)
                                current_model = arg
                                model_display = arg
                                console.print(f"[green]Switched to model: {arg}[/green]")
                                if arg in (
                                    "pro", "thinking", "argon",
                                    "gemini-4-argon", "gemini-4",
                                ):
                                    console.print(
                                        "[dim]Pro, Thinking, and Argon require Chrome — "
                                        "first message may be slower.[/dim]"
                                    )
                            except ValueError as e:
                                console.print(f"[red]{e}[/red]")
                        else:
                            console.print(f"Current model: {model_display}")

                    elif cmd in ("/thinking", "/think"):
                        choice = arg.lower()
                        if choice in ("on", "enable", "enabled", "true", "high"):
                            thinking_level = "high"
                            extended_thinking = None
                            console.print("[green]Thinking level: high.[/green]")
                        elif choice in ("off", "disable", "disabled", "false", "low"):
                            thinking_level = "low"
                            extended_thinking = None
                            console.print("[green]Thinking level: low.[/green]")
                        elif choice == "medium":
                            thinking_level = "medium"
                            extended_thinking = None
                            console.print("[green]Thinking level: medium.[/green]")
                        else:
                            active = thinking_level or (
                                "high" if extended_thinking is True
                                else "low" if extended_thinking is False
                                else "default"
                            )
                            console.print(f"Thinking level: {active}")

                    elif cmd == "/task":
                        if arg.lower() in ("on", "task", "true", "enable", "enabled"):
                            composer_task = True
                            console.print("[green]Composer: Task.[/green]")
                        elif arg.lower() in ("off", "chat", "false", "disable", "disabled"):
                            composer_task = False
                            console.print("[green]Composer: Chat.[/green]")
                        else:
                            console.print(
                                f"Composer: {'Task' if composer_task else 'Chat'}"
                            )

                    elif cmd == "/verify":
                        if last_server_model_label:
                            console.print(
                                f"[bold]Server confirmed:[/bold] {last_server_model_label} "
                                f"({last_server_model_hash})"
                            )
                        else:
                            console.print(
                                "[dim]No server model info yet. Send a message first.[/dim]"
                            )

                    elif cmd == "/new":
                        svc.reset()
                        history.clear()
                        last_server_model_hash = None
                        last_server_model_label = None
                        console.print("[green]Started new conversation.[/green]")

                    elif cmd == "/save":
                        if not arg:
                            console.print("[red]Usage: /save <filename>[/red]")
                        elif not history:
                            console.print("[yellow]No conversation to save.[/yellow]")
                        else:
                            text = "\n\n".join(
                                f"**You:** {h['prompt']}\n\n**Gemini:** {h['response']}"
                                for h in history
                            )
                            Path(arg).write_text(text, encoding="utf-8")
                            console.print(f"[green]Saved {len(history)} turns to {arg}[/green]")

                    elif cmd == "/history":
                        if not history:
                            console.print("[dim]No conversation history yet.[/dim]")
                        else:
                            for i, h in enumerate(history, 1):
                                console.print(f"[dim]Turn {i}:[/dim] {h['prompt'][:60]}...")

                    else:
                        console.print(f"[red]Unknown command: {cmd}[/red] (try /help)")

                    continue

                # ── Regular chat message ────────────────────────────
                try:
                    response = await svc.send(
                        user_input,
                        model=current_model,
                        extended_thinking=extended_thinking,
                        thinking_level=thinking_level,
                        task=composer_task,
                    )

                    # Track server-confirmed model
                    if response.server_model_label:
                        last_server_model_hash = response.server_model_hash
                        last_server_model_label = response.server_model_label

                    if response.text:
                        # Show server-confirmed model tag
                        model_tag = ""
                        if response.server_model_label:
                            model_tag = f"[dim][{response.server_model_label}][/dim] "

                        console.print()
                        if model_tag:
                            console.print(model_tag)
                        console.print(Markdown(response.text))
                        console.print()
                        history.append({
                            "prompt": user_input,
                            "response": response.text,
                        })
                    else:
                        console.print("[yellow]No text in response.[/yellow]\n")

                    if response.has_images:
                        images = response.candidates[0].generated_images
                        if images:
                            count = len(images)
                            console.print(
                                f"[bold magenta]Generated {count} image(s):[/bold magenta]"
                            )
                            for img in images:
                                try:
                                    url = img[0][3][3] if isinstance(img, list) else str(img)
                                    console.print(f"[link={url}]{url}[/link]")
                                except (IndexError, TypeError):
                                    pass
                            console.print()

                except TokenFactoryError as e:
                    _handle_token_factory_error(e, command="chat")
                except GeminiError as e:
                    console.print(f"[red]Error: {e}[/red]\n")

    try:
        run_async(_run())
    except TokenFactoryError as e:
        _handle_token_factory_error(e, command="chat")
        raise SystemExit(1)
    except GeminiError as e:
        _fail(e)


# ── Image ───────────────────────────────────────────────────────────────────


@cli.command()
@click.argument("prompt")
@click.option("--model", "-m", default=None,
              help="Model: pro (Nano Banana Pro, default), flash (Nano Banana 2)")
@click.option("--aspect", "-A", default=None,
              type=click.Choice(["1:1", "9:16", "3:4", "4:3", "16:9"], case_sensitive=False),
              help="Image aspect ratio (default: model decides)")
@click.option("--output", "-o", default=None, help="Save generated image to file")
@click.pass_context
def image(ctx, prompt, model, aspect, output):
    """Generate an image from a text prompt.

    Uses Nano Banana Pro (Gemini 3 Pro Image) by default. Pass -m flash for
    Nano Banana 2 (Gemini 3.1 Flash Image) if your account supports Flash image gen.

    \b
    Examples:
        gemcli image "A serene mountain landscape at sunset"
        gemcli image "A vertical poster" -A 9:16 -o poster.png
        gemcli image "A wide banner" -A 16:9 -m flash
    """
    profile_name = ctx.obj.get("profile")
    _validate_model(model)

    async def _image():
        async with GeminiClient(profile_name=profile_name) as client:
            from gemini_web_mcp_cli.services.image import ImageService

            svc = ImageService(client)
            response = await svc.generate(prompt, model=model, aspect=aspect)

            if response.has_images:
                images = response.candidates[0].generated_images
                if images and len(images) > 0:
                    url = images[0][0][3][3] if isinstance(images[0], list) else str(images[0])

                    # Determine output path (explicit or temp file)
                    if output:
                        out_path = output
                    else:
                        import tempfile
                        out_path = tempfile.mktemp(suffix=".png", prefix="gemini_")

                    saved = await svc.download(url, out_path)
                    console.print(f"[green]Image saved to {saved}[/green]")

                    # Auto-open image for viewing when no explicit output path
                    if not output:
                        import platform
                        import subprocess as sp
                        system = platform.system()
                        try:
                            if system == "Darwin":
                                sp.Popen(["open", str(saved)])
                            elif system == "Linux":
                                sp.Popen(["xdg-open", str(saved)])
                            elif system == "Windows":
                                sp.Popen(["start", str(saved)], shell=True)
                        except Exception:
                            pass  # Non-fatal if viewer can't open
                else:
                    console.print("[yellow]Image generated but no URL found.[/yellow]")

                # Also show any text response alongside the image
                if response.text:
                    console.print(Markdown(response.text))
            elif response.text:
                # Detect silent image generation failure — Gemini returns text
                # like "please try again with 'Create Image' enabled" when the
                # model doesn't support image gen on this account (Bug 2).
                text_lower = response.text.lower()
                image_fail_hints = [
                    "create image", "image generation", "generate images",
                    "enable image", "i can't create", "i cannot create",
                    "i'm not able to create", "i am not able to create",
                ]
                if any(hint in text_lower for hint in image_fail_hints):
                    used_model = model or "pro"
                    console.print(
                        f"[red]Image generation failed with model '{used_model}'.[/red]"
                    )
                    console.print(Markdown(response.text))
                    if used_model != "pro":
                        console.print(
                            "\n[yellow]Tip: Image generation usually requires "
                            "Gemini Advanced. Try: gemcli image \"...\" -m pro[/yellow]"
                        )
                else:
                    console.print(Markdown(response.text))
            else:
                console.print("[yellow]No images generated.[/yellow]")

    try:
        run_async(_image())
    except TokenFactoryError as e:
        _handle_token_factory_error(e)
        raise SystemExit(1)
    except (AuthError, GeminiError) as e:
        _fail(e)


# ── Video ───────────────────────────────────────────────────────────────────


@cli.command()
@click.argument("prompt", required=False, default=None)
@click.option("--model", "-m", default=None,
              help="Video model: flash (default), pro, lite, thinking")
@click.option("--orientation", "-O", default="landscape",
              type=click.Choice(["landscape", "portrait"], case_sensitive=False),
              help="Video orientation: landscape (16:9) or portrait (9:16)")
@click.option("--template", "-T", default=None,
              help="Omni video template (e.g., 'Anime', 'Logo reveal', '8-bit adventure')")
@click.option("--file", "-f", "files", multiple=True,
              help="Reference image/video to upload (repeatable). E.g. animate a still image")
@click.option("--output", "-o", default=None, help="Save generated video to file (.mp4)")
@click.pass_context
def video(ctx, prompt, model, orientation, template, files, output):
    """Generate a video from a text prompt (Gemini Omni).

    \b
    Examples:
        gemcli video "A sunset on the beach with waves crashing"
        gemcli video "A cat playing piano" -o cat_piano.mp4
        gemcli video "A vertical story" -O portrait -o story.mp4
        gemcli video "A cinematic oner" -m pro -O landscape -o shot.mp4
        gemcli video -T "Logo reveal" "NAIDA'S hair salon" -o logo.mp4
        gemcli video "Animate this: the balloon drifts" -f poster.png -o motion.mp4
    """
    profile_name = ctx.obj.get("profile")
    _validate_model(model)
    if not prompt and not template:
        raise click.UsageError("Provide a PROMPT (or a template prompt) to generate a video.")

    async def _video():
        async with GeminiClient(profile_name=profile_name) as client:
            from gemini_web_mcp_cli.services.video import (
                VideoService,
                extract_video_metadata,
                extract_video_url,
            )

            svc = VideoService(client)

            # Start generation
            response = await svc.generate(
                prompt or "",
                model=model,
                orientation=orientation,
                template=template,
                files=list(files) or None,
            )
            if response.text:
                console.print(Markdown(response.text))

            # Check if video data is already in the initial response
            video_data = None
            if response.has_video:
                for c in response.candidates:
                    if c.generated_video:
                        video_data = c.generated_video
                        break

            # If no video data yet and -o requested, poll for completion
            if not video_data and output:
                if not svc._cid:
                    console.print(
                        "[yellow]Video generation started but no conversation ID "
                        "returned. Check the web UI for progress.[/yellow]"
                    )
                    return

                console.print(
                    "[yellow]Video generation started. "
                    "Waiting for completion (up to 10 minutes)...[/yellow]"
                )
                with console.status(
                    "[bold cyan]Generating video...[/bold cyan]",
                    spinner="dots",
                ):
                    completed = await svc.wait_for_completion(
                        poll_interval=15.0,
                        max_wait=900.0,
                    )

                if completed and completed.has_video:
                    for c in completed.candidates:
                        if c.generated_video:
                            video_data = c.generated_video
                            break
                    if completed.text and completed.text != response.text:
                        console.print(Markdown(completed.text))
                else:
                    console.print(
                        "[red]Video generation timed out or failed. "
                        "Check the web UI for status.[/red]"
                    )
                    return

            # If we have video data, show metadata and optionally download
            if video_data:
                meta = extract_video_metadata(video_data)
                if meta:
                    if meta.get("model"):
                        console.print(f"[bold]Model:[/bold]  {meta['model']}")
                    if meta.get("duration_seconds"):
                        console.print(
                            f"[bold]Duration:[/bold] {meta['duration_seconds']}s"
                        )
                    if meta.get("width") and meta.get("height"):
                        console.print(
                            f"[bold]Resolution:[/bold] "
                            f"{meta['width']}x{meta['height']}"
                        )
                    if meta.get("orientation"):
                        console.print(
                            f"[bold]Orientation:[/bold] {meta['orientation']}"
                        )

                if output:
                    url = extract_video_url(video_data)
                    if not url:
                        console.print(
                            "[red]Could not extract download URL from response.[/red]"
                        )
                        return
                    saved = await svc.download(url, output)
                    console.print(f"\n[green]Video saved to {saved}[/green]")
                else:
                    url = extract_video_url(video_data)
                    if url:
                        console.print(
                            f"\n[dim]Download URL: {url[:80]}...[/dim]"
                        )
                    console.print(
                        "\n[dim]Use -o <file> to download "
                        "(e.g., gemcli video \"...\" -o video.mp4)[/dim]"
                    )
            elif not output:
                console.print(
                    "[yellow]Video generation started. "
                    "Use the web UI to check progress, "
                    "or use -o <file> to auto-download.[/yellow]"
                )

    try:
        run_async(_video())
    except TokenFactoryError as e:
        _handle_token_factory_error(e)
        raise SystemExit(1)
    except (AuthError, GeminiError) as e:
        _fail(e)


# ── Music ──────────────────────────────────────────────────────────────────


@cli.command()
@click.argument("prompt", required=False, default=None)
@click.option("--model", "-m", default=None,
              help="Model: pro, flash, thinking (default: flash)")
@click.option("--output", "-o", default=None,
              help="Save to file (.mp3 for audio, .mp4 for video)")
@click.option("--format", "-f", "fmt", default=None,
              type=click.Choice(["audio", "video"]),
              help="Download format: audio (MP3) or video (MP4 with cover art)")
@click.option("--style", "-s", default=None,
              help="Music style preset (e.g., 8-bit, k-pop, emo). Use --list-styles to see all.")
@click.option("--length", "-L", default=None,
              type=click.Choice(["short", "standard"], case_sensitive=False),
              help="Track length: short or standard")
@click.option("--vocals", "-V", default=None,
              type=click.Choice(["custom", "vocals", "instrumental"], case_sensitive=False),
              help="Vocals: custom (from prompt), vocals on, or instrumental")
@click.option("--genre", "-g", default=None,
              help="Genre: pop, hip-hop, rock, k-pop, latin, electronic, r&b, country, "
                   "afrobeats, reggae, jazz, classical, folk, lo-fi, acoustic, cinematic, ambient")
@click.option("--template", "-T", default=None,
              help="Music template (e.g., 'Soundscape', 'Intro music', 'Brand jingle')")
@click.option("--list-styles", is_flag=True, help="List available music style presets and exit")
@click.pass_context
def music(ctx, prompt, model, output, fmt, style, length, vocals, genre, template, list_styles):
    """Generate a music track from a text prompt (Lyria 3.5).

    \b
    Examples:
        gemcli music "A comical R&B slow jam about a sock"
        gemcli music "Epic orchestral piece" -o track.mp3
        gemcli music "Cats playing video games" -s 8-bit
        gemcli music "Summer vibes" -s k-pop -o track.mp3
        gemcli music "A chill study beat" -g lo-fi -L short
        gemcli music "An upbeat ad jingle" -V vocals -g pop -T "Brand jingle"
    \b
    Format is auto-detected from file extension when using -o:
        .mp3 → audio    .mp4 → video
    Without -o, displays track info only (use -o to download).
    \b
    Use --list-styles to see available legacy style presets.
    """
    if list_styles:
        from gemini_web_mcp_cli.core.music_presets import MUSIC_PRESETS

        console.print("[bold]Available music style presets:[/bold]\n")
        for key, preset in sorted(MUSIC_PRESETS.items()):
            console.print(f"  [bold]{key}[/bold]  ({preset['name']})")
        console.print("\n[dim]Use with: gemcli music \"prompt\" -s <style>[/dim]")
        return

    _validate_model(model)

    if not prompt and not template:
        console.print("[red]Error: Missing argument 'PROMPT'.[/red]")
        console.print("[dim]Usage: gemcli music \"your prompt here\"[/dim]")
        raise SystemExit(1)

    profile_name = ctx.obj.get("profile")

    async def _music():
        async with GeminiClient(profile_name=profile_name) as client:
            from gemini_web_mcp_cli.services.music import MusicFormat, MusicService

            svc = MusicService(client)
            if style:
                console.print(f"[bold]Generating music track (style: {style})...[/bold]")
            else:
                console.print("[bold]Generating music track...[/bold]")
            response = await svc.generate(
                prompt or "",
                model=model,
                style=style,
                length=length,
                vocals=vocals,
                genre=genre,
                template=template,
            )

            if not response.has_music:
                if response.text:
                    console.print(Markdown(response.text))
                else:
                    console.print("[yellow]No music generated.[/yellow]")
                return

            music_data = response.candidates[0].generated_music
            if not music_data:
                console.print("[yellow]No music data in response.[/yellow]")
                return

            # Extract track metadata (entry 2)
            metadata = music_data[2] if len(music_data) > 2 and music_data[2] else None
            if metadata and isinstance(metadata, list):
                title = metadata[0] if len(metadata) > 0 else "Unknown"
                album = metadata[2] if len(metadata) > 2 else ""
                track_genre = metadata[4] if len(metadata) > 4 else ""
                moods = metadata[5] if len(metadata) > 5 else []
                console.print(f"\n[bold]Track:[/bold]  {title}")
                if album:
                    console.print(f"[bold]Album:[/bold]  {album}")
                if track_genre:
                    console.print(f"[bold]Genre:[/bold]  {track_genre}")
                if moods and isinstance(moods, list):
                    console.print(f"[bold]Mood:[/bold]   {', '.join(str(m) for m in moods)}")

            # Show text response
            if response.text:
                console.print()
                console.print(Markdown(response.text))

            # Download if output path specified
            if output:
                # Auto-detect format from extension if not explicitly set
                download_fmt = fmt
                if not download_fmt:
                    ext = Path(output).suffix.lower()
                    if ext == ".mp4":
                        download_fmt = "video"
                    else:
                        download_fmt = "audio"  # Default to audio

                music_fmt = MusicFormat(download_fmt)

                # Extract download URL
                try:
                    if music_fmt == MusicFormat.VIDEO:
                        url = music_data[1][1][7][1]  # MP4 video URL
                    else:
                        url = music_data[0][1][7][1]  # MP3 audio URL
                except (IndexError, TypeError):
                    console.print("[red]Could not extract download URL from response.[/red]")
                    return

                saved = await svc.download(url, output, fmt=music_fmt)
                console.print(f"\n[green]Track saved to {saved}[/green]")
            else:
                console.print(
                    "\n[dim]Use -o <file> to download "
                    "(e.g., gemcli music \"...\" -o track.mp3)[/dim]"
                )

    try:
        run_async(_music())
    except TokenFactoryError as e:
        _handle_token_factory_error(e)
        raise SystemExit(1)
    except (AuthError, GeminiError) as e:
        _fail(e)


# ── Research ────────────────────────────────────────────────────────────────


@cli.command()
@click.argument("query")
@click.option("--model", "-m", default=None,
              help="Model: pro, flash, thinking (default: browser selection)")
@click.option("--output", "-o", default=None, help="Save research report to file")
@click.pass_context
def research(ctx, query, model, output):
    """Start a Deep Research query."""
    profile_name = ctx.obj.get("profile")
    _validate_model(model)

    async def _research():
        async with GeminiClient(profile_name=profile_name) as client:
            from gemini_web_mcp_cli.services.research import ResearchService

            svc = ResearchService(client)
            console.print("[bold]Creating research plan...[/bold]")
            plan = await svc.create_plan(query, model=model)
            if plan.text:
                console.print(Markdown(plan.text))
            await svc.start()
            console.print("[bold]Research running...[/bold]")
            result = await svc.wait_for_completion()
            console.print(Markdown(result["text"]))
            if output:
                from pathlib import Path

                Path(output).expanduser().write_text(result["text"], encoding="utf-8")

    try:
        run_async(_research())
    except TokenFactoryError as e:
        _handle_token_factory_error(e)
        raise SystemExit(1)
    except (AuthError, GeminiError) as e:
        _fail(e)


# ── Limits ──────────────────────────────────────────────────────────────────


@cli.command()
@click.pass_context
def limits(ctx):
    """Show current usage limits and remaining quota.

    Requires Chrome for browser cookie authentication (Token Factory).
    Queries the qpEbW RPC to get per-feature usage data including
    current usage, daily limit, remaining quota, and reset time.

    Examples:
        gemcli limits
    """
    profile_name = ctx.obj.get("profile")

    async def _limits():
        async with GeminiClient(profile_name=profile_name) as client:
            from gemini_web_mcp_cli.services.limits import LimitsService

            svc = LimitsService(client)

            account = (client.auth_manager.state.email or "").strip()
            profile = (
                client.auth_manager.profile_name
                or client.profile_manager.get_active_profile()
            )

            console.print()
            if account:
                console.print(
                    f"[bold]Account:[/bold] {account} [dim](profile: {profile})[/dim]"
                )
            else:
                console.print(f"[bold]Profile:[/bold] {profile}")

            feature_limits = await svc.get_limits()
            if not feature_limits:
                console.print(
                    "[yellow]No usage data returned. This usually means browser "
                    "cookies are unavailable (run 'gemcli chrome start'), or the "
                    "server changed the usage response format.[/yellow]"
                )
                return

            console.print()
            console.print("[bold]Gemini Usage Limits[/bold]")

            # The plan pool is the most common feature limit (a few features,
            # e.g. Audio Overviews, report larger unrelated pools).
            import textwrap
            from collections import Counter

            pool_values = [fl.limit for fl in feature_limits if fl.limit > 0]
            pool = Counter(pool_values).most_common(1)[0][0] if pool_values else 0
            if pool:
                console.print(
                    f"[dim]Plan pool: {pool} credits per window · "
                    "'Used' is the server-reported usage percentage[/dim]"
                )

            # Most features report the shared plan-pool percentage; advanced
            # features (Video, Deep Think) carry their own figure. Grouping by
            # percentage turns ~13 identical rows into one meaningful line.
            groups: dict[int, dict] = {}
            for fl in feature_limits:
                if fl.limit == 0:
                    continue
                group = groups.setdefault(
                    fl.used,
                    {"names": [], "remainings": [], "reset": fl.reset_in_seconds},
                )
                group["names"].append(fl.name)
                group["remainings"].append(fl.remaining)

            def _fmt_reset(secs: float) -> str:
                return f"{secs / 3600:.1f}h" if secs >= 3600 else f"{secs / 60:.0f}m"

            console.print()
            header = (
                f"{'Used':>5s}  {'Credits Left':>12s}  {'Resets In':>9s}  Features"
            )
            console.print(f"[dim]{header}[/dim]")
            console.print(f"[dim]{'─' * 72}[/dim]")

            for used, group in sorted(groups.items(), key=lambda kv: -kv[0]):
                remaining = min(group["remainings"])
                if remaining <= 0:
                    style = "red bold"
                elif pool and remaining <= pool * 0.2:
                    style = "yellow"
                else:
                    style = "green"

                line = (
                    f"{f'{used}%':>5s}  {remaining:>12d}  "
                    f"{_fmt_reset(group['reset']):>9s}  "
                )
                names = ", ".join(group["names"])
                wrapped = textwrap.wrap(names, width=44) or [""]
                console.print(f"[{style}]{line}{wrapped[0]}[/{style}]")
                for extra in wrapped[1:]:
                    console.print(f"{' ' * 33}{extra}")

            console.print()
            console.print(
                "[dim]Rows group features sharing a usage figure. The top row is "
                "the shared plan pool;[/dim]"
            )
            console.print(
                "[dim]Video and Deep Think report their own usage.[/dim]"
            )
            console.print(
                "[dim]Live view: https://gemini.google.com/usage[/dim]"
            )

    try:
        run_async(_limits())
    except TokenFactoryError as e:
        _handle_token_factory_error(e)
        raise SystemExit(1)
    except (AuthError, GeminiError) as e:
        _fail(e)


# ── Gems ────────────────────────────────────────────────────────────────────


@cli.group()
def gems():
    """Manage Gemini Gems (custom system prompts)."""
    pass


@gems.command("list")
@click.option("--predefined", is_flag=True, help="Show Google's premade gems")
@click.option("--shared", is_flag=True, help="Show gems shared with you")
@click.pass_context
def gems_list(ctx, predefined, shared):
    """List available gems."""
    profile_name = ctx.obj.get("profile")

    async def _list():
        async with GeminiClient(profile_name=profile_name) as client:
            # Gems RPCs require browser cookies (Token Factory)
            await client.send(prompt=".", force_token_factory=True)

            from gemini_web_mcp_cli.services.gems import GemsService

            svc = GemsService(client)
            gem_list = await svc.list_gems(predefined=predefined, shared=shared)
            if not gem_list:
                console.print("No gems found.")
                return
            for g in gem_list:
                console.print(f"  [bold]{g.name}[/bold] ({g.id})")
                if g.description:
                    console.print(f"    {g.description}")
                if g.default_tool:
                    console.print(f"    [dim]Default tool:[/dim] {g.default_tool_name}")
                if g.resources:
                    console.print(f"    [dim]Resources ({len(g.resources)}):[/dim]")
                    for r in g.resources:
                        tag = f"[cyan]{r.source}[/cyan]"
                        detail = r.mime_type if r.source != "notebook" else r.notebook_id
                        console.print(f"      - {r.name} ({detail}) [{tag}]")

    try:
        run_async(_list())
    except TokenFactoryError as e:
        _handle_token_factory_error(e)
        raise SystemExit(1)
    except (AuthError, GeminiError) as e:
        _fail(e)


@gems.command("create")
@click.option("--name", required=True, help="Gem name")
@click.option("--description", default="", help="Gem description")
@click.option("--prompt", required=True, help="System prompt")
@click.option("--notebook", multiple=True, help="NotebookLM notebook ID to attach (repeatable)")
@click.option(
    "--tool", "default_tool", default=None,
    help=(
        "Default tool for the gem. Options: none, image, video, music, "
        "canvas, deep-research, learning"
    ),
)
@click.option(
    "--file", "-f", "files", multiple=True,
    help="Local file path to attach as knowledge (repeatable)",
)
@click.pass_context
def gems_create(ctx, name, description, prompt, notebook, default_tool, files):
    """Create a new custom gem."""
    profile_name = ctx.obj.get("profile")

    async def _create():
        async with GeminiClient(profile_name=profile_name) as client:
            # Gems RPCs require browser cookies (Token Factory)
            await client.send(prompt=".", force_token_factory=True)

            from gemini_web_mcp_cli.services.gems import GEM_TOOL_ALIASES, GemsService

            svc = GemsService(client)
            tool_code = GEM_TOOL_ALIASES.get(default_tool.lower(), 0) if default_tool else 0
            await svc.create(
                name, description, prompt,
                knowledge_files=list(files) if files else None,
                notebook_ids=list(notebook) if notebook else None,
                default_tool=tool_code,
            )
            console.print(f"[green]Gem '{name}' created.[/green]")

    try:
        run_async(_create())
    except TokenFactoryError as e:
        _handle_token_factory_error(e)
        raise SystemExit(1)
    except (AuthError, GeminiError) as e:
        _fail(e)



@gems.command("delete")
@click.argument("gem_id")
@click.option(
    "--yes", "-y", is_flag=True, default=False,
    help="Skip confirmation prompt (for CI/automation)"
)
@click.pass_context
def gems_delete(ctx, gem_id, yes):
    """Delete a custom gem."""
    profile_name = ctx.obj.get("profile")

    if not yes:
        click.confirm(f"Delete gem '{gem_id}'? This cannot be undone.", abort=True)

    async def _delete():
        async with GeminiClient(profile_name=profile_name) as client:
            # Gems RPCs require browser cookies (Token Factory)
            await client.send(prompt=".", force_token_factory=True)

            from gemini_web_mcp_cli.services.gems import GemsService

            svc = GemsService(client)
            await svc.delete(gem_id)
            console.print(f"[green]Gem '{gem_id}' deleted.[/green]")

    try:
        run_async(_delete())
    except TokenFactoryError as e:
        _handle_token_factory_error(e)
        raise SystemExit(1)
    except (AuthError, GeminiError) as e:
        _fail(e)


# ── File ────────────────────────────────────────────────────────────────────


@cli.group()
def file():
    """Manage file uploads for conversation context."""
    pass


@file.command("upload")
@click.argument("file_path", type=click.Path(exists=True))
@click.pass_context
def file_upload(ctx, file_path):
    """Upload a file to Gemini and get its identifier."""
    profile_name = ctx.obj.get("profile")

    async def _upload():
        async with GeminiClient(profile_name=profile_name) as client:
            from gemini_web_mcp_cli.services.file import FileService

            svc = FileService(client)
            file_id = await svc.upload(file_path)
            console.print("[green]File uploaded successfully![/green]")
            console.print(f"[bold]Identifier:[/bold] {file_id}")
            console.print("\n[dim]You can use this identifier in raw stream_generate calls.[/dim]")

    try:
        run_async(_upload())
    except (AuthError, GeminiError) as e:
        _fail(e)


# ── Config ──────────────────────────────────────────────────────────────────


@cli.group()
def config():
    """Manage configuration settings."""
    pass


@config.command("show")
def config_show():
    """Show current configuration."""

    pm = ProfileManager()
    active = pm.get_active_profile()
    profiles = pm.list_profiles()
    has_nlm = pm.has_nlm_profiles()
    cfg = pm._read_config()
    default_model = cfg.get("default_model", "flash-preview")

    console.print(f"[bold]Active profile:[/bold]  {active}")
    console.print(f"[bold]Default model:[/bold]   {default_model}")
    console.print(f"[bold]Profiles:[/bold]        {', '.join(profiles) if profiles else 'none'}")
    console.print(f"[bold]NLM available:[/bold]   {'yes' if has_nlm else 'no'}")
    console.print(f"[bold]Config dir:[/bold]      {pm.config_dir}")
    console.print(f"[bold]Version:[/bold]         {__version__}")
    console.print()
    console.print(
        "[dim]Model shortcuts: pro, flash, gemini-3.8-flash, gemini-4-argon, "
        "thinking, preview[/dim]"
    )
    console.print("[dim]Set default:     gemcli config set model pro[/dim]")


@config.command("get")
@click.argument("key")
def config_get(key):
    """Get a specific configuration value.

    Keys: active_profile, model, browser
    """
    pm = ProfileManager()
    config_data = pm._read_config()

    if key == "active_profile":
        console.print(pm.get_active_profile())
    elif key == "model":
        console.print(config_data.get("default_model", "flash-preview"))
    elif key == "browser":
        console.print(config_data.get("browser", "auto"))
    elif key in config_data:
        console.print(str(config_data[key]))
    else:
        console.print(f"[red]Unknown config key: {key}[/red]")
        console.print("Available: active_profile, model, browser")


@config.command("set")
@click.argument("key")
@click.argument("value")
def config_set(key, value):
    """Set a configuration value.

    Examples:
        gemcli config set model pro
        gemcli config set model thinking
        gemcli config set model flash
        gemcli config set active_profile work
        gemcli config set browser brave
        gemcli config set browser "/Applications/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing"
    """  # noqa: E501
    pm = ProfileManager()

    if key == "active_profile":
        try:
            pm.set_active_profile(value)
            console.print(f"[green]Set {key} = {value}[/green]")
        except GeminiError as e:
            console.print(f"[red]{e}[/red]")
    elif key == "model":
        from gemini_web_mcp_cli.core.constants import get_model
        try:
            model = get_model(value)
            config_data = pm._read_config()
            config_data["default_model"] = value
            pm._write_config(config_data)
            console.print(f"[green]Default model set to: {value}[/green] ({model.name})")
        except ValueError as e:
            console.print(f"[red]{e}[/red]")
    elif key == "browser":
        from gemini_web_mcp_cli.core.cdp import SUPPORTED_BROWSER_KEYS, _is_browser_path
        valid = {"auto", *SUPPORTED_BROWSER_KEYS}
        if _is_browser_path(value):
            path = Path(value).expanduser()
            if not (path.is_file() and os.access(path, os.X_OK)):
                console.print(f"[red]Not an executable file: {value}[/red]")
                console.print("Give the binary inside the .app, e.g. .../Contents/MacOS/<name>")
                return
            value = str(path)
        elif value.lower() not in valid:
            console.print(f"[red]Invalid browser: {value}[/red]")
            console.print(f"Valid: {', '.join(sorted(valid))}, or a path to a Chromium binary")
            return
        else:
            value = value.lower()
        config_data = pm._read_config()
        config_data["browser"] = value
        pm._write_config(config_data)
        console.print(f"[green]Browser set to: {value}[/green]")
    else:
        config_data = pm._read_config()
        config_data[key] = value
        pm._write_config(config_data)
        console.print(f"[green]Set {key} = {value}[/green]")


# ── Chrome Daemon ──────────────────────────────────────────────────────────


def _format_uptime(total_seconds: int) -> str:
    """Format seconds as human-readable uptime."""
    days, remainder = divmod(total_seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, _ = divmod(remainder, 60)
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    parts.append(f"{minutes}m")
    return " ".join(parts)


@cli.group()
def chrome():
    """Manage persistent Chrome for Token Factory."""
    pass


@chrome.command("start")
@click.option("--visible", is_flag=True, help="Show Chrome window (default: headless)")
@click.option("--port", "-p", type=int, default=None, help="CDP debugging port (default: auto)")
@click.pass_context
def chrome_start(ctx, visible, port):
    """Start a persistent Chrome instance for Token Factory.

    Chrome runs in the background and survives terminal close.
    Token Factory will automatically detect and use it.

    Must be run from an interactive terminal (macOS security).

    \b
    Examples:
        gemcli chrome start              # Start headless
        gemcli chrome start --visible    # Start with window
        gemcli chrome start -p 9222      # Use specific port
    """
    import time

    from gemini_web_mcp_cli.core.chrome_manager import (
        DaemonAlreadyRunning,
        start_chrome_daemon,
    )

    pm = ProfileManager()
    profile_name = ctx.obj.get("profile") or pm.get_active_profile()
    chrome_profile_path = pm.get_chrome_profile_path(profile_name)
    # Timestamp: the LaunchAgent appends this output to chrome-agent.log.
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")

    if not chrome_profile_path:
        console.print("[red]No Chrome profile found.[/red]")
        console.print("Run [bold]gemcli login[/bold] first to set up authentication.")
        raise SystemExit(1)

    try:
        info = start_chrome_daemon(
            profile_name=profile_name,
            chrome_profile_path=chrome_profile_path,
            headless=not visible,
            port=port,
        )
        console.print(f"[green]{stamp} Chrome daemon started.[/green]")
        console.print(f"  [bold]PID:[/bold]     {info.pid}")
        console.print(f"  [bold]Port:[/bold]    {info.port}")
        console.print(f"  [bold]Profile:[/bold] {info.profile_name}")
        console.print(f"  [bold]Mode:[/bold]    {'headless' if info.headless else 'visible'}")
        console.print()
        console.print("[dim]Token Factory will automatically detect this Chrome instance.[/dim]")
        console.print("[dim]Stop with: gemcli chrome stop[/dim]")
        console.print(
            "[dim]To auto-start at login (survives reboot): "
            "gemcli chrome install-agent[/dim]"
        )
    except DaemonAlreadyRunning as e:
        # Exit 0: the LaunchAgent relaunches on non-zero exits, so reporting
        # "already running" as a failure looped every 5 minutes.
        console.print(f"{stamp} {e}")
    except TokenFactoryError as e:
        console.print(f"[red]{stamp} {e}[/red]")
        raise SystemExit(1)


@chrome.command("stop")
@click.option("--now", is_flag=True,
              help="Stop immediately, even if a request is using the daemon")
def chrome_stop(now):
    """Stop the persistent Chrome instance.

    Waits for in-flight requests on the daemon's profile first (up to
    GEMCLI_PROFILE_LOCK_TIMEOUT); --now skips the wait and breaks them.
    """
    from contextlib import nullcontext

    from gemini_web_mcp_cli.core.chrome_manager import load_daemon_info, stop_chrome_daemon
    from gemini_web_mcp_cli.core.locks import ProfileBusy, profile_lock

    info = load_daemon_info()
    guard = nullcontext() if now or not info else profile_lock(info.profile_name)
    try:
        with guard:
            stopped = stop_chrome_daemon()
    except ProfileBusy as e:
        _fail(e)
    if stopped:
        console.print("[green]Chrome daemon stopped.[/green]")
    else:
        console.print("[yellow]No Chrome daemon is running.[/yellow]")


@chrome.command("install-agent")
@click.option("--visible", is_flag=True, help="Show Chrome window (default: headless)")
@click.option("--port", "-p", type=int, default=None, help="CDP debugging port (default: auto)")
@click.pass_context
def chrome_install_agent(ctx, visible, port):
    """Install a macOS LaunchAgent to auto-start Chrome at login.

    Solves the issue where 'gemcli chrome start' fails from background
    processes (e.g., AI agent slots) that lack a GUI session.

    The LaunchAgent runs in the Aqua (GUI) session so Chrome gets proper
    WindowServer access. Chrome starts automatically at login and
    survives reboots.

    \b
    Examples:
        gemcli chrome install-agent           # Install headless
        gemcli chrome install-agent --visible  # Install with window
    """
    from gemini_web_mcp_cli.core.chrome_manager import (
        install_launch_agent,
        load_launch_agent,
    )

    pm = ProfileManager()
    profile_name = ctx.obj.get("profile") or pm.get_active_profile()
    chrome_profile_path = pm.get_chrome_profile_path(profile_name)

    if not chrome_profile_path:
        console.print("[red]No Chrome profile found.[/red]")
        console.print("Run [bold]gemcli login[/bold] first to set up authentication.")
        raise SystemExit(1)

    try:
        plist_path = install_launch_agent(
            profile_name=profile_name,
            chrome_profile_path=chrome_profile_path,
            headless=not visible,
            port=port,
        )
        console.print("[green]LaunchAgent installed.[/green]")
        console.print(f"  [bold]Plist:[/bold]   {plist_path}")
        console.print(f"  [bold]Profile:[/bold] {profile_name}")
        console.print(f"  [bold]Mode:[/bold]    {'headless' if not visible else 'visible'}")

        # Auto-load the agent
        loaded = load_launch_agent()
        if loaded:
            console.print()
            console.print(
                "[green]LaunchAgent loaded — Chrome will start "
                "now and at every login.[/green]"
            )
        else:
            console.print()
            console.print("[yellow]LaunchAgent written but could not be auto-loaded.[/yellow]")
            console.print("[dim]Load manually with:[/dim]")
            console.print(f"  launchctl load {plist_path}")

        console.print()
        console.print("[dim]Uninstall with: gemcli chrome uninstall-agent[/dim]")

    except TokenFactoryError as e:
        console.print(f"[red]{e}[/red]")
        raise SystemExit(1)


@chrome.command("uninstall-agent")
def chrome_uninstall_agent():
    """Uninstall the macOS LaunchAgent for Chrome.

    Stops Chrome auto-start at login and removes the plist file.
    """
    from gemini_web_mcp_cli.core.chrome_manager import uninstall_launch_agent

    removed = uninstall_launch_agent()
    if removed:
        console.print("[green]LaunchAgent uninstalled.[/green]")
        console.print("[dim]Chrome will no longer auto-start at login.[/dim]")
    else:
        console.print("[yellow]No LaunchAgent found to uninstall.[/yellow]")


@chrome.command("cleanup")
def chrome_cleanup():
    """Scan for and kill zombie Chrome processes.

    A zombie is a Chrome that responds to CDP but has no functional pages.
    These can block fresh launches and cause authentication failures.
    """
    from gemini_web_mcp_cli.core.chrome_manager import cleanup_all_zombies

    console.print("[dim]Scanning for zombie Chrome processes...[/dim]")
    cleaned = cleanup_all_zombies()
    if cleaned:
        console.print(f"[green]Cleaned {len(cleaned)} zombie(s):[/green]")
        for z in cleaned:
            console.print(
                f"  • PID {z['pid']} on port {z['port']} "
                f"(profile: {z['profile']})"
            )
    else:
        console.print("[green]No zombies found. Chrome is clean.[/green]")


@chrome.command("status")
def chrome_status():
    """Show persistent Chrome status."""
    import datetime

    from gemini_web_mcp_cli.core.chrome_manager import (
        check_daemon_health,
        get_gemini_auth_status,
    )

    info, status = check_daemon_health()

    if status == "not_running":
        console.print("[dim]Chrome daemon is not running.[/dim]")
        console.print("[dim]Start with: gemcli chrome start[/dim]")
        return

    if status == "stale":
        console.print("[yellow]Chrome daemon was running but has exited.[/yellow]")
        console.print("[dim]Cleaned up stale state. Start fresh with: gemcli chrome start[/dim]")
        return

    # status is "running", "zombie", or "unresponsive"
    started = datetime.datetime.fromtimestamp(info.started_at)
    uptime = datetime.datetime.now() - started
    uptime_str = _format_uptime(int(uptime.total_seconds()))

    console.print("  [bold]Status:[/bold]  ", end="")
    if status == "running":
        console.print("[green]running[/green]")
    elif status == "zombie":
        console.print("[red]zombie[/red] (responsive but no pages)")
    else:
        console.print("[yellow]unresponsive[/yellow]")

    console.print(f"  [bold]PID:[/bold]     {info.pid}")
    console.print(f"  [bold]Port:[/bold]    {info.port}")
    console.print(f"  [bold]Profile:[/bold] {info.profile_name}")
    console.print(f"  [bold]Mode:[/bold]    {'headless' if info.headless else 'visible'}")
    console.print(f"  [bold]Uptime:[/bold]  {uptime_str}")

    if status == "running":
        auth_status = get_gemini_auth_status(info.port, info.profile_name)
        if auth_status.is_authenticated:
            console.print("  [bold]Auth:[/bold]   [green]authenticated[/green]")
        else:
            console.print("  [bold]Auth:[/bold]   [yellow]not authenticated to Gemini[/yellow]")
            if auth_status.has_auth_cookie and not auth_status.access_token:
                console.print("       [yellow]→[/yellow] Cookies present, but SNlM0e is missing")
            elif auth_status.error:
                console.print(f"       [yellow]→[/yellow] {auth_status.error}")
            console.print("       [yellow]→[/yellow] Run: gemcli login")

    if status == "zombie":
        console.print()
        console.print("[red]Chrome is a zombie — responsive but has no functional pages.[/red]")
        console.print(
            "[dim]Fix: gemcli chrome cleanup  (or)  "
            "gemcli chrome stop && gemcli chrome start[/dim]"
        )

    if status == "unresponsive":
        console.print()
        console.print("[yellow]Chrome is running but not responding to CDP.[/yellow]")
        console.print("[dim]Try: gemcli chrome stop && gemcli chrome start[/dim]")


# ── Keep-alive ──────────────────────────────────────────────────────────────

_HEALTH_STYLE = {
    "alive": "[green]alive[/green]",
    "recovered": "[green]recovered[/green]",
    "dead": "[red]DEAD[/red]",
    "stale": "[yellow]stale[/yellow]",
    "skipped": "[dim]skipped[/dim]",
    "error": "[yellow]error[/yellow]",
}


def _print_health_row(result) -> None:
    status = _HEALTH_STYLE.get(result.status, result.status)
    email = result.email or ""
    line = f"  {result.profile:<14} {status:<28} {email}"
    if result.method:
        line += f" [dim]({result.method})[/dim]"
    console.print(line)
    if result.detail:
        console.print(f"  {'':<14} [dim]{result.detail}[/dim]")
    if result.capture:
        console.print(f"  {'':<14} {_capture_style(result.capture, result.transport)}")
    for step in result.steps if result.status != "alive" else []:
        console.print(f"  {'':<14} [dim]· {step}[/dim]")


def _capture_style(capture: str, transport: str = "") -> str:
    """Render a keep-alive token-capture result."""
    if capture == "ok":
        suffix = f" ({transport})" if transport else ""
        return f"[green]token capture ok{suffix}[/green]"
    if capture.startswith("failed"):
        return f"[red]token capture {capture}[/red]"
    return f"[dim]token capture {capture}[/dim]"


def _health_exit_code(results) -> int:
    """3 if a profile needs a human sign-in, 1 on errors or failed capture, else 0."""
    if any(r.status == "dead" for r in results):
        return EXIT_AUTH_REQUIRED
    if any(r.status == "error" or r.capture_failed for r in results):
        return 1
    return 0


def _run_health(
    only: str | None, recover: bool, check_only: bool, as_json: bool, probe: bool = True
) -> None:
    import json as json_mod
    from dataclasses import asdict

    from gemini_web_mcp_cli.core.keepalive import KeepaliveLocked, run_keepalive

    try:
        results = run_keepalive(
            only=only,
            recover=recover,
            check_only=check_only,
            on_result=None if as_json else _print_health_row,
            probe=probe,
        )
    except KeepaliveLocked as e:
        console.print(f"[yellow]{e}[/yellow]")
        return

    if as_json:
        click.echo(json_mod.dumps([asdict(r) for r in results], indent=2))
    else:
        dead = [r.profile for r in results if r.status == "dead"]
        if dead:
            console.print()
            console.print(
                f"[red]Needs a manual sign-in:[/red] {', '.join(dead)} "
                "— run [bold]gemcli login --profile <name>[/bold] for each."
            )
        stale = [r.profile for r in results if r.status == "stale"]
        if stale:
            console.print(
                f"[yellow]Saved cookies out of date:[/yellow] {', '.join(stale)} "
                "— run [bold]gemcli keepalive run[/bold] to refresh them."
            )
        broken = [r.profile for r in results if r.capture_failed]
        if broken:
            console.print(
                f"[red]Signed in, but BotGuard token capture fails:[/red] {', '.join(broken)} "
                "— uploads, images, video, music and Pro will fail on these. "
                "Run [bold]gemcli -p <name> doctor --deep[/bold]."
            )
    code = _health_exit_code(results)
    if code:
        raise SystemExit(code)


@cli.group()
def keepalive():
    """Keep every profile's Google session alive (see issue #3)."""
    pass


@keepalive.command("run")
@click.option("--recover", is_flag=True,
              help="If a session expired, try Google's one-click 'Continue as' sign-in "
                   "(off-screen window, never types a password)")
@click.option("--json", "as_json", is_flag=True, help="Output results as JSON")
@click.option("--no-probe", is_flag=True,
              help="Skip the BotGuard token-capture probe (faster; sends nothing either way)")
@click.pass_context
def keepalive_run(ctx, recover, as_json, no_probe):
    """Renew each profile's session through its own Chrome, and save the cookies.

    For each logged-in profile, opens that profile's own Chrome headless, loads
    Gemini so Chrome renews the session the normal way, and mirrors the fresh
    cookies into auth.json. The Chrome daemon's profile is refreshed from the
    daemon instead. Each signed-in profile then gets a BotGuard token-capture
    probe (the path uploads, images, video, music and Pro depend on); the probe
    is aborted inside Chrome, so nothing is sent to Gemini. Results are appended
    to logs/keepalive.jsonl.

    Exit codes: 0 = all alive, 3 = a profile needs a manual sign-in,
    1 = error or failed token capture.

    \b
    Examples:
        gemcli keepalive run                 # All profiles
        gemcli -p work keepalive run         # One profile
        gemcli keepalive run --recover       # Also try one-click re-sign-in
    """
    _run_health(ctx.obj.get("profile"), recover=recover, check_only=False, as_json=as_json,
                probe=not no_probe)


@keepalive.command("status")
def keepalive_status():
    """Show the last keep-alive result for each profile and the agent state."""
    import datetime

    from gemini_web_mcp_cli.core.keepalive import keepalive_plist_path, log_path, read_last_results

    plist = keepalive_plist_path()
    if plist.exists():
        text = plist.read_text(encoding="utf-8")
        hours = ""
        if "<key>StartInterval</key>" in text:
            seconds = int(text.split("<key>StartInterval</key>")[1].split("<integer>")[1]
                          .split("</integer>")[0])
            hours = f"every {seconds / 3600:g}h"
        recover = "with --recover" if "--recover" in text else "without --recover"
        console.print(f"[bold]Agent:[/bold] installed ({hours}, {recover})")
    else:
        console.print("[bold]Agent:[/bold] not installed "
                      "[dim](gemcli keepalive install-agent)[/dim]")

    latest = read_last_results()
    if not latest:
        console.print("[dim]No keep-alive runs logged yet.[/dim]")
        return
    console.print(f"[bold]Last results[/bold] [dim]({log_path()})[/dim]")
    for name, entry in sorted(latest.items()):
        status = _HEALTH_STYLE.get(entry.get("status"), entry.get("status"))
        when = entry.get("ts", "")
        try:
            when = datetime.datetime.strptime(when, "%Y-%m-%dT%H:%M:%S%z").strftime(
                "%b %d %H:%M"
            )
        except ValueError:
            pass
        console.print(f"  {name:<14} {status:<28} {when}  {entry.get('email', '')}")
        if entry.get("detail"):
            console.print(f"  {'':<14} [dim]{entry['detail']}[/dim]")
        if entry.get("capture"):
            capture = _capture_style(entry["capture"], entry.get("transport", ""))
            console.print(f"  {'':<14} {capture}")


@keepalive.command("install-agent")
@click.option("--every", "every_hours", type=float, default=4, show_default=True,
              help="Hours between runs")
@click.option("--recover", is_flag=True, help="Pass --recover to each scheduled run")
def keepalive_install_agent(every_hours, recover):
    """Install a macOS LaunchAgent that runs 'gemcli keepalive run' periodically.

    Runs in your login session (needed so Chrome can open), at load and then
    every --every hours. Output goes to logs/keepalive-agent.log.
    """
    from gemini_web_mcp_cli.core.keepalive import install_keepalive_agent

    try:
        plist = install_keepalive_agent(every_hours=every_hours, recover=recover)
    except (RuntimeError, ValueError) as e:
        console.print(f"[red]{e}[/red]")
        raise SystemExit(1)
    console.print("[green]Keep-alive agent installed and loaded.[/green]")
    console.print(f"  [bold]Plist:[/bold]    {plist}")
    console.print(f"  [bold]Schedule:[/bold] now, then every {every_hours:g}h")
    console.print(f"  [bold]Recovery:[/bold] {'on' if recover else 'off'}")
    console.print("[dim]Check results: gemcli keepalive status[/dim]")


@keepalive.command("uninstall-agent")
def keepalive_uninstall_agent():
    """Remove the keep-alive LaunchAgent."""
    from gemini_web_mcp_cli.core.keepalive import uninstall_keepalive_agent

    if uninstall_keepalive_agent():
        console.print("[green]Keep-alive agent uninstalled.[/green]")
    else:
        console.print("[yellow]No keep-alive agent found.[/yellow]")


# ── Doctor ──────────────────────────────────────────────────────────────────


@cli.command()
@click.option("--verbose", "-v", is_flag=True, help="Show additional details")
@click.option("--deep", is_flag=True,
              help="Also test the live path: capture a BotGuard token in Chrome and "
                   "upload a tiny file (sends nothing to Gemini chat)")
@click.pass_context
def doctor(ctx, verbose, deep):
    """Diagnose installation and configuration.

    Plain doctor checks that things are installed and saved. Only --deep proves
    that uploads, images, video, music and Pro can work for the profile
    (issue #5). Exit code 1 when --deep finds a failure.
    """
    console.print(f"\n[bold]gemcli doctor[/bold] (v{__version__})\n")
    all_ok = True

    # ── Verbose: platform info ──
    if verbose:
        console.print(f"  [dim]Python:   {sys.version.split()[0]}[/dim]")
        console.print(f"  [dim]Platform: {platform.platform()}[/dim]")
        console.print(f"  [dim]Version:  {__version__}[/dim]")
        console.print()

    # ── 1. Installation ──
    console.print("  [bold]Installation[/bold]")
    gemcli_path = shutil.which("gemcli")
    if gemcli_path:
        console.print(f"  [green]✓[/green]  gemcli binary: {gemcli_path}")
    else:
        console.print("  [yellow]-[/yellow]  gemcli binary: not on PATH (running via python -m)")

    mcp_path = shutil.which("gemini-web-mcp")
    if mcp_path:
        console.print(f"  [green]✓[/green]  gemini-web-mcp binary: {mcp_path}")
    else:
        console.print("  [red]✗[/red]  gemini-web-mcp binary: not found on PATH")
        console.print("       [yellow]→[/yellow] Fix: pip install gemini-web-mcp-cli[mcp]")
        all_ok = False

    # ── 2. Browser ──
    from gemini_web_mcp_cli.core.cdp import _find_browser_binary
    console.print()
    console.print("  [bold]Browser[/bold]")
    browser_result = _find_browser_binary()
    if browser_result:
        console.print(f"  [green]✓[/green]  {browser_result.name}: found")
        if verbose:
            console.print(f"       [dim]{browser_result.path}[/dim]")
    else:
        console.print("  [yellow]-[/yellow]  No Chromium browser found")
        console.print(
            "       [yellow]→[/yellow] Needed for login and Token Factory (Pro/Thinking)"
        )
        console.print(
            "       [dim]Install Chrome, Brave, Edge, or set GEMCLI_BROWSER=<name>[/dim]"
        )

    pm = ProfileManager()
    chrome_profiles_dir = pm.config_dir / "chrome-profiles"
    if chrome_profiles_dir.exists():
        chrome_profiles = [p for p in chrome_profiles_dir.iterdir() if p.is_dir()]
        if chrome_profiles:
            names = ", ".join(p.name for p in chrome_profiles)
            console.print(f"  [green]✓[/green]  Chrome profiles: {names}")
        else:
            console.print("  [dim]-[/dim]  Chrome profiles: directory exists but empty")
    else:
        console.print("  [dim]-[/dim]  Chrome profiles: none saved yet")

    # Chrome daemon status
    from gemini_web_mcp_cli.core.chrome_manager import check_daemon_health

    daemon_info, daemon_status = check_daemon_health()
    if daemon_status == "running":
        console.print(
            f"  [green]✓[/green]  Chrome daemon: running "
            f"(port {daemon_info.port}, PID {daemon_info.pid})"
        )
        if verbose:
            import datetime

            started = datetime.datetime.fromtimestamp(daemon_info.started_at)
            uptime = datetime.datetime.now() - started
            console.print(f"       [dim]Profile: {daemon_info.profile_name}[/dim]")
            console.print(
                f"       [dim]Mode: {'headless' if daemon_info.headless else 'visible'}[/dim]"
            )
            uptime_str = _format_uptime(int(uptime.total_seconds()))
            console.print(f"       [dim]Uptime: {uptime_str}[/dim]")
    elif daemon_status == "zombie":
        console.print(
            f"  [red]✗[/red]  Chrome daemon: ZOMBIE "
            f"(PID {daemon_info.pid}, port {daemon_info.port})"
        )
        console.print(
            "       [red]→[/red] Chrome is responsive but has no pages. "
            "Fix: gemcli chrome cleanup"
        )
        all_ok = False
    elif daemon_status == "unresponsive":
        console.print(
            f"  [yellow]-[/yellow]  Chrome daemon: unresponsive (PID {daemon_info.pid})"
        )
        console.print(
            "       [yellow]→[/yellow] Try: gemcli chrome stop && gemcli chrome start"
        )
        all_ok = False
    elif daemon_status == "stale":
        console.print("  [dim]-[/dim]  Chrome daemon: stale (auto-cleaned)")
    else:
        console.print("  [dim]-[/dim]  Chrome daemon: not running")
        if verbose:
            console.print("       [dim]Start with: gemcli chrome start[/dim]")

    # Check for zombie Chrome processes (beyond daemon)
    from gemini_web_mcp_cli.core.cdp import _read_port_map, is_chrome_healthy
    from gemini_web_mcp_cli.core.chrome_manager import is_chrome_responsive
    port_map = _read_port_map()
    zombie_count = 0
    for port_str, entry in port_map.items():
        port = int(port_str)
        if is_chrome_responsive(port) and not is_chrome_healthy(port):
            zombie_count += 1
    if zombie_count > 0:
        console.print(
            f"  [red]✗[/red]  Zombie Chrome: {zombie_count} zombie(s) detected in port map"
        )
        console.print("       [red]→[/red] Fix: gemcli chrome cleanup")
        all_ok = False
    elif verbose:
        console.print(f"  [green]✓[/green]  Port map: {len(port_map)} entries, no zombies")

    # ── 3. Configuration ──
    console.print()
    console.print("  [bold]Configuration[/bold]")
    if pm.config_dir.exists():
        console.print(f"  [green]✓[/green]  Config dir: {pm.config_dir}")
    else:
        console.print("  [dim]-[/dim]  Config dir: not created yet")
        console.print("       [yellow]→[/yellow] Run: gemcli login")

    profiles = pm.list_profiles()
    if profiles:
        active = pm.get_active_profile()
        console.print(f"  [green]✓[/green]  Profiles: {', '.join(profiles)} (active: {active})")
    else:
        console.print("  [yellow]-[/yellow]  No profiles found")

    if pm.has_nlm_profiles():
        nlm = pm._list_nlm_profiles()
        console.print(f"  [green]✓[/green]  NotebookLM MCP: {', '.join(nlm)}")
    else:
        console.print("  [dim]-[/dim]  NotebookLM MCP: not installed")

    # ── 4. Authentication ──
    console.print()
    console.print("  [bold]Authentication[/bold]")
    active_profile = ctx.obj.get("profile") or pm.get_active_profile()
    auth_data = pm.load_auth(active_profile)
    if auth_data and auth_data.get("cookies", {}).get("__Secure-1PSID"):
        console.print(f"  [green]✓[/green]  Auth ({active_profile}): saved cookies present")
        if verbose:
            cookie_count = len(auth_data.get("cookies", {}))
            console.print(f"       [dim]{cookie_count} cookies stored[/dim]")
            last_refreshed = auth_data.get("last_refreshed")
            if last_refreshed:
                import datetime

                ts = datetime.datetime.fromtimestamp(last_refreshed)
                console.print(f"       [dim]Last refreshed: {ts.isoformat()}[/dim]")
        if auth_data.get("tokens", {}).get("snlm0e"):
            console.print(f"  [green]✓[/green]  Auth ({active_profile}): saved tokens present")
            if not deep:
                console.print(
                    "       [dim]Saved ≠ working. Test the live path: "
                    f"gemcli -p {active_profile} doctor --deep[/dim]"
                )
        else:
            console.print(f"  [yellow]-[/yellow]  Auth ({active_profile}): no tokens")
            console.print("       [yellow]→[/yellow] Run: gemcli login")
            all_ok = False
    else:
        console.print(f"  [yellow]-[/yellow]  Auth ({active_profile}): not authenticated")
        if pm.profile_exists(active_profile):
            source = pm.get_profile_source(active_profile)
            if source == "nlm":
                console.print(
                    "       [yellow]→[/yellow] Profile from NLM — run gemcli login to add "
                    "Gemini cookies"
                )
        else:
            console.print("       [yellow]→[/yellow] Run: gemcli login")

    # ── 5. MCP Clients ──
    console.print()
    console.print("  [bold]MCP Clients[/bold]")
    from gemini_web_mcp_cli.core.json_io import read_json_dict
    from gemini_web_mcp_cli.setup import (
        CLIENT_REGISTRY,
        MCP_SERVER_KEY,
        _is_configured,
    )

    configured_clients = []
    for cid, info in CLIENT_REGISTRY.items():
        if cid == "claude-code":
            claude_cmd = shutil.which("claude")
            if claude_cmd:
                try:
                    result = subprocess.run(
                        [claude_cmd, "mcp", "list"],
                        capture_output=True,
                        text=True,
                        timeout=5,
                    )
                    if MCP_SERVER_KEY.lower() in result.stdout.lower():
                        configured_clients.append("Claude Code")
                except (subprocess.TimeoutExpired, OSError):
                    pass
            continue
        if cid == "codex":
            continue
        config_fn = info.get("config_fn")
        if config_fn:
            key = info.get("key", MCP_SERVER_KEY)
            path = config_fn()
            cfg = read_json_dict(path)
            if _is_configured(cfg, key):
                configured_clients.append(info["name"])

    if configured_clients:
        console.print(f"  [green]✓[/green]  Configured: {', '.join(configured_clients)}")
    else:
        console.print("  [dim]-[/dim]  No MCP clients configured")
        console.print("       [yellow]→[/yellow] Run: gemcli setup add <client>")

    # ── 6. Skills ──
    console.print()
    console.print("  [bold]Skills[/bold]")
    from gemini_web_mcp_cli.skill import TOOL_CONFIGS as SKILL_CONFIGS
    from gemini_web_mcp_cli.skill import check_install_status as skill_check

    installed_skills = []
    for tool_name in SKILL_CONFIGS:
        if tool_name == "other":
            continue
        is_installed, _ = skill_check(tool_name, "user")
        if is_installed:
            installed_skills.append(tool_name)

    if installed_skills:
        console.print(f"  [green]✓[/green]  Installed: {', '.join(installed_skills)}")
    else:
        console.print("  [dim]-[/dim]  No skills installed")
        console.print("       [yellow]→[/yellow] Run: gemcli skill install <tool>")

    # ── 7. Live path (--deep) ──
    if deep:
        console.print()
        console.print(f"  [bold]Live path ({active_profile})[/bold]")
        if not _doctor_deep(pm, active_profile):
            all_ok = False

    # ── Summary ──
    console.print()
    if all_ok:
        label = "All checks passed" if deep else "All checks passed (saved state only)"
        console.print(f"  [green]{label}.[/green]\n")
    else:
        console.print("  [yellow]Some issues found. See above.[/yellow]\n")
        if deep:
            raise SystemExit(1)


def _doctor_deep(pm: ProfileManager, profile_name: str) -> bool:
    """Run the live-path probes for doctor --deep. Returns True if all pass."""
    from gemini_web_mcp_cli.core.locks import lock_timeout
    from gemini_web_mcp_cli.core.probe import probe_token_capture, probe_upload

    probes = [
        probe_token_capture(
            profile_name, pm.get_chrome_profile_path(profile_name), lock_timeout=lock_timeout()
        ),
        asyncio.run(probe_upload(profile_name)),
    ]
    labels = {"token_capture": "BotGuard token capture", "upload": "File upload"}
    for probe in probes:
        if probe.ok:
            transport = (
                f" [dim]— chat transport: {probe.transport}[/dim]" if probe.transport else ""
            )
            console.print(
                f"  [green]✓[/green]  {labels[probe.name]}: ok "
                f"[dim]({probe.duration}s)[/dim]{transport}"
            )
        else:
            console.print(f"  [red]✗[/red]  {labels[probe.name]}: {probe.detail}")
    if not probes[0].ok:
        console.print(
            "       [red]→[/red] Uploads, images, video, music and Pro will fail. "
            "See 'Troubleshooting' in the gemcli skill: check `gemcli chrome status`, "
            "then `gemcli chrome stop && gemcli chrome start`, then another profile."
        )
    return all(p.ok for p in probes)


# ── Setup (MCP configuration for AI tools) ─────────────────────────────────

from gemini_web_mcp_cli.setup import setup  # noqa: E402

cli.add_command(setup)

# ── Skill (install AI tool skills) ─────────────────────────────────────────

from gemini_web_mcp_cli.skill import skill  # noqa: E402

cli.add_command(skill)


# ── Hack (launch AI tools connected to Gemini) ────────────────────────────


@cli.group()
def hack():
    """Launch AI tools connected to Gemini models."""
    pass


@hack.command(
    "claude",
    context_settings={
        "allow_extra_args": True,
        "allow_interspersed_args": False,
    },
)
@click.option(
    "--model", "-m",
    type=click.Choice(
        [
            "flash",
            "gemini-3.8-flash",
            "gemini-3.7-flash",
            "gemini-3.7-flash-extended",
            "gemini-4-argon",
            "pro",
            "thinking",
        ],
        case_sensitive=False,
    ),
    default=None,
    help="Gemini model to use (default: flash)",
)
@click.pass_context
def hack_claude(ctx, model):
    """Launch Claude Code using Gemini as the backend.

    Starts a local Anthropic-compatible API server backed by Gemini,
    then launches Claude Code connected to it. All remaining arguments
    are passed through to Claude Code.

    \b
    Examples:
        gemcli hack claude
        gemcli hack claude -m pro
        gemcli hack claude --model thinking
        gemcli hack claude -m pro -p "fix this bug"
    """
    from gemini_web_mcp_cli.hack import cmd_hack_claude

    raise SystemExit(cmd_hack_claude(ctx.args, model=model))


# ── Verb-first aliases ──────────────────────────────────────────────────────
# These let users write "gemcli list gems" instead of "gemcli gems list"


@cli.group(name="list")
def verb_list():
    """List resources (gems, profiles, skills)."""
    pass


@verb_list.command("gems")
@click.option("--predefined", is_flag=True, help="Show Google's premade gems")
@click.option("--shared", is_flag=True, help="Show gems shared with you")
@click.pass_context
def verb_list_gems(ctx, predefined, shared):
    """List available gems."""
    ctx.invoke(gems_list, predefined=predefined, shared=shared)


@verb_list.command("profiles")
def verb_list_profiles():
    """List all profiles."""
    profile_list()


@verb_list.command("skills")
@click.pass_context
def verb_list_skills(ctx):
    """List skill installation status."""
    from gemini_web_mcp_cli.skill import skill_list

    ctx.invoke(skill_list)


@cli.group(name="install")
def verb_install():
    """Install resources (skills)."""
    pass


@verb_install.command("skill")
@click.argument("tool")
@click.option(
    "--level", "-l", type=click.Choice(["user", "project"]),
    default="user", help="Install at user or project level",
)
@click.pass_context
def verb_install_skill(ctx, tool, level):
    """Install Gemini skill for an AI tool."""
    from gemini_web_mcp_cli.skill import skill_install

    ctx.invoke(skill_install, tool=tool, level=level)


@cli.group(name="update")
def verb_update():
    """Update resources (skills)."""
    pass


@verb_update.command("skill")
@click.argument("tool", required=False, default=None)
@click.pass_context
def verb_update_skill(ctx, tool):
    """Update outdated skills."""
    from gemini_web_mcp_cli.skill import skill_update

    ctx.invoke(skill_update, tool=tool)


@cli.group(name="create")
def verb_create():
    """Create resources (gems, profiles)."""
    pass


@verb_create.command("gem")
@click.option("--name", required=True, help="Gem name")
@click.option("--description", default="", help="Gem description")
@click.option("--prompt", required=True, help="System prompt")
@click.pass_context
def verb_create_gem(ctx, name, description, prompt):
    """Create a new custom gem."""
    ctx.invoke(gems_create, name=name, description=description, prompt=prompt)


@verb_create.command("profile")
@click.argument("name")
def verb_create_profile(name):
    """Create a new profile."""
    pm = ProfileManager()
    try:
        pm.create_profile(name)
        console.print(f"[green]Created profile: {name}[/green]")
    except GeminiError as e:
        console.print(f"[red]{e}[/red]")


@cli.group(name="delete")
def verb_delete():
    """Delete resources (gems, profiles)."""
    pass


@verb_delete.command("gem")
@click.argument("gem_id")
@click.confirmation_option(prompt="Are you sure?")
@click.pass_context
def verb_delete_gem(ctx, gem_id):
    """Delete a custom gem."""
    ctx.invoke(gems_delete, gem_id=gem_id)


@verb_delete.command("profile")
@click.argument("name")
@click.confirmation_option(prompt="Are you sure?")
def verb_delete_profile(name):
    """Delete a profile."""
    pm = ProfileManager()
    try:
        pm.delete_profile(name)
        console.print(f"[green]Deleted profile: {name}[/green]")
    except GeminiError as e:
        console.print(f"[red]{e}[/red]")


@cli.group(name="switch")
def verb_switch():
    """Switch active resources."""
    pass


@verb_switch.command("profile")
@click.argument("name")
def verb_switch_profile(name):
    """Switch the active profile."""
    pm = ProfileManager()
    try:
        pm.set_active_profile(name)
        console.print(f"[green]Switched to profile: {name}[/green]")
    except GeminiError as e:
        console.print(f"[red]{e}[/red]")


@cli.group(name="upload")
def verb_upload():
    """Upload resources (files)."""
    pass


@verb_upload.command("file")
@click.argument("file_path", type=click.Path(exists=True))
@click.pass_context
def verb_upload_file(ctx, file_path):
    """Upload a file to Gemini."""
    ctx.invoke(file_upload, file_path=file_path)


# ── Main entry point ────────────────────────────────────────────────────────


def main():
    """Entry point for the gemcli command."""
    cli(obj={})


if __name__ == "__main__":
    main()
