# Gemini Web MCP CLI - Command Reference

Complete command signatures for `gemcli` and the `gemini-web-mcp` MCP server.

---

## Global Options

| Option | Short | Description |
|--------|-------|-------------|
| `--profile` | `-p` | Use a specific profile for this command |
| `--verbose` | `-v` | Enable debug logging |
| `--version` | | Show version |
| `--ai` | | Output AI-friendly documentation |
| `--install-completion` | | Install shell completion |
| `--show-completion` | | Display completion script |

---

## Authentication

### `gemcli login`

Authenticate with Google Gemini via Chrome CDP or manual cookie entry.

```bash
gemcli login                          # Automated Chrome login via CDP
gemcli login --check                  # Validate current session
gemcli login --check --all            # Check every profile (read-only; exit 3 if any needs sign-in)
gemcli login --manual                 # Paste cookies manually
gemcli login --profile <name>         # Authenticate a specific profile
```

| Option | Description |
|--------|-------------|
| `--check` | Validate current auth without re-authenticating |
| `--manual` | Manual cookie entry mode |
| `--profile, -p` | Profile to authenticate |

---

## Chat

### `gemcli chat [PROMPT]`

Send messages to Gemini. Without a prompt, opens interactive REPL.

```bash
gemcli chat "What is quantum computing?"
gemcli chat "Explain this" -m gemini-3.1-pro
gemcli chat "Summarize" -o summary.md
gemcli chat "Analyze this" -f document.pdf
gemcli chat "Compare" -f file1.md -f file2.md
gemcli chat --new                     # Force new conversation
gemcli chat                           # Interactive REPL
```

| Option | Short | Description |
|--------|-------|-------------|
| `--model` | `-m` | Model to use (e.g., gemini-3.8-flash, gemini-4-argon) |
| `--thinking-level` | | Thinking level: `low`, `medium`, or `high` |
| `--extended-thinking` | | Enable Thinking level High (old Extended toggle) |
| `--task` | | Send as a Task (Chat/Task control; formerly Spark) |
| `--output` | `-o` | Save response to file |
| `--file` | `-f` | Attach a file (can be used multiple times) |
| `--new` | | Start new conversation (discard context) |
| `--gem` | | Use a specific Gem by ID |

**Interactive REPL Slash Commands:**

| Command | Description |
|---------|-------------|
| `/model <name>` | Switch model |
| `/thinking on\|off\|low\|medium\|high` | Set thinking level (`on` = high) |
| `/task on\|off` | Send later messages as a Task or a Chat |
| `/verify` | Show server model hash |
| `/new` | Start new conversation |
| `/save <file>` | Export conversation |
| `/history` | View conversation turns |
| `/help` | Show help |
| `/quit` | Exit REPL |

---

## Image Generation

### `gemcli image PROMPT`

Generate images using Gemini (Nano Banana / Imagen). Requires Chrome for BotGuard token and tool activation (`gemcli chrome start`).

```bash
gemcli image "A red panda in bamboo"
gemcli image "Futuristic city" -o city.png
gemcli image "Logo design" -m flash
gemcli image "A vertical poster" -A 9:16 -o poster.png
```

| Option | Short | Description |
|--------|-------|-------------|
| `--model` | `-m` | `pro` (Nano Banana Pro, default) or `flash` (Nano Banana 2) |
| `--aspect` | `-A` | `1:1`, `9:16`, `3:4`, `4:3`, or `16:9` (default: model decides) |
| `--output` | `-o` | Save generated image to file; the extension sets the format (`.png`, `.jpg`, `.webp`) |

---

## Video Generation

### `gemcli video PROMPT`

Generate videos using Gemini Omni (Veo 3.1 engine). Videos take 1-2 minutes. Requires Chrome for BotGuard token and tool activation (`gemcli chrome start`).

```bash
gemcli video "Ocean waves at sunset"
gemcli video "Dancing robot" -o robot.mp4
gemcli video "A vertical story" -O portrait -o story.mp4
gemcli video "A cinematic oner" -m pro -O landscape -o shot.mp4
gemcli video -T "Logo reveal" "NAIDA'S hair salon" -o logo.mp4
gemcli video "Animate this: the balloon drifts" -f poster.png -o motion.mp4
```

| Option | Short | Description |
|--------|-------|-------------|
| `--model` | `-m` | Video model: `flash` (default), `pro`, `lite`, `thinking` |
| `--orientation` | `-O` | `landscape` (16:9, default) or `portrait` (9:16) |
| `--template` | `-T` | Omni template name (e.g., `Anime`, `Logo reveal`, `8-bit adventure`) |
| `--file` | `-f` | Reference image/video to upload (repeatable) — e.g. animate a still image |
| `--output` | `-o` | Save generated video to file |

