# Gemini Web MCP CLI - Troubleshooting Guide

## Quick Diagnosis

| Symptom | Likely Cause | Solution |
|---------|-------------|----------|
| "AuthError" or "expired" (exit code 3) | Session cookies expired | `gemcli login --check --all` first (read-only); switch to an `alive` profile; `gemcli login` only in an interactive session (see Exit Codes) |
| "Profile '…' is busy with another request" | Parallel jobs on one profile waited past the limit | Retry, use `-p <other>`, or raise `GEMCLI_PROFILE_LOCK_TIMEOUT` — see Heavy / Parallel Use |
| "Gemini did not read the attachment" | Upload reached Gemini but it couldn't open the file | Retry once; `gemcli -p <profile> doctor --deep`; another profile |
| `keepalive status` shows `token capture failed` | Signed in, but BotGuard capture broken on that profile | `gemcli -p <profile> doctor --deep`; use another profile meanwhile |
| "UsageLimitExceeded" (1037) | Too many requests | Wait 1-2 minutes, retry |
| "ModelInvalid" (1050/1052) | Wrong model name or no Token Factory | Check model name, run `gemcli doctor` |
| "TemporarilyBlocked" (1060) | IP rate limited by Google | Wait 5-10 minutes, try VPN |
| Chrome doesn't launch / "did not answer … within 30s" | Busy machine, or profile locked by another Chrome | Retry; `GEMCLI_CHROME_START_TIMEOUT=60`; close the Chrome named in the error |
| "Chrome sent the prompt through a Gemini request that Token Factory does not recognise" (`PromptEscaped`) | Gemini changed this account's chat transport again; the prompt may have been sent once and was not retried | Don't resend in a loop; `gemcli -p <profile> doctor --deep`; use another profile; report it |
| "Gemini returned an error instead of an answer" (`GeminiReplyError`) | Gemini's generic failure reply ("I seem to be encountering an error…"), usually temporary | Retry once; then another profile |
| TokenFactoryError | Token capture failed | `gemcli -p <profile> doctor --deep` (names the failing stage), then `gemcli chrome status`. Background: `gemcli chrome install-agent` |
| "gemini-web-mcp not found" | Binary not on PATH | `pip install gemini-web-mcp-cli[mcp]` |
| MCP tool returns error | Auth or network issue | Run `gemcli login`, then retry |
| Empty response from chat | Model returned no candidates | Try different model or rephrase prompt |
| Video generates image | Missing BotGuard/tool activation | `gemcli chrome start`, ensure Chrome running |
| Image generation fails | Missing BotGuard/tool activation | `gemcli chrome start`, ensure Chrome running |
| Music generation fails | Chrome/BotGuard or content policy | `gemcli chrome start`, then retry; `gemcli login` if auth error |
| "Unknown music style" | Invalid style preset name | Run `gemcli music --list-styles` for valid names |
| WebSocket 500 / stale target | Chrome restarted, stale CDP target ID | Retry — Token Factory reconnects to the new Chrome automatically |

---

## Authentication Issues

### Cookies Have Expired

**Symptoms:** Commands fail with `AuthError`, "session expired", or 401-like responses.

**Solution:**
```bash
gemcli login
# Or validate current session:
gemcli login --check
```

### Exit Codes (for scripts and agents)

Commands exit non-zero on failure, so `gemcli ... || <fallback>` works:

| Exit code | Meaning | What to do |
|-----------|---------|------------|
| `0` | Success | — |
| `1` | Generation/API/Token Factory error, busy profile, unread attachment | Read the message (table above); `gemcli -p <profile> doctor --deep` |
| `3` | Auth error — session expired or sign-in failed | `gemcli login --check --all`, then another profile (`gemcli -p <profile> ...`); if all fail, a human must run `gemcli login` |

**Never run `gemcli login` from a script, cron job or LaunchAgent.** It stops
the profile's Chrome daemon and opens a sign-in window nobody sees. Scheduled
session care is `gemcli keepalive install-agent`.

### Sessions Keep Expiring / Inactive Profiles Go Stale

