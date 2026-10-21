---
name: gemini-web-skill
description: "Expert guide for the Gemini Web MCP CLI (`gemcli`) and MCP server - interfaces for Google Gemini (gemini.google.com). Use this skill when users want to interact with Gemini programmatically, including: chatting with models, generating images, generating videos, generating music, deep research, managing Gems (custom personas), or automating Gemini workflows. Triggers on mentions of \"gemcli\", \"gemini web mcp\", \"gemini chat\", \"image generation\", \"video generation\", \"music generation\", \"deep research\", \"gems\", or any Gemini web-related automation task."
version: "0.9.7"
---

# Gemini Web MCP CLI & MCP Expert

This skill provides comprehensive guidance for using Google Gemini via both the `gemcli` CLI and MCP tools.

## Tool Detection (CRITICAL - Read First!)

**ALWAYS check which tools are available before proceeding:**

1. **Check for MCP tools**: Look for tools starting with `mcp__gemini-web-mcp__*`
2. **If BOTH MCP tools AND CLI are available**: **ASK the user** which they prefer
3. **If only MCP tools are available**: Use them directly (refer to tool docstrings for parameters)
4. **If only CLI is available**: Use `gemcli` CLI commands via Bash

**Decision Logic:**
```
has_mcp_tools = check_available_tools()  # Look for mcp__gemini-web-mcp__*
has_cli = check_bash_available()          # Can run gemcli commands

if has_mcp_tools and has_cli:
    # ASK USER: "I can use either MCP tools or the gemcli CLI. Which do you prefer?"
    user_preference = ask_user()
elif has_mcp_tools:
    # Use MCP tools directly
    mcp__gemini-web-mcp__chat(action="send", prompt="Hello")
else:
    # Use CLI via Bash
    bash("gemcli chat 'Hello'")
```

This skill documents BOTH approaches. Choose based on tool availability and **user preference**.

## Quick Reference

**Run `gemcli --ai` to get comprehensive AI-optimized documentation.**

```bash
gemcli --help              # List all commands
gemcli <command> --help    # Help for specific command
gemcli --ai                # Full AI-optimized documentation (RECOMMENDED)
gemcli --version           # Check installed version
gemcli doctor              # Diagnose installation and auth
```

## Route-specific model names

This tool uses Gemini's **web** catalog. Relay/Antigravity crew model IDs do not establish availability here. Before file or video analysis, check `gemcli chat --help` and use a supported model alias or ID. The web catalog currently lists `gemini-3.5-flash-lite`, `gemini-3.8-flash`, `gemini-3.1-pro`, and `gemini-4-argon` (captured 2026-10-13; `gemini-3.7-flash` remains an alias of 3.8 Flash). Every command that takes `--model` (`chat`, `research`, `image`, `video`, `music`) rejects an unknown name up front with a one-line "Unknown model: … Available: …" error — no traceback — before authentication or uploads. Do not substitute unverified model hashes.

## Critical Rules (Read First!)

1. **Always authenticate first**: Run `gemcli login` before any operations
2. **Session expiry**: Cookies can expire — auto-recovery handles this silently (see below). Exit code `3` means an auth error; `1` means any other failure
3. **Model selection**: Gemini 3.8 Flash is the default fast model (`gemini-3.7-flash` is the same hash). Thinking level is `low` / `medium` / `high`; Pro, Argon, and non-low thinking need Token Factory (Chrome + BotGuard). `--task` uses the Chat/Task control
4. **Music generation requires Chrome**: Music (Lyria 3) needs a BotGuard token even on Flash. Start persistent Chrome first: `gemcli chrome start`
5. **Video generation requires Chrome**: Video (Veo 3.1) needs BotGuard + tool activation. Start persistent Chrome first: `gemcli chrome start`
6. **Image generation requires Chrome**: Image generation needs BotGuard + tool activation. Defaults to Nano Banana Pro (Gemini 3 Pro Image); use `-m flash` for Nano Banana 2 (Gemini 3.1 Flash Image, requires Flash image gen enabled on account). Start persistent Chrome first: `gemcli chrome start`
7. **Interactive chat**: `gemcli chat` without a prompt opens an interactive REPL with slash commands
8. **NotebookLM cross-product**: If you have NotebookLM MCP installed, gemcli can reuse its Chrome profiles
9. **Background processes (LaunchAgent/cron)**: Cannot launch Chrome. Either install a LaunchAgent (`gemcli chrome install-agent`) or start persistent Chrome from an interactive terminal first: `gemcli chrome start`
10. **Parallel jobs are safe; they queue per profile**: requests on the same profile take turns in its Chrome (a few seconds each for the token step; generation itself still runs in parallel). For more throughput, spread jobs across profiles with `-p <profile>`. Never "fix" slowness by stopping or restarting Chrome.
11. **Never schedule `gemcli login`** (cron, LaunchAgent, pipeline step). It stops the profile's Chrome daemon and opens a window nobody sees. Use `gemcli keepalive install-agent` to keep sessions alive.
12. **Use `--help` when unsure**: Run `gemcli <command> --help` for available options

## Failure Triage (AI AGENTS — MANDATORY)