Reference-image videos render more slowly (5-15 minutes). The CLI waits up to
15 minutes when `-o` is used; if it times out, the video still appears in the
conversation in the web UI.

Template names are matched against the Create videos page in Chrome (case-insensitive).
A prompt is optional when a template is given.

---

## File Upload

### `gemcli file upload <FILE_PATH>`

Upload a file to Gemini and get its identifier.

```bash
gemcli file upload document.pdf
gemcli file upload screenshot.png
```

**Note:** For most use cases, use `gemcli chat -f <file>` instead — it handles upload + chat in one step.

---

### `gemcli chat -f <FILE_PATH>`

Attach one or more files to a chat message. Files are uploaded automatically.

```bash
gemcli chat "Summarize this" -f report.pdf
gemcli chat "What's in this image?" -f photo.jpg
gemcli chat "Compare these" -f a.md -f b.md
```

Requires Chrome for BotGuard token. Run `gemcli chrome start` first.

**Upload limits (Gemini Apps, July 2026):** Up to 10 files per prompt; each video
≤ 2 GB (total video ≤ 5 min free / 1 hour Pro); other files ≤ 100 MB each; total
audio ≤ 10 min free / 3 hours Pro. Large files may exceed the context window —
run `gemcli limits` to check quota before large batches.

---

## Music Generation

### `gemcli music [PROMPT]`

Generate music tracks using Gemini (Lyria 3.5). Includes vocals, lyrics, instrumentals, and auto-generated cover art. Without a prompt and with `--list-styles`, shows available legacy style presets.

```bash
gemcli music "A comical R&B slow jam about a sock"
gemcli music "Cats playing video games" -s 8-bit -o track.mp3
gemcli music "Summer vibes" -s k-pop -o video.mp4 -f video
gemcli music "A chill study beat" -g lo-fi -L short
gemcli music "An upbeat ad jingle" -V vocals -g pop -T "Brand jingle" -o jingle.mp3
gemcli music --list-styles
```

| Option | Short | Description |
|--------|-------|-------------|
| `--model` | `-m` | Model to use |
| `--output` | `-o` | Save generated track to file |
| `--style` | `-s` | Legacy style preset (e.g., 8-bit, k-pop, cinematic) |
| `--length` | `-L` | `short` or `standard` |
| `--vocals` | `-V` | `custom` (from prompt), `vocals` (vocals on), or `instrumental` |
| `--genre` | `-g` | Pop, Hip-hop & rap, Rock, K-pop, Latin, Electronic, R&B, Country, Afrobeats, Reggae, Jazz & blues, Classical, Folk, Lo-fi, Acoustic, Cinematic, Ambient |
| `--template` | `-T` | Music template, e.g. `Soundscape`, `Intro music`, `Brand jingle`, `Rap battle` |
| `--format` | `-f` | Output format: `audio` (MP3, default) or `video` (MP4 with cover art) |
| `--list-styles` | | Show all 16 available style presets and exit |

**Music templates (24):** Soundscape, Background music, Memorize something, Text messages, Intro music, Montage, Say it with a track, Brand jingle, Ringtone, Streaming, Speech to song, Rap battle, Comedy, Team anthem, Sports recap, Party invite, Happy birthday, Friend appreciation, Love story, Birthday roast, Ode to your pet, Hometown tribute, Weather report, Business promo.

**Genre aliases:** hip hop/hiphop/rap → Hip-hop & rap, rnb → R&B, jazz/blues → Jazz & blues, lofi → Lo-fi, kpop → K-pop, afrobeat → Afrobeats.

**Available Style Presets:** 90s-rap, latin-pop, folk-ballad, 8-bit, workout, reggaeton, rnb-romance, kawaii-metal, cinematic, emo, afropop, forest-bath, k-pop, birthday-roast, folk-a-cappella, bad-music.

**Aliases:** rap, latin, folk, chiptune, edm, rnb, r&b, kawaii, metal, orchestral, ambient, kpop, birthday, roast, country, acappella, bad.

---

## Deep Research

### `gemcli research QUERY`

Run deep research queries with multi-source analysis.

```bash
gemcli research "Latest AI advances in 2026"
gemcli research "Quantum computing breakthroughs" -m gemini-3.1-pro
```

| Option | Short | Description |
|--------|-------|-------------|
| `--model` | `-m` | Model to use |
| `--output` | `-o` | Save research report to file |