**Symptoms:** Profiles you haven't used for a few days fail with exit code `3`;
switching profiles doesn't help because they are all stale.

**Solution:** keep every profile alive automatically:
```bash
gemcli login --check --all                           # See which profiles are signed in
gemcli keepalive run                                 # Renew all of them now
gemcli keepalive install-agent --every 4 --recover   # macOS: renew every 4 hours
gemcli keepalive status                              # Last result per profile
```
A profile reported `DEAD` needs `gemcli login --profile <name>` (Google asked
for a password, passkey, or verification). Avoid copying Chrome profile folders
between tools — sharing one session between several browsers gets it revoked.

### Chrome Doesn't Launch for Login

**Symptoms:** `gemcli login` hangs or errors about Chrome.

**Solutions:**
1. Close all Chrome instances first
2. Check Chrome is installed: `gemcli doctor --verbose`
3. Fall back to manual mode: `gemcli login --manual`

### Login Over SSH (macOS)

**Symptoms:** `gemcli login` on a remote Mac via SSH says "cannot open a browser window".

macOS blocks WindowServer access from SSH sessions, so Chrome can't show a login window.

**For refreshing an existing session** — works automatically. `gemcli login` runs Chrome headlessly and extracts cookies without a visible window.

**For a new login** — use one of:
```bash
gemcli login --manual   # Paste cookies from Chrome DevTools (open Chrome on any machine)
```
Or connect via Screen Sharing / VNC to the Mac's desktop and run `gemcli login` there.

### Manual Cookie Entry

If automated Chrome login fails:

```bash
gemcli login --manual
```

Then extract cookies from Chrome DevTools:
1. Open `gemini.google.com` in Chrome
2. Open DevTools (F12) > Application > Cookies
3. Copy `__Secure-1PSID` and `__Secure-1PSIDTS` values
4. Paste when prompted

### NotebookLM Profile Not Working

**Symptoms:** Profile from NLM shows "not authenticated" in gemcli.

**Cause:** NLM profiles share Chrome sessions but gemcli needs its own Gemini cookies.

**Solution:**
```bash
gemcli login --profile <nlm-profile-name>
```

---

## Model-Specific Issues

### Pro/Thinking Model Returns Flash Responses

**Cause:** Without a BotGuard token, Google ignores the model header and returns Flash.

**Solution:** Token Factory must be operational:
1. Chrome must be installed and accessible
2. Run `gemcli doctor --verbose` to check Chrome status
3. Ensure all browser cookies are captured (not just 2)

### "ModelInvalid" Error (1050/1052)

**Cause:** Invalid model identifier.

**Valid models:**
- `gemini-3.8-flash` (or just `flash`; `gemini-3.7-flash` is the same hash)
- `gemini-4-argon` (or just `argon`)
- `gemini-3.1-pro` (or just `pro`)
- `gemini-3.5-flash-lite` (or just `lite`)
- `thinking` / `--thinking-level high` (High is the old Extended thinking toggle)

### "Unknown model" Error (before any request)

**Symptom:** One-line `Unknown model: '…'. Available: …` (exit 1, no traceback).

**Cause:** The name is not in the Gemini Web catalog. The web picker currently
lists 3.5 Flash-Lite, 3.8 Flash, 3.1 Pro, and 4 Argon.

**Solution:** Use a supported alias or ID from the list in the error. Every
command that takes `--model` (`chat`, `research`, `image`, `video`, `music`)
rejects unknown names before authentication or uploads. Do not substitute
unverified model hashes.

### Token Factory Error

**Symptoms:** `TokenFactoryError` when uploading files, generating images/video/music, using Pro/Argon/non-low thinking, or `--task`.