Branch on the **exit code**, then on the message. `0` = success, `3` = auth
(a sign-in may be needed), `1` = anything else. Never loop: at most **one
retry per step**, then move on.

### Exit 3 — "Session expired" / `AuthError`

1. **Check before acting (read-only):** `gemcli login --check --all`.
   - The profile is `alive` → the session is fine; retry the command once.
   - `stale` → only the saved copy is old: `gemcli -p <profile> keepalive run`, then retry once.
   - `DEAD` → go to step 2.
2. **Switch profiles:** rerun with `-p <another alive profile>`.
3. **Interactive session with a user present only:** `gemcli login --profile <name>`
   (refreshes silently in ~5s if Chrome is still signed in; waits for running
   jobs on that profile first). **Unattended / background / pipeline: never run
   `gemcli login`** — report the profile name instead.
4. Still failing → tell the user which profile needs a manual sign-in.

Avoid `gemcli login --force` unless the user asks: it signs Chrome itself out
of that account and removes the one-click "Continue as…" sign-in.

### Exit 1 — read the message

| Message contains | What it means | Do this |
|---|---|---|
| `Profile '<name>' is busy with another request` | Other jobs held the profile's Chrome longer than the wait (default 300s) | Retry, or use `-p <other>`. For long queues set `GEMCLI_PROFILE_LOCK_TIMEOUT=900`. Do **not** stop/restart Chrome. |
| `Gemini did not read the attachment` | The upload reached Gemini but it could not open the file; the answer was withheld because it is usually invented | Retry once; then `gemcli -p <profile> doctor --deep`; then another profile. Never use a reply that says it can't open the file. |
| `Not retrying without Chrome` / `Failed to capture BotGuard token` / `TokenFactoryError` | Token capture failed (uploads, images, video, music, Pro all need it) | `gemcli -p <profile> doctor --deep` names the failing stage. Then `gemcli chrome status`. If the daemon is unhealthy: `gemcli chrome stop && gemcli chrome start` (stop waits for running jobs). Else another profile. |
| `Chrome sent the prompt through a Gemini request that Token Factory does not recognise` (`PromptEscaped`) | Gemini changed how this account sends chats; the prompt may have gone out once and was **not** retried | Don't resend in a loop. `gemcli -p <profile> doctor --deep`; use another profile meanwhile; report it |
| `Gemini returned an error instead of an answer` (`GeminiReplyError`) | Gemini replied with its generic failure text ("I seem to be encountering an error…"); usually a temporary server-side error | Retry once; if it repeats, use another profile. Never use that sentence as content. |
| `did not answer on port … within 30s` | Chrome started too slowly (machine busy) | Retry; or `GEMCLI_CHROME_START_TIMEOUT=60` |
| `The profile is locked by another Chrome (host-PID)` | A login window or another Chrome is open on that profile | Close that window/process. Don't delete lock files. |
| `tool is disabled` / `UsageLimitExceeded` | Quota used up | `gemcli limits`, then `-p <other>` (see Profile Management) |

### Health checks that prove the real path

- `gemcli -p <profile> doctor --deep` — captures a BotGuard token in Chrome and
  uploads a tiny file. Sends nothing to Gemini chat, uses no quota. Exit 1 if
  anything fails. Plain `gemcli doctor` only checks that credentials are *saved*.
- `gemcli keepalive status` — per profile: session `alive/stale/DEAD` **and**
  `token capture ok/failed` (a profile can be signed in while capture fails).
- Both also show the account's **chat transport**: `streamgenerate` or
  `processSession` (Gemini's newer WebChannel transport, rolled out per account
  in Sep 2026). Both are supported; the transport is detected on every request.

### Never do this while other gemcli jobs may be running

`gemcli chrome stop --now`, killing Chrome processes, deleting `Singleton*`
lock files, copying Chrome profile folders, or `gemcli login --force`. Each of
these breaks in-flight jobs or the session itself.

```bash
# Example: a batch job fails with exit 3
gemcli login --check --all              # read-only: which profiles are alive?
gemcli -p work image "A sunset" -o s.png  # retry on an alive profile
```

## Workflow Decision Tree

