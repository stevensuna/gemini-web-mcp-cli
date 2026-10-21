<!-- gemini-web-skill-start -->

## Gemini Web MCP - CLI & MCP Expert

**Triggers:** "gemcli", "gemini web mcp", "gemini chat", "image generation", "video generation", "music generation", "check limits", "quota", "deep research", "gems"

This section provides guidance for using Google Gemini via the `gemcli` CLI and `gemini-web-mcp` MCP server.

### Quick Reference

```bash
gemcli --ai                # Full AI-optimized documentation
gemcli --help              # List all commands
gemcli doctor              # Diagnose installation and auth
```

### Critical Rules

1. **Always authenticate first**: Run `gemcli login` before any operations
2. **Session expiry**: Exit code `3` = auth error. First run `gemcli login --check --all` (read-only): if the profile is `alive`, just retry once; `stale` → `gemcli -p <profile> keepalive run`, retry; `DEAD` → use another alive profile (`gemcli -p <profile> ...`). Only in an interactive session with the user present run `gemcli login --profile <name>`; **never from a script, cron, LaunchAgent or pipeline** (it stops the Chrome daemon and opens a window nobody sees). If none work, tell the user which profile needs a sign-in. Avoid `--force`. Exit code `1` = any other failure — read the message (Error Recovery below)
3. **Parallel jobs queue per profile** (safe since 0.8.3). Spread big batches across profiles with `-p` for throughput; never stop/restart Chrome to "unstick" jobs
4. **Health that proves the real path**: `gemcli -p <profile> doctor --deep` (token capture + tiny upload, sends nothing to Gemini) and `gemcli keepalive status` (`token capture ok/failed` per profile). Plain `gemcli doctor` only checks saved state
5. **Check limits before media generation**: Run `gemcli limits` before video, music, or image generation. It shows the account/profile, per-feature usage percentage, credits left, and reset time
6. **If a media tool is disabled or quota is exhausted, switch profiles**: `gemcli -p <profile> limits` to compare, then `gemcli -p <profile> video "..."` (or `gemcli profile switch <profile>` to make it the default)
7. **Model selection**: Gemini 3.8 Flash is default (`gemini-3.7-flash` is the same hash). Web catalog also has `gemini-3.5-flash-lite`, `gemini-3.1-pro`, and `gemini-4-argon`. Thinking level is `low` / `medium` / `high`; `--task` is the Chat/Task control. Pro, Argon, Task, and non-low thinking need Token Factory. Unknown `--model` names fail up front with a one-line error
8. **Music, video, image generation and file attachments require Chrome**: Run `gemcli chrome start` first (BotGuard + tool activation needed)
9. **Background processes**: If running from LaunchAgent/cron, use `gemcli chrome install-agent` or start persistent Chrome from interactive terminal first
10. **Use `--help` when unsure**: `gemcli <command> --help`

### Key Commands

```bash
# Chat
gemcli chat "prompt"                    # Single message
gemcli chat "prompt" -m gemini-3.1-pro  # Use Pro model
gemcli chat "prompt" -m gemini-4-argon  # Gemini 4 Argon
gemcli chat --task "Collect recipes…"   # Task / agent mode
gemcli chat                             # Interactive REPL

# Image Generation (Nano Banana Pro default, Nano Banana 2 with -m flash)
gemcli image "A sunset" -o sunset.png
gemcli image "A vertical poster" -A 9:16 -o poster.png     # aspects: 1:1 9:16 3:4 4:3 16:9
gemcli image "A wide banner" -A 16:9 -m flash -o banner.png

# Video Generation (Gemini Omni)
gemcli video "Ocean waves" -o video.mp4
gemcli video "A vertical story" -O portrait -o story.mp4   # -O landscape (default) | portrait
gemcli video "A cinematic oner" -m pro -O landscape -o shot.mp4  # -m flash|pro|lite|thinking
gemcli video -T "Logo reveal" "NAIDA'S hair salon" -o logo.mp4   # template + optional prompt
gemcli video "Animate this" -f poster.png -O portrait -o motion.mp4  # reference image (5-15 min render)

# Music Generation (Lyria 3.5)
gemcli music "A comical R&B slow jam about a sock"
gemcli music "Cats playing games" -s 8-bit -o track.mp3    # legacy style preset
gemcli music "A chill study beat" -g lo-fi -L short        # genre + length
gemcli music "An upbeat ad jingle" -V vocals -g pop -T "Brand jingle" -o jingle.mp3
gemcli music --list-styles                  # Show all 16 legacy style presets

# Deep Research
gemcli research "AI advances in 2026"

# Gems Management
gemcli gems list
gemcli gems create --name "Reviewer" --prompt "You are a code reviewer..."
gemcli gems create --name "Expert" --prompt "..." --notebook <uuid>  # With NotebookLM
gemcli gems delete <gem_id>

# Profile Management (separate accounts; use to keep working when quota runs out)
gemcli profile list
gemcli profile switch <name>
gemcli -p <name> limits                 # Check another account's quota
gemcli -p <name> video "..." -o clip.mp4  # Run any command as another profile

# Persistent Chrome (required for image, video, music generation, and background processes)
gemcli chrome start              # Start headless Chrome daemon
gemcli chrome install-agent      # Auto-start at login (survives reboot)
gemcli chrome status             # Check health, auth cookie, and live SNlM0e
gemcli chrome stop               # Stop daemon (waits for running jobs)

# Session health (multiple profiles)
gemcli login --check --all       # Which profiles are signed in (exit 3 if any needs sign-in)
gemcli keepalive run             # Renew every profile + probe token capture
gemcli keepalive status          # Last result: alive/stale/DEAD + token capture ok/failed
gemcli -p <name> doctor --deep   # Prove uploads/media can work on that profile
gemcli keepalive install-agent --every 4 --recover   # Keep them alive every 4h (macOS)

# Usage Limits (run before generating; flip profiles when exhausted)
gemcli limits                    # Account/profile + per-feature % used, credits left, reset time

# Diagnostics & Setup
gemcli doctor
gemcli setup add <tool>
gemcli skill install <tool>
```