---

## Usage Limits

### `gemcli limits`

Show current usage limits and remaining quota for all features. Requires Chrome for browser cookie authentication (Token Factory).

```bash
gemcli limits
gemcli -p <profile> limits       # Check a different account
```

Output starts with the **account and profile** the data is for, then grouped
usage rows:

| Column | Meaning |
|--------|---------|
| `Used` | Server-reported **usage percentage**. Most features share one plan pool and show the account-wide figure (matches the "Current usage" on `https://gemini.google.com/usage`); Video (Gemini Omni) and Deep Think report their own |
| `Credits Left` | Remaining credits in that pool (pool size depends on the account's plan) |
| `Resets In` | Time until that row resets, as reported by Google (differs by feature and account) |
| `Features` | Which features the row covers |

When a feature reaches 100% its tool is disabled until the window resets —
**switch profiles to keep working**.

---

## Gems Management

### `gemcli gems list`

List all custom Gems.

```bash
gemcli gems list
gemcli gems list --predefined        # Include predefined Gems
```

| Option | Description |
|--------|-------------|
| `--predefined` | Include system/predefined gems |

### `gemcli gems create`

Create a new custom Gem.

```bash
gemcli gems create --name "Code Reviewer" --prompt "You are a senior code reviewer..."
gemcli gems create --name "Writer" --description "Creative writing" --prompt "..."
```

| Option | Description |
|--------|-------------|
| `--name` | Display name (required) |
| `--description` | Short description |
| `--prompt` | System prompt text (required) |

### `gemcli gems delete GEM_ID`

Delete a Gem by ID.

```bash
gemcli gems delete abc123
```

---

## Profile Management

Profiles are separate Gemini accounts/sessions. Use them to work across
accounts or to keep generating when one account's quota is exhausted.

**Run any command as another profile** with the global flag (before the
subcommand):

```bash
gemcli -p work chat "hi"
gemcli -p work limits
gemcli -p work video "A drone shot over a lake" -O landscape -o clip.mp4
```

**Quota-flip workflow:**
```bash
gemcli limits                 # active profile usage
gemcli -p <other> limits      # compare accounts
gemcli -p <other> video "..." # generate on the account with quota
gemcli profile switch <other> # make it the default
```

### `gemcli profile list`

List all profiles (gemcli-native + NotebookLM shared).

### `gemcli profile switch NAME`

Switch the active profile.

### `gemcli profile create NAME`

Create a new profile.

### `gemcli profile delete NAME`

Delete a profile (requires confirmation).

### `gemcli profile sources`

Show profile sources (gemcli-native vs NLM shared).

---

## Session Keep-Alive

Renews every logged-in profile's Google session through that profile's own
Chrome and saves the fresh cookies to `auth.json`. The Chrome daemon's profile
is refreshed from the daemon. Each signed-in profile then gets a BotGuard
token-capture probe (aborted inside Chrome, so nothing is sent to Gemini),
recorded as `capture` (`ok`, `failed: <stage>` or `skipped: <why>`) next to
the session status, plus `transport` (`streamgenerate` / `processSession`)
when the probe succeeds. Results are appended to
`~/.gemini-web-mcp-cli/logs/keepalive.jsonl`.

```bash
gemcli keepalive run                   # All profiles
gemcli -p <name> keepalive run         # One profile
gemcli keepalive run --recover         # Also try one-click "Continue as" re-sign-in
gemcli keepalive run --json            # Machine-readable results
gemcli keepalive run --no-probe        # Skip the token-capture probe
gemcli keepalive status                # Last result per profile + agent schedule
gemcli keepalive install-agent --every 4 --recover
gemcli keepalive uninstall-agent
```

| Exit code | Meaning |
|-----------|---------|
| `0` | Every profile alive (or skipped) with working token capture |
| `3` | At least one profile needs a manual `gemcli login --profile <name>` |
| `1` | A profile could not be checked (error), or it is signed in but token capture failed |

`login --check --all` also reports `stale`: the saved cookie copy is out of
date but the profile's Chrome may still be signed in — `gemcli keepalive run`
refreshes it (exit code stays `0`).

`--recover` never types anything: a password, passkey, or "verify it's you"
page ends the attempt and reports the profile as `DEAD`.

## Persistent Chrome

### `gemcli chrome start`

Start a persistent Chrome daemon for Token Factory. Required for image generation, video generation, music generation, and Pro/Extended thinking models. Must be run from an interactive terminal.

```bash
gemcli chrome start              # Start headless (default)
gemcli chrome start --visible    # Start with visible window
gemcli chrome start -p 9225      # Use specific CDP port
```

| Option | Short | Description |
|--------|-------|-------------|
| `--visible` | | Show Chrome window instead of headless |
| `--port` | `-p` | Specific CDP debugging port (default: auto from 9222-9231) |

Chrome runs in the background and survives terminal close. Token Factory automatically detects it on ports 9222-9231, verifies live Gemini browser auth (`__Secure-1PSID` plus `SNlM0e`), and uses it only for the profile it holds. Saved cookies are never injected into the daemon.

### `gemcli chrome stop`

Stop the persistent Chrome daemon. Waits for requests already using it
(up to `GEMCLI_PROFILE_LOCK_TIMEOUT`, default 300s); new requests queue until
it is done.

```bash
gemcli chrome stop
gemcli chrome stop --now   # Don't wait (breaks in-flight requests)
```

Start failures now say why: "did not answer on port P within 30s" (raise
`GEMCLI_CHROME_START_TIMEOUT`), or "exited with code N … The profile is
locked by another Chrome (host-PID)". `gemcli chrome start` exits 0 when the
daemon is already running.

### `gemcli chrome status`

Show Chrome daemon health, port, uptime, and verified Gemini auth status. Authentication is considered valid only when Chrome has both the Google auth cookie and Gemini's live `SNlM0e` page token.

```bash
gemcli chrome status
```

### `gemcli chrome install-agent`

Install a macOS LaunchAgent to auto-start the Chrome daemon at login. Solves the issue where `gemcli chrome start` fails from background processes (e.g., AI agent slots) that lack a GUI session. Chrome starts automatically at login and survives reboots.

```bash
gemcli chrome install-agent              # Install headless (default)
gemcli chrome install-agent --visible    # Install with visible window
```

| Option | Short | Description |
|--------|-------|-------------|
| `--visible` | | Show Chrome window instead of headless |
| `--port` | `-p` | Specific CDP debugging port |

### `gemcli chrome uninstall-agent`

Remove the macOS LaunchAgent. Chrome will no longer auto-start at login.

```bash
gemcli chrome uninstall-agent
```

---

## Configuration

### `gemcli config show`

Display all current settings.

### `gemcli config get KEY`

Get a specific configuration value.

### `gemcli config set KEY VALUE`

Set a configuration value.

**Available Keys:**

| Key | Default | Description |
|-----|---------|-------------|
| `active_profile` | `default` | Active profile name |
| `default_model` | (none) | Default model for commands |
| `browser` | `auto` | Browser name (`chrome`, `brave`, `edge`, `chromium`, …) or a path to a Chromium binary, e.g. a dedicated Chrome for Testing |

**Environment variables:**

| Variable | Default | Description |
|----------|---------|-------------|
| `GEMCLI_BROWSER` | — | Overrides `browser` (name or path) |
| `GEMCLI_PROFILE_LOCK_TIMEOUT` | `300` | Seconds a request waits while other requests use the profile's Chrome, then "Profile '…' is busy" |
| `GEMCLI_CHROME_START_TIMEOUT` | `30` | Seconds a new Chrome daemon gets to answer CDP |
| `GEMCLI_CHROME_IDLE_TIMEOUT` | `120` | Seconds before a Token Factory Chrome that gemcli launched is closed (0 = never) |
| `GEMCLI_ATTACHMENT_CHECK` | `1` | `0` returns replies that say the attachment couldn't be opened instead of failing |

---

## MCP Setup

### `gemcli setup list`

Show all supported AI tools and their MCP configuration status.

### `gemcli setup add CLIENT`

Add Gemini Web MCP server to an AI tool.

```bash
gemcli setup add cursor
gemcli setup add claude-desktop
gemcli setup add claude-code
gemcli setup add gemini-cli
gemcli setup add windsurf
gemcli setup add cline
gemcli setup add antigravity
```

### `gemcli setup remove CLIENT`

Remove Gemini Web MCP server from an AI tool.

---

## Skill Management

### `gemcli skill list`

Show available tools and skill installation status.

### `gemcli skill install TOOL`

Install Gemini skill documentation for an AI tool.

```bash
gemcli skill install claude-code
gemcli skill install cursor
gemcli skill install codex
gemcli skill install gemini-cli
```

| Option | Short | Default | Description |
|--------|-------|---------|-------------|
| `--level` | `-l` | `user` | Install at user or project level |

### `gemcli skill uninstall TOOL`

Remove installed Gemini skill.

### `gemcli skill update [TOOL]`

Update outdated skills. If TOOL omitted, updates all.

### `gemcli skill show`

Display the full skill documentation content.

---

## Hack (Launch AI Tools via Gemini)

### `gemcli hack claude [OPTIONS]`

Launch Claude Code connected to a local Anthropic-compatible API server backed by Gemini.

```bash
gemcli hack claude                         # Default: gemini-auto (Flash)
gemcli hack claude --model gemini-pro      # Use Gemini Pro
gemcli hack claude -p "fix this bug"       # Pass args to Claude Code
```

All arguments after `claude` are passed through to Claude Code.

**Available models:** `gemini-auto`, `gemini-3.8-flash`, `gemini-4-argon`, `gemini-3.7-flash`, `gemini-3.7-flash-extended`, `gemini-pro`, `gemini-thinking`.

---

## Diagnostics

### `gemcli doctor`

Diagnose installation, saved authentication, and configuration. Plain
`doctor` checks that credentials are *saved*, not that they work.

```bash
gemcli doctor                       # Standard diagnostics
gemcli doctor --verbose             # Detailed diagnostics with paths and timestamps
gemcli -p <profile> doctor --deep   # Also test the live path
```

`--deep` captures a BotGuard token in the profile's Chrome (the request is
aborted inside Chrome, so nothing reaches Gemini) and uploads a tiny text file
(not attached to any chat). It prints the failing stage and exits 1 on
failure. Use it when uploads, images, video, music or Pro fail on a profile
that looks signed in. On success it also names the account's chat transport:
`streamgenerate` or `processSession` (Gemini's WebChannel transport, rolled out
per account from Sep 2026). Both are supported and detected per request.