```
User wants to...
|
+--> Chat with Gemini
|    +--> Single message -> gemcli chat "prompt" [-m model]
|    +--> With file(s) -> gemcli chat "analyze" -f file.pdf [-f file2.png]
|    +--> Interactive REPL -> gemcli chat (no prompt)
|    +--> With extensions -> gemcli chat "@youtube summarize ..."
|
+--> Upload files
|    +--> With chat -> gemcli chat "describe this" -f image.png
|    +--> Standalone -> gemcli file upload document.pdf
|
+--> Generate images (Nano Banana / Nano Banana Pro)
|    +--> gemcli image "prompt" [-o output.png] [-m pro|flash] [-A 1:1|9:16|3:4|4:3|16:9]
|
+--> Generate videos (Gemini Omni)
|    +--> gemcli video "prompt" [-o output.mp4] [-O landscape|portrait] [-m flash|pro|lite|thinking]
|    +--> With template -> gemcli video -T "Logo reveal" "prompt" -o logo.mp4
|
+--> Generate music (Lyria 3.5)
|    +--> gemcli music "prompt" [-o track.mp3] [-L short|standard] [-V custom|vocals|instrumental]
|    +--> With genre -> gemcli music "prompt" -g lo-fi
|    +--> With template -> gemcli music -T "Brand jingle" "prompt" -o jingle.mp3
|    +--> With legacy style preset -> gemcli music "prompt" -s 8-bit
|    +--> List presets -> gemcli music --list-styles
|
+--> Check quota before generating
|    +--> gemcli limits            # account + per-feature % used and credits left
|    +--> gemcli -p <profile> limits   # compare another account before flipping
|
+--> Deep Research
|    +--> gemcli research "query" [-m model]
|
+--> Manage Gems (custom personas)
|    +--> List gems -> gemcli gems list
|    +--> Create gem -> gemcli gems create --name "Name" --prompt "..."
|    +--> With NotebookLM -> gemcli gems create ... --notebook <uuid>
|    +--> Delete gem -> gemcli gems delete <gem_id>
|
+--> First-time setup
|    +--> gemcli login -> gemcli doctor
|
+--> Persistent Chrome (for music, Pro model, or background processes)
|    +--> gemcli chrome start           # Start headless Chrome daemon
|    +--> gemcli chrome install-agent   # Auto-start at login (survives reboot)
|    +--> gemcli chrome status          # Check if running + authenticated
|    +--> gemcli chrome stop            # Stop Chrome daemon
|
+--> Check usage limits / remaining quota
|    +--> gemcli limits              # Per-feature usage, limits, and reset times
|
+--> Use Gemini inside Claude Code
|    +--> gemcli hack claude                  # Launch with default model
|    +--> gemcli hack claude --model gemini-pro
|
+--> Configure AI tools
     +--> gemcli setup add <tool>    (MCP server)
     +--> gemcli skill install <tool> (skill docs)
```

## Command Categories

### 1. Authentication

#### CLI Authentication
```bash
gemcli login                    # Automated Chrome login via CDP
gemcli login --check            # Validate current session
gemcli login --check --all      # Health of every profile (read-only)
gemcli login --manual           # Paste cookies manually
gemcli login --profile work     # Use named profile
```

#### MCP Authentication
If using MCP tools and encountering auth errors, run `gemcli login` from the CLI to refresh cookies.

### 2. Chat

#### MCP Tool
```python
mcp__gemini-web-mcp__chat(action="send", prompt="Hello", model="pro")
mcp__gemini-web-mcp__chat(action="send", prompt="Follow up", conversation_id="abc123")
mcp__gemini-web-mcp__chat(action="send", prompt="@youtube summarize this", extensions=["youtube"])
mcp__gemini-web-mcp__chat(action="send", prompt="Analyze this", files=["/path/to/doc.pdf"])
```

#### CLI Commands
```bash
gemcli chat "What is quantum computing?"          # Single message
gemcli chat "Solve this carefully" -m gemini-3.8-flash --thinking-level high
gemcli chat "Explain this" -m gemini-3.1-pro      # Use Pro model
gemcli chat "Complex plan" -m gemini-4-argon      # Gemini 4 Argon
gemcli chat --task "Collect recipes from my inbox"  # Task / agent mode
gemcli chat "Summarize" -o summary.md             # Save to file
gemcli chat "Analyze this" -f document.pdf        # Chat with file attachment
gemcli chat "Compare" -f a.md -f b.md             # Multiple files
gemcli chat                                        # Interactive REPL
```

**Interactive REPL Slash Commands:**
- `/model <name>` - Switch model
- `/thinking on|off|low|medium|high` - Set thinking level (`on` = high)
- `/task on|off` - Send later messages as a Task or a Chat
- `/verify` - Show server model hash
- `/new` - Start new conversation
- `/save <file>` - Export conversation
- `/history` - View turns
- `/help` - Show help
- `/quit` - Exit

### 3. Image Generation (Nano Banana)

**Full prompting reference:** See `references/IMAGE_PROMPTING_GUIDE.md` (installed alongside this skill) for the complete guide with templates, recipes, art styles, and examples optimized for Nano Banana.

**Quick rules:**
1. **Structure:** Subject → Action → Location → Composition → Style → Constraints
2. **Be specific:** "worn navy blue tweed jacket, shallow depth of field" not "nice jacket"
3. **No vague praise:** Avoid "stunning, epic, 8K" — use concrete visual facts
4. **Text in images:** Put text in **"quotes"**, specify font, keep to **25 chars or fewer**, max 2–3 phrases
5. **Positive framing:** "empty street" not "no cars"
6. **Check quota first:** Run `gemcli limits` before generating

**Prompt template:**
```
[Subject with specific appearance/materials] [action/pose], [location/backdrop].
[Shot type, angle]. [Camera/film style, lighting, color grading].
[Text if needed: "TEXT" in bold white sans-serif]. Constraints: no watermark, no extra text.
```