### MCP Tools (when available)

| Tool | Actions | Key Parameters |
|------|---------|---------------|
| `chat` | send | prompt, model, conversation_id, extensions |
| `image` | generate, download | prompt, model, aspect (`1:1` `9:16` `3:4` `4:3` `16:9`), output_path, image_url |
| `video` | generate, status, download | prompt, model, orientation (`landscape`/`portrait`), template, files (reference images), output_path |
| `music` | generate, list_styles, download | prompt, style, length (`short`/`standard`), vocals (`custom`/`vocals`/`instrumental`), genre, template, output_path, download_url |
| `research` | start, status | query, model |
| `gems` | list, list_notebooks, create, update, delete | gem_id, name, system_prompt, notebook_ids |
| `limits` | (none) | Per-feature usage percentages, credits left, reset time |

### Common Workflows

**First-time setup:**
```bash
gemcli login && gemcli doctor
```

**Quota-aware media generation (check → generate → flip profile if blocked):**
```bash
gemcli limits                                    # account, % used, credits left
gemcli video "A vertical story" -O portrait -o story.mp4
# If the Videos tool is disabled or usage is exhausted:
gemcli -p <other-profile> limits                 # compare another account
gemcli -p <other-profile> video "A vertical story" -O portrait -o story.mp4
```

**Image generation pipeline:**
```bash
gemcli image "A futuristic cityscape" -o city.png
gemcli image "A vertical movie poster" -A 9:16 -o poster.png
```

**Video generation pipeline:**
```bash
gemcli video "Ocean waves at sunset" -o waves.mp4
gemcli video -T "8-bit adventure" "A tiny knight crossing a kingdom" -o pixel.mp4
```

**Music generation pipeline:**
```bash
gemcli music "An upbeat pop song about coding" -o track.mp3
gemcli music "Epic battle theme" -s cinematic -o battle.mp3
gemcli music "A chill lo-fi beat" -g lo-fi -L short -V instrumental -o beat.mp3
```

**Research pipeline:**
```bash
gemcli research "Latest breakthroughs in quantum computing"
```

### Error Recovery

| Error | Solution |
|-------|----------|
| Auth expired (exit code 3) | `gemcli login --check --all`; retry on an `alive` profile; `gemcli login` only interactively; then ask the user to sign in |
| "Profile '…' is busy with another request" | Retry, use `-p <other>`, or raise `GEMCLI_PROFILE_LOCK_TIMEOUT` (default 300s). Don't restart Chrome |
| "Gemini did not read the attachment" | Answer withheld (it's usually invented). Retry once, `doctor --deep`, another profile |
| TokenFactoryError / "Not retrying without Chrome" | `gemcli -p <profile> doctor --deep`, `gemcli chrome status`, then `gemcli chrome stop && gemcli chrome start`; background: `gemcli chrome install-agent` |
| "Chrome sent the prompt through a Gemini request that Token Factory does not recognise" | Not retried (may have been sent once). `doctor --deep`, another profile; don't resend in a loop |
| "Gemini returned an error instead of an answer" | Gemini's generic failure reply; retry once, then another profile |
| "did not answer … within 30s" / "locked by another Chrome" | Retry or `GEMCLI_CHROME_START_TIMEOUT=60`; close the Chrome named in the message |
| Model invalid / "Unknown model: …" | Unknown names fail up front with the available-model list (no traceback): gemini-3.8-flash, gemini-4-argon, gemini-3.7-flash, pro, thinking |
| Rate limited | Wait 30s, retry |
| Tool disabled / usage limit reached | `gemcli limits`, then switch accounts: `gemcli -p <profile> <command>` |
| WebSocket 500 / stale target | Retry — Token Factory reconnects automatically |

### Limits Notes

- `gemcli limits` prints **Account / Profile**, then grouped usage rows.
- Most features share one plan pool and report the same account-wide percentage
  (matches "Current usage" on the web page); **Video (Gemini Omni)** and
  **Deep Think** report their own, higher figures. `Credits Left` is the
  remaining balance of the pool (size depends on the plan); each row's reset time is what Google reports in `Resets In` (it differs by feature and account — don't assume a fixed window).
- The live web view is `https://gemini.google.com/usage`.
- Different accounts can have different features enabled — a disabled tool on one
  profile may be available on another.

For full documentation, install the complete skill: `gemcli skill install <tool>`

<!-- gemini-web-skill-end -->