---

## MCP Server Tools

The `gemini-web-mcp` MCP server exposes these tools:

### `chat`

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `action` | string | yes | `"send"` |
| `prompt` | string | for send | Message to send |
| `model` | string | no | Model: "pro", "flash", "lite", "thinking" |
| `conversation_id` | string | no | Continue existing conversation |
| `extensions` | list[str] | no | Extensions: ["youtube", "maps"] |
| `files` | list[str] | no | Local file paths to upload and attach |

### `image`

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `action` | string | yes | `"generate"` or `"download"` |
| `prompt` | string | for generate | Image description |
| `model` | string | no | `"pro"` (default, Nano Banana Pro) or `"flash"` (Nano Banana 2) |
| `image_url` | string | for download | URL from generate response |
| `output_path` | string | for download | Local file path |

### `video`

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `action` | string | yes | `"generate"`, `"status"`, or `"download"` |
| `prompt` | string | for generate | Video description |
| `model` | string | no | Model to use |
| `output_path` | string | for download | Local file path |

### `music`

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `action` | string | yes | `"generate"`, `"list_styles"`, or `"download"` |
| `prompt` | string | for generate | Music description / concept |
| `style` | string | no | Style preset name (e.g., "8-bit", "k-pop", "cinematic") |
| `output_path` | string | no | Auto-download generated track to this path |
| `download_url` | string | for download | URL from a previous generation |