**Example prompts:**
```bash
# Photorealistic
gemcli image "Photorealistic product shot of an amber glass serum bottle on polished black marble. Hard directional light from upper-right. Label reads 'ÉCLAT' in thin white serif. No watermark." -o serum.png

# Editorial/fashion
gemcli image "Fashion model in tailored brown dress, confident stance, deep cherry red studio backdrop. Medium-full shot. Medium-format analog film, high saturation, cinematic grain." -o fashion.png

# With Nano Banana 2 (Flash, faster)
gemcli image "Minimalist armchair, walnut frame, cream boucle, sun-drenched living room. Photorealistic 3D render." -m flash -o chair.png

# Explicit aspect ratio (Images composer control)
gemcli image "A vertical movie poster" -A 9:16 -o poster.png
gemcli image "A wide banner" -A 16:9 -o banner.png
```

**Aspect ratio:** `-A` / `aspect` supports `1:1`, `9:16`, `3:4`, `4:3`, `16:9`
(aliases: square, portrait, landscape). Other ratios must be requested in the
prompt text.

#### MCP Tool
```python
mcp__gemini-web-mcp__image(action="generate", prompt="A product shot...", output_path="img.png")
mcp__gemini-web-mcp__image(action="download", image_url="https://...", output_path="img.png")
```

#### CLI Commands
```bash
gemcli image "A red panda in bamboo forest, macro lens, shallow depth of field" -o panda.png
gemcli image "Futuristic city at night, cinematic wide angle, neon reflections" -o city.png
gemcli image "Logo: bold white 'APEX' text on dark marble" -m flash -o logo.png
gemcli image "A vertical poster" -A 9:16 -o poster.png
gemcli limits          # Check image quota before generating
```

### 4. Video Generation (Gemini Omni / Veo 3.1)

**Full prompting reference:** See `references/VIDEO_PROMPTING_GUIDE.md` (installed alongside this skill) for the complete guide with templates, cinematic direction, style transfer, kinetic typography, recipes, and common mistakes optimized for Gemini Omni.

**Supported options:**
- **Orientation:** `landscape` (16:9, default) or `portrait` (9:16) via `-O` / `orientation`.
- **Model:** `flash` (default), `pro`, `lite`, `thinking` via `-m` / `model`. Pro and thinking videos use the higher-quality Omni engine.
- **Templates:** `-T` / `template` selects a Create-videos template (`Anime`, `Logo reveal`, `8-bit adventure`, `Storybook`, `Product showcase`, ...). Templates prefill the style; your prompt and orientation still apply.
- **Reference inputs:** `-f` / `files` uploads reference images/videos (Omni uses them as references — e.g. animate a still image). Reference generations can take **5-15 minutes** (longer than text-only videos); `-o` waits up to 15 minutes. If the wait times out, the video still completes in the conversation — open the chat in the web UI to find it.

**Quick rules:**
1. **Describe intent, not pixels:** Omni is a reasoning world model; describe the visual goal and let it handle physical rendering.
2. **Edit iteratively:** Use multi-turn conversation to refine details; change one variable per turn.
3. **Lock what works:** Explicitly instruct the model to keep unchanged elements: "Keep everything identical. Change butterfly to bee."
4. **Cinematic camera terms:** Direct the camera using professional terms: "oner", "push in", "dolly zoom", "static camera", "locked off".
5. **Stack multimodal inputs:** Stack visual forms, sound tempos, and reference tags: `<video> + <image> + <audio>`.
6. **Use visual storyboards:** Feed storyboard frames with sequential execution timing instructions.
7. **Check quota first:** Run `gemcli limits` before initiating a generation.

**Prompt template:**
```
Subject: [focal character, materials, textures, colors]
Action/Interaction: [movements or how subjects interact with environment]
Location/Context: [backdrop, setting, atmosphere]
Lighting: [light source direction, quality, color, reflections]
Style/Aesthetic: [art style: risograph, waxy crayon, 3D translucent glass]
Cinematography: [camera setup, lens framing, movement, timing/oner instructions]
```

**Example prompts:**
```bash
# Cinematic Oner
gemcli video "Subject: vintage leather boots. Action: walking. Location: wet Tokyo alley. Lighting: neon reflections catching fog. Style: photorealistic. Cinematography: low-angle close-up tracking shot tilting up to medium shot, slow-motion fluid oner." -o boots.mp4

# Kinetic Typography Sizzle Reel
gemcli video "Kinetic typography did you know. Solid black screen. Text flashes word-by-word: 'did', 'you', 'know', 'that', 'this', 'model', 'can', 'do', 'pretty', 'good', 'text!?'. Different animated style per word, perfect pacing to a hip-hop rhythm." -o kinetic.mp4
```

#### MCP Tool
```python
mcp__gemini-web-mcp__video(action="generate", prompt="Ocean waves at sunset")
mcp__gemini-web-mcp__video(action="generate", prompt="A vertical story", orientation="portrait", model="pro")
mcp__gemini-web-mcp__video(action="generate", prompt="NAIDA'S salon", template="Logo reveal")
mcp__gemini-web-mcp__video(action="generate", prompt="Animate this", files=["poster.png"])
mcp__gemini-web-mcp__video(action="status")         # Check progress
```