**Checks:**
1. `gemcli -p <profile> doctor --deep` — runs the real path (BotGuard token capture + a tiny upload) and names the failing stage. Sends nothing to Gemini chat.
2. Is the Chrome daemon authenticated? `gemcli chrome status` verifies both the Google auth cookie and Gemini's live `SNlM0e`
3. Daemon unhealthy? `gemcli chrome stop && gemcli chrome start` (stop waits for running jobs; don't use `--now` while jobs run)
4. Running from a background process? Start persistent Chrome: `gemcli chrome install-agent`
5. Still failing on one profile while another works? Use the working profile (`-p`) and re-check the broken one later with `doctor --deep`.

`doctor --deep` and `keepalive status` also name the account's chat transport:
`streamgenerate` (classic) or `processSession` (Gemini's WebChannel transport,
rolled out per account from Sep 2026). gemcli detects it on every request and
supports both, including Pro, attachments, images and follow-ups.

When token capture fails for a request with attachments or an image/video/music
tool, gemcli exits 1 ("Not retrying without Chrome"). It used to quietly retry
without Chrome, and Gemini then invented an answer about a file it never saw.

Token Factory never injects saved `auth.json` cookies into Chrome (sharing one session between browsers gets it revoked). If `gemcli chrome status` reports the daemon is not authenticated, run `gemcli login --profile <name>`; use `gemcli login --force` only when Google has invalidated the saved cookies and a plain `gemcli login` window fails — it also signs Chrome itself out of that account.

### Token Factory in Background Processes (LaunchAgent, cron, SSH)

**Symptoms:** `TokenFactoryError` when running from macOS LaunchAgent, cron job, systemd service, or SSH without display. Chrome cannot launch because background processes lack WindowServer/TCC access.

**Solution:** Start persistent Chrome from an interactive terminal, or install a LaunchAgent:
```bash
gemcli chrome start              # Start headless daemon (survives terminal close)
gemcli chrome install-agent      # Auto-start at login (survives reboot)
gemcli chrome status             # Verify running + live Gemini auth
```

Token Factory will automatically find the persistent Chrome on ports 9222-9231.

**After reboot:** Either use `gemcli chrome install-agent` for automatic restart, or run `gemcli chrome start` again from an interactive terminal.

---

## Heavy / Parallel Use (pipelines)

Every Gemini request passes through the profile's Chrome to get a BotGuard
token, and that Chrome has one Gemini tab. Since 0.8.3 every process takes a
**per-profile lock** (`~/.gemini-web-mcp-cli/locks/<profile>.lock`) for that
step, so parallel jobs queue instead of overwriting each other. Before 0.8.3,
collisions surfaced as a false "Session expired — auto sign-in failed".

- **Throughput:** jobs on one profile run their token step one at a time (a
  few seconds each); the generation itself still runs in parallel. Spread
  large batches across profiles with `-p`.
- **Wait limit:** a job waits up to `GEMCLI_PROFILE_LOCK_TIMEOUT` seconds
  (default 300), then fails with "Profile '…' is busy". Raise it for long
  queues rather than retrying in a tight loop.
- **Safe maintenance:** `gemcli chrome stop`, `gemcli login` and the
  keep-alive wait for running jobs. The daemon's 12h / 1.5 GB restart only
  happens while it is idle. `gemcli chrome stop --now` does not wait.
- **Don't** schedule `gemcli chrome stop/start` or `gemcli login` — the daemon
  restarts itself safely, and `gemcli keepalive install-agent` keeps sessions
  alive.
- **Slow Chrome starts:** the daemon gets 30s to come up
  (`GEMCLI_CHROME_START_TIMEOUT`). `chrome-agent.log` lines are timestamped.
- **Other Chrome-driving tools** on the same machine share CPU, memory and
  ports. To isolate gemcli, point it at its own Chromium build:
  `gemcli config set browser "/path/to/Chrome for Testing"` (or `GEMCLI_BROWSER`).

---

## Image/Video/Music Generation Issues

### Image Generation Fails / "No images generated"

**Common causes:**
- Chrome not running — image generation requires BotGuard + tool activation (`gemcli chrome start`)
- Wrong model — image generation defaults to Pro; Flash requires explicit `-m flash` and Flash image gen enabled on account
- Content policy rejection (try different prompt)
- Auth cookies expired (`gemcli login`)

**Headless/background environments:** Image generation requires Chrome for BotGuard token capture. Ensure the persistent Chrome daemon is running: `gemcli chrome start` or install the LaunchAgent: `gemcli chrome install-agent`

### Music Generation Fails

**Common causes:**
- Chrome not running — music requires BotGuard even on Flash (`gemcli chrome start`)
- Content policy rejection (try different prompt or style)
- Auth cookies expired (`gemcli login`)
- Invalid style preset name (run `gemcli music --list-styles` for valid names)
- Running from background process — start persistent Chrome first

**Style preset tips:**
- Use exact preset names: `8-bit`, `k-pop`, `cinematic`, etc.
- Aliases also work: `chiptune` → `8-bit`, `kpop` → `k-pop`, `ambient` → `forest-bath`
- Case-insensitive: `K-Pop`, `k-pop`, `K-POP` all work

### Video Generation Produces Image Instead of Video

**Cause:** Video generation requires Chrome for BotGuard token + tool activation (tool_id=11). Without these, Gemini falls back to image generation.

**Solution:**
```bash
gemcli chrome start          # Ensure Chrome is running
gemcli limits                # Check video quota
gemcli video "prompt" -o out.mp4
```

### Video Generation Times Out

Videos via Veo 3.1 take 1-2 minutes to generate. If polling times out:
```bash
# Check status manually
gemcli video "prompt"  # Start generation
# Wait and check again
```

---

## MCP Server Issues

### "gemini-web-mcp binary not found"

**Solution:**
```bash
pip install gemini-web-mcp-cli[mcp]
# Or with uv:
uv pip install gemini-web-mcp-cli[mcp]
```

Then verify: `gemcli doctor`

### MCP Client Can't Connect

1. Check the server is configured: `gemcli setup list`
2. Add to your tool: `gemcli setup add <tool>`
3. Restart the AI tool after adding

### MCP Tool Returns Auth Error

The MCP server shares authentication with the CLI:
```bash
gemcli login           # Refresh auth
# Then restart the MCP-connected AI tool
```

---

## Network Issues

### IP Temporarily Blocked (Error 1060)

Google may temporarily block IPs making too many requests.

**Solutions:**
- Wait 5-10 minutes before retrying
- Use a VPN or different network
- Reduce request frequency

### Rate Limiting

Recommended delays between operations:
- Chat messages: 2 seconds
- Image generation: 5 seconds
- Video generation: 10 seconds (plus polling)
- Music generation: 5 seconds (plus polling)
- Research queries: 5 seconds

---

## Configuration Issues

### Config Directory Not Found

**Solution:** Run `gemcli login` to initialize the config directory at `~/.gemini-web-mcp-cli/`.

### Profile Doesn't Exist

```bash
gemcli profile list    # See available profiles
gemcli profile create <name>  # Create new one
```

### Wrong Active Profile

```bash
gemcli profile switch <name>
# Or use --profile flag for one-off:
gemcli chat "hello" --profile work
```

---

## Updating gemcli

### New Version Not Found After Release

**Symptoms:** `uv tool install --force gemini-web-mcp-cli` still installs the old version, or uv reports "no version found" for a specific release.

**Cause:** uv caches the PyPI package index locally. After a new release, the cached index may not include the new version yet — even if PyPI has it.

**Solution:**
```bash
uv cache clean && uv tool install --force --refresh gemini-web-mcp-cli
```

- `uv cache clean` — removes cached packages and index metadata
- `--refresh` — forces uv to re-fetch the package index from PyPI instead of using a cached copy

If you want to pin to a specific version:
```bash
uv cache clean && uv tool install --force --refresh 'gemini-web-mcp-cli==0.3.15'
```

After installing, verify:
```bash
gemcli --version
```

---

## Getting Help

```bash
gemcli --help              # All commands
gemcli <command> --help    # Specific command help
gemcli --ai                # AI-optimized full docs
gemcli doctor --verbose    # Detailed diagnostics
gemcli -p <profile> doctor --deep   # Test the live path (token capture + upload)
```

If issues persist, check the project repository for known issues.