**Actions:**
- `generate` — Generate a 30-second track. Returns track metadata, lyrics, and download URLs (MP3 + MP4).
- `list_styles` — Returns all 16 available style preset names.
- `download` — Download a track from a previous generation URL.

### `research`

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `action` | string | yes | `"start"` or `"status"` |
| `query` | string | for start | Research question |
| `model` | string | no | Model to use |

### `file`

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `action` | string | yes | `"upload"` |
| `file_path` | string | for upload | Local path to the file |

### `gems`

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `action` | string | yes | `"list"`, `"create"`, `"update"`, `"delete"` |
| `gem_id` | string | for update/delete | Gem identifier |
| `name` | string | for create | Display name |
| `description` | string | no | Short description |
| `system_prompt` | string | for create | System prompt text |

### Stub Tools (Coming Soon)

- **`canvas`**: Collaborative document editing (actions: create, update, export)
- **`code`**: Python code execution in Gemini's sandbox (actions: execute, download)
- **`file`**: File upload for conversation context (actions: upload)

---

## Verb-First Aliases

These aliases provide an alternative command style:

```bash
gemcli list gems                 # = gemcli gems list
gemcli list profiles             # = gemcli profile list
gemcli list skills               # = gemcli skill list
gemcli create gem --name ...     # = gemcli gems create --name ...
gemcli delete gem <id>           # = gemcli gems delete <id>
gemcli install skill <tool>      # = gemcli skill install <tool>
gemcli update skill [tool]       # = gemcli skill update [tool]
```