#### CLI Commands
```bash
gemcli video "Ocean waves at sunset"
gemcli video "Dancing robot" -o robot.mp4
gemcli video "A vertical story for Shorts" -O portrait -o story.mp4
gemcli video "A cinematic oner" -m pro -O landscape -o shot.mp4
gemcli video -T "Logo reveal" "NAIDA'S hair salon" -o logo.mp4
gemcli video "Animate this: the balloon drifts at sunrise" -f poster.png -o motion.mp4
```

### 5. Music Generation (Lyria 3.5)

Generates music tracks with vocals, lyrics, instrumentals, and auto-generated cover art. The Lyria 3.5 composer supports Length, Vocals, and Genre controls plus 24 template cards; 16 legacy style presets remain available via `-s`.

#### MCP Tool
```python
# Generate a track
mcp__gemini-web-mcp__music(action="generate", prompt="A comical R&B slow jam about a sock")

# Generate with a style preset
mcp__gemini-web-mcp__music(action="generate", prompt="Cats playing games", style="8-bit")

# Generate and auto-download
mcp__gemini-web-mcp__music(action="generate", prompt="Summer vibes", style="k-pop", output_path="track.mp3")

# Use the new Lyria 3.5 composer controls
mcp__gemini-web-mcp__music(action="generate", prompt="A chill study beat", genre="lo-fi", length="short")
mcp__gemini-web-mcp__music(action="generate", prompt="An upbeat ad jingle", vocals="vocals", genre="pop", template="Brand jingle", output_path="jingle.mp3")

# List available style presets
mcp__gemini-web-mcp__music(action="list_styles")

# Download a track from a previous generation
mcp__gemini-web-mcp__music(action="download", download_url="https://...", output_path="track.mp3")
```

#### CLI Commands
```bash
gemcli music "A comical R&B slow jam about a sock"
gemcli music "Cats playing video games" -s 8-bit -o track.mp3
gemcli music "Summer vibes" -s k-pop -o video.mp4 -f video
gemcli music "A chill study beat" -g lo-fi -L short
gemcli music "An upbeat ad jingle" -V vocals -g pop -T "Brand jingle" -o jingle.mp3
gemcli music --list-styles                  # Show all 16 style presets
```

**Composer controls (Lyria 3.5):**
- `-L` / `length`: `short` or `standard`
- `-V` / `vocals`: `custom` (from prompt), `vocals` (vocals on), `instrumental`
- `-g` / `genre`: pop, hip-hop & rap, rock, k-pop, latin, electronic, r&b, country, afrobeats, reggae, jazz & blues, classical, folk, lo-fi, acoustic, cinematic, ambient
- `-T` / `template`: Soundscape, Background music, Memorize something, Text messages, Intro music, Montage, Say it with a track, Brand jingle, Ringtone, Streaming, Speech to song, Rap battle, Comedy, Team anthem, Sports recap, Party invite, Happy birthday, Friend appreciation, Love story, Birthday roast, Ode to your pet, Hometown tribute, Weather report, Business promo

**Legacy Style Presets:** 90s-rap, latin-pop, folk-ballad, 8-bit, workout, reggaeton, rnb-romance, kawaii-metal, cinematic, emo, afropop, forest-bath, k-pop, birthday-roast, folk-a-cappella, bad-music.

**Aliases:** rap, latin, folk, chiptune, edm, rnb, r&b, kawaii, metal, orchestral, ambient, kpop, birthday, roast, country, acappella, bad.

### 6. File Upload

Upload files (images, PDFs, documents, audio) to provide context for chat conversations.

#### MCP Tool
```python
# Upload a file and get its identifier
mcp__gemini-web-mcp__file(action="upload", file_path="/path/to/document.pdf")

# Chat with file attachments (handles upload automatically)
mcp__gemini-web-mcp__chat(action="send", prompt="Summarize this", files=["/path/to/doc.pdf"])
```

#### CLI Commands
```bash
gemcli chat "What is this?" -f image.png              # Attach file to chat
gemcli chat "Compare these files" -f a.md -f b.md     # Multiple attachments
gemcli file upload document.pdf                        # Standalone upload
```

**Notes:**
- File attachments require Chrome (BotGuard token needed). Run `gemcli chrome start` first.
- If Gemini replies that it can't open the file, gemcli exits 1 with
  `Gemini did not read the attachment` instead of returning that reply (it
  usually goes on to invent a description). See Failure Triage.
  `GEMCLI_ATTACHMENT_CHECK=0` disables the check.
- Supported types: images (PNG, JPEG, GIF, WebP), PDFs, text/documents, audio, and video.
- Files expire after ~1 day (`ttl_1d` in the identifier).

#### Upload Limits (Gemini Apps, as of July 2026)

These are the service-side limits enforced by gemini.google.com. Exceeding them
returns an error or a truncated/missed-detail analysis.

| Limit | Free | Google AI Pro / Ultra |
|-------|------|------------------------|
| Files per prompt | Up to 10 (any mix of types) | Up to 10 |
| Max size per **video** | 2 GB | 2 GB |
| Max size per **other file** (image, PDF, doc, audio) | 100 MB | 100 MB |
| Total **video** length | 5 min | 1 hour |
| Total **audio** length | 10 min | 3 hours |
| Code folder / GitHub repo | 5,000 files, 100 MB | 5,000 files, 100 MB |
| ZIP archive | 10 files, 100 MB (no audio/video inside) | same |

- **Context window:** Very large files can exceed the model's context window and
  produce responses that miss connections/details. Free plans have a smaller
  context; Pro/Ultra unlock up to a 1M-token window. Prefer smaller, focused files.
- **Rolling quotas:** Upload/analyze volume is rate-limited over a rolling period
  and resets over time. Run `gemcli limits` to check current remaining quota
  before large batches.
- **Large videos:** Uploads stream in 1 MB chunks with a dynamic timeout, so
  multi-hundred-MB videos (e.g. 200 MB) work, but stay under the 2 GB / duration
  caps above.

#### Video Analysis — Model Choice

Use the default **Gemini 3.8 Flash** (`fast`) for video analysis. It handles
describe/summarize/"what's happening" tasks well, is much faster and cheaper than
Pro, and has the same 2 GB / duration upload caps. Example:

```bash
gemcli chat "What happens in this video?" -f clip.mp4          # default = 3.8 Flash
gemcli chat "Describe this" -f clip.mp4 -m gemini-3.8-flash    # explicit
```

Reach for **Pro** (`gemini-3.1-pro`) only when the video is long (near the 1-hour
Pro cap) or the question needs deep multi-step reasoning (e.g. "analyze the
strategy and explain why the winning play worked"):

```bash
gemcli chat "Break down the tactics and who won and why" -f game.mp4 -m gemini-3.1-pro
```

Source: [Gemini Apps Help — Upload & analyze files](https://support.google.com/gemini/answer/14903178)

### 7. Deep Research

#### MCP Tool
```python
mcp__gemini-web-mcp__research(action="start", query="AI advances in 2026")
mcp__gemini-web-mcp__research(action="status")       # Check progress
```

#### CLI Commands
```bash
gemcli research "Latest AI advances in 2026"
gemcli research "Quantum computing breakthroughs" -m gemini-3.1-pro
```

### 8. Gems (Custom Personas)

#### MCP Tool
```python
mcp__gemini-web-mcp__gems(action="list")
mcp__gemini-web-mcp__gems(action="list_notebooks")  # List NotebookLM notebooks for attachment
mcp__gemini-web-mcp__gems(action="create", name="Reviewer", system_prompt="You are...")
mcp__gemini-web-mcp__gems(action="create", name="Researcher", system_prompt="...",
    notebook_ids=["uuid1", "uuid2"])  # Attach NotebookLM notebooks as knowledge
mcp__gemini-web-mcp__gems(action="update", gem_id="abc", name="New Name",
    notebook_ids=["uuid1"])  # Update with notebook knowledge
mcp__gemini-web-mcp__gems(action="delete", gem_id="abc")
```

#### CLI Commands
```bash
gemcli gems list
gemcli gems create --name "Code Reviewer" --prompt "You are a senior code reviewer..."
gemcli gems create --name "Expert" --prompt "..." --notebook <uuid>  # With NotebookLM
gemcli gems create --name "Multi" --prompt "..." --notebook <id1> --notebook <id2>
gemcli gems delete <gem_id>
```

**NotebookLM Integration:** Use `list_notebooks` to find notebook IDs, then pass them via `notebook_ids` (MCP) or `--notebook` (CLI) when creating or updating gems. Notebooks are attached as knowledge sources the gem can reference. Up to 10 knowledge sources per gem (files + notebooks combined).

### 9. Profile Management

Profiles are separate Gemini accounts/sessions. Use them to work across
accounts, or to keep generating when one account's plan pool runs out.

```bash
gemcli profile list              # List all profiles (gemcli + NLM shared)
gemcli profile switch <name>     # Switch active profile
gemcli profile create <name>     # Create new empty profile
gemcli profile delete <name>     # Delete profile
gemcli profile sources           # Show profile sources
```

**Run any command against another profile** with the global `-p` / `--profile`
flag (place it before the subcommand):

```bash
gemcli -p work chat "hi"
gemcli -p work limits                  # Check that account's quota
gemcli -p work video "..." -o v.mp4
```

**Quota-flip workflow** — when a media tool is disabled or a generation fails
with a usage error, compare accounts and switch:

```bash
gemcli limits                 # account + per-feature usage for the active profile
gemcli -p <other> limits      # compare another profile
gemcli -p <other> video "Cinematic drone shot over a lake" -O landscape -o clip.mp4
gemcli profile switch <other> # make it the default for future commands
```

Every account has its own plan pool (size depends on the plan) and its
own per-feature usage percentages. A feature at 100% is disabled in the UI
until its window resets (`gemcli limits` shows the reset time). Different
accounts may also have different features enabled (e.g. one account's Videos
tool can be disabled while another's is available).

### 10. Persistent Chrome (for background processes)

Some features require Chrome for BotGuard token generation:
- **File uploads / attachments** — BotGuard required for chat with files
- **Image generation** (Nano Banana / Nano Banana Pro) — BotGuard + tool activation required
- **Video generation** (Gemini Omni) — BotGuard + tool activation required
- **Music generation** (Lyria 3.5) — always needs BotGuard, even on Flash model
- **Pro / Argon / non-low thinking** — need BotGuard for model switching
- **Task mode** (`--task`) — needs BotGuard; Chrome clicks the Chat/Task control

If running from a **background process** (macOS LaunchAgent, cron, systemd, SSH without display), Chrome cannot be launched on demand for Token Factory (Pro/Argon/thinking/Music/Video/Task). Start it once from an interactive terminal:

> **SSH note:** `gemcli login` itself works over SSH for refreshing an existing session (runs Chrome headlessly). For a brand-new login over SSH, use `gemcli login --manual` to paste cookies.

```bash
gemcli chrome start              # Start headless Chrome daemon (survives terminal close)
gemcli chrome start --visible    # Start with visible window (for debugging)
gemcli chrome start -p 9225      # Use specific CDP port
gemcli chrome stop               # Stop the daemon (waits for running jobs; --now doesn't)
gemcli chrome status             # Check health, port, auth cookie, and live SNlM0e
gemcli chrome install-agent      # Install macOS LaunchAgent (auto-start at login)
gemcli chrome uninstall-agent    # Remove the LaunchAgent
```

**How it works:** Token Factory automatically detects the running Chrome on ports 9222-9231. The daemon is used only for the profile it holds — `-p <other>` uses that profile's own Chrome — and a Chrome signed in to a different account is never used. Saved cookies are never injected into the daemon. No configuration needed — just start it and music/Pro features work from any context.

**Concurrency:** every process (CLI runs, MCP calls, keep-alive, login, `chrome stop`) takes a per-profile lock before driving that profile's Chrome, so parallel jobs queue instead of overwriting each other's prompt and token. The daemon restarts itself after 12h / 1.5 GB, but only while no job is using it. A daemon that starts slowly gets 30s (`GEMCLI_CHROME_START_TIMEOUT`).

**After reboot:** Either install the LaunchAgent (`gemcli chrome install-agent`) for automatic startup, or run `gemcli chrome start` again from an interactive terminal.

### Keeping sessions alive (multiple profiles, unattended use)

Google sessions stay alive while the browser that owns them keeps using them.
Profiles you don't use for a few days go stale. The keep-alive renews every
profile through **its own** Chrome (never a copy, never injecting cookies) and
saves the fresh cookies:

```bash
gemcli login --check --all             # Read-only health of every profile (exit 3 if any needs sign-in)
gemcli keepalive run                   # Renew every profile now (~10s per profile)
gemcli keepalive run --recover         # ...and try one-click "Continue as" re-sign-in if one expired
gemcli keepalive status                # Last result per profile + agent schedule
gemcli keepalive install-agent --every 4 --recover   # macOS LaunchAgent: run every 4h
gemcli keepalive uninstall-agent
```

`--recover` only clicks Google's account chooser for the matching account. If
Google asks for a password, passkey, or "verify it's you", the profile is
reported `DEAD` and a human must run `gemcli login --profile <name>`.
Each signed-in profile also gets a **token-capture probe** (sends nothing to
Gemini): a profile can be `alive` yet show `token capture failed`, which means
uploads, images, video, music and Pro will fail on it — use another profile and
run `gemcli -p <name> doctor --deep`. `keepalive run` exits 1 in that case;
`--no-probe` skips the probe.
**Agents: before a batch of media jobs, run `gemcli login --check --all` and
use a profile reported `alive`.** `stale` means only the saved cookie copy is
out of date — `gemcli keepalive run` fixes it without a sign-in.

### 11. Configuration

```bash
gemcli config show               # Show all settings
gemcli config get <key>          # Get specific value
gemcli config set <key> <value>  # Set a value
gemcli config set browser brave  # Browser by name...
gemcli config set browser "/Applications/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing"
                                 # ...or a path to a dedicated Chromium binary
```

Environment overrides: `GEMCLI_BROWSER` (name or path),
`GEMCLI_PROFILE_LOCK_TIMEOUT` (seconds a job waits for a busy profile, default
300), `GEMCLI_CHROME_START_TIMEOUT` (default 30), `GEMCLI_ATTACHMENT_CHECK=0`,
`GEMCLI_CHROME_IDLE_TIMEOUT` (default 120).

### 12. MCP Setup

```bash
gemcli setup list                # Show configured clients
gemcli setup add cursor          # Add to Cursor
gemcli setup add claude-desktop  # Add to Claude Desktop
gemcli setup add claude-code     # Add to Claude Code
gemcli setup add gemini-cli      # Add to Gemini CLI
gemcli setup remove <tool>       # Remove from tool
```

### 13. Skill Management

```bash
gemcli skill list                # Show installation status
gemcli skill install claude-code # Install for Claude Code
gemcli skill install cursor      # Install for Cursor
gemcli skill update              # Update all outdated skills
gemcli skill show                # Display skill content
```

### 14. Hack Claude (Launch Claude Code via Gemini)

Launch Claude Code connected to a local Anthropic-compatible API server backed by Gemini.

```bash
gemcli hack claude                         # Launch with Gemini Flash (default)
gemcli hack claude --model gemini-pro      # Use Gemini Pro
gemcli hack claude -p "fix this bug"       # Pass args through to Claude Code
```

**How it works:** Starts a local FastAPI server on a free port that implements the Anthropic Messages API, sets `ANTHROPIC_BASE_URL` to point to it, and launches `claude`. When Claude Code exits, the server is automatically shut down.

**Requirements:** Claude Code must be installed (`npm install -g @anthropic-ai/claude-code`).

### 15. Diagnostics

```bash
gemcli doctor                    # Check installation and SAVED auth/config
gemcli doctor --verbose          # Detailed diagnostics
gemcli -p <profile> doctor --deep  # Prove the live path: BotGuard token capture + tiny upload
```

Plain `doctor` passing does not mean uploads or media work — only `--deep`
tests that (it sends nothing to Gemini chat and exits 1 on failure).

### 16. Usage Limits

```bash
gemcli limits                    # Show per-feature usage quotas and remaining count
gemcli -p <profile> limits       # Check a different account's limits
```

The output starts with the **account and profile** the numbers are for, then
grouped usage rows. Verified against `https://gemini.google.com/usage` (2026):

- Most features **share one plan pool** and report the same account-wide
  percentage — that is the shared row (it matches the "Current usage" figure on
  the web page). The pool size depends on the account's plan (e.g. 2,400 or 48,384 credits); each row's reset time is what Google reports in `Resets In` (it differs by feature and account — don't assume a fixed window).
- **Video (Gemini Omni)** and **Deep Think** report their own percentages and
  run ahead of the account-wide figure (advanced features consume more).
- When a feature hits 100% (0 credits left), its tool is disabled in the UI
  until the window resets. **Switch profiles to keep working** (see
  [Profile Management](#9-profile-management)).

Requires Chrome for browser cookie authentication (Token Factory). The live
web view is at `https://gemini.google.com/usage`.

#### MCP Tool
```python
mcp__gemini-web-mcp__limits()    # Returns JSON with per-feature limit data
```

**IMPORTANT**: Call `limits` before attempting video, music, or image generation to verify quota is available. This avoids wasting time on operations that will be rejected. If the tool is disabled (usage exhausted), run `gemcli limits`, then retry with another profile via `-p <profile>`.

## Model Selection Guide

| Model | CLI Flag | Notes |
|-------|----------|-------|
| Gemini 3.8 Flash (default) | `-m gemini-3.8-flash` | Fast model. `gemini-3.7-flash` is the same hash |
| Gemini 3.8 Flash High | `-m gemini-3.8-flash --thinking-level high` | Old Extended thinking toggle. Requires Chrome |
| Gemini 3.8 Flash Medium | `-m gemini-3.8-flash --thinking-level medium` | Balanced thinking. Requires Chrome |
| Gemini 3.1 Pro | `-m gemini-3.1-pro` | Requires Chrome |
| Gemini 4 Argon | `-m gemini-4-argon` | Complex tasks. Requires Chrome |
| Task | `gemcli chat --task "prompt"` | Agent mode on the Chat/Task control. Requires Chrome |

**Token Factory**: Pro, Argon, Task, and non-low thinking levels require a BotGuard token generated by Chrome.

## Error Recovery

| Error | Cause | Solution |
|-------|-------|----------|
| AuthError / expired cookies (exit code 3) | Session timeout (or, before 0.8.3, parallel jobs colliding) | Follow **Failure Triage** above: `gemcli login --check --all` first, then another profile; `gemcli login` only in an interactive session |
| ProfileBusy ("is busy with another request") | Profile's Chrome busy past the wait | Retry, `-p <other>`, or raise `GEMCLI_PROFILE_LOCK_TIMEOUT` |
| AttachmentNotRead ("did not read the attachment") | Gemini could not open the file | Retry once, `doctor --deep`, another profile; never use that reply |
| UsageLimitExceeded (1037) | Too many requests | Wait, then retry |
| ModelInvalid (1050/1052) | Bad model name | Check model names above |
| TemporarilyBlocked (1060) | IP rate limited | Wait or use VPN |
| TokenFactoryError | Token capture failed | `gemcli -p <profile> doctor --deep`, then `gemcli chrome status`; restart the daemon with `gemcli chrome stop && gemcli chrome start` (waits for running jobs). Background processes: `gemcli chrome install-agent` |
| MusicGenerationError | Music generation failed | Check prompt, retry; content policy may reject some prompts |
| Chrome doesn't launch / "did not answer within 30s" | Busy machine or profile locked by another Chrome | Retry; `GEMCLI_CHROME_START_TIMEOUT=60`; close the Chrome named in the message |
| WebSocket 500 / stale target | Chrome was restarted | Retry — Token Factory reconnects automatically |

## Advanced Reference

For detailed information, see:
- **[references/IMAGE_PROMPTING_GUIDE.md](references/IMAGE_PROMPTING_GUIDE.md)**: Complete Nano Banana image prompting guide with templates, art styles, quality modifiers, and recipes
- **[references/command_reference.md](references/command_reference.md)**: Complete command signatures
- **[references/troubleshooting.md](references/troubleshooting.md)**: Detailed error handling
- **[references/workflows.md](references/workflows.md)**: End-to-end task sequences
