# Gemini Web MCP CLI - Workflows

End-to-end task sequences for common operations.

---

## AI Behavior Rules

**CRITICAL: Always follow these rules when using gemcli on behalf of a user:**

1. **Confirm before destructive operations**: Before deleting gems or profiles, show what will be deleted and ask for explicit user confirmation
2. **Check auth first**: Run `gemcli login --check` before starting a workflow to avoid mid-workflow auth failures
3. **Capture IDs from output**: Create commands return IDs needed for subsequent operations
4. **Report errors clearly**: If a command fails, show the error and suggest next steps

**Commands requiring user confirmation before execution:**
- `gemcli gems delete <id>`
- `gemcli profile delete <name>`

---

## Workflow 1: First-Time Setup

Goal: Get gemcli installed, authenticated, and verified.

```bash
# Step 1: Authenticate
gemcli login

# Step 2: Verify everything works
gemcli doctor

# Step 3: Test with a quick chat
gemcli chat "Hello, what can you do?"

# Step 4: (Optional) Set up AI tool integration
gemcli setup add claude-code
gemcli skill install claude-code
```

---

## Workflow 2: Chat with Model Selection

Goal: Chat using different models for different tasks.

```bash
# Quick answer with Flash (default, fastest)
gemcli chat "What is the capital of France?"

# Detailed analysis with Pro
gemcli chat "Analyze the pros and cons of microservices architecture" -m gemini-3.1-pro

# Reasoning-heavy task with high thinking on Flash
gemcli chat "Solve this logic puzzle: ..." -m gemini-3.8-flash --thinking-level high

# Complex multi-step work with Gemini 4 Argon
gemcli chat "Draft a migration plan for …" -m gemini-4-argon

# Agent / Task mode (formerly Spark)
gemcli chat --task "Collect recipes from my inbox"

# Save response to file
gemcli chat "Write a summary of quantum computing" -o quantum_summary.md
```

**Interactive session with model switching:**
```bash
gemcli chat
# In REPL:
# /model gemini-3.1-pro     (switch to Pro)
# What are the latest trends in AI?
# /model gemini-4-argon     (switch to Argon)
# /model gemini-3.8-flash   (switch back to Flash)
# /thinking medium          (balanced thinking level)
# /task on                  (next prompts go through Task)
# Summarize that in one sentence
# /save conversation.md     (save the conversation)
# /quit
```

---

## Workflow 3: Image Generation Pipeline

Goal: Generate and save images.

```bash
# Generate with auto-save
gemcli image "A serene mountain landscape at sunset, photorealistic" -o landscape.png

# Generate without saving (displays URL)
gemcli image "An abstract painting of creativity"
# Then download specific image:
# Copy the image URL from the output and use the MCP download action
```

**Via MCP tools:**
```python
# Generate
result = mcp__gemini-web-mcp__image(
    action="generate",
    prompt="A futuristic cityscape at night",
    output_path="city.png"
)

# Download a specific URL later
mcp__gemini-web-mcp__image(
    action="download",
    image_url="https://...",
    output_path="city_v2.png"
)
```

---

## Workflow 4: Video Generation & Iterative Editing Pipeline

Goal: Generate a high-fidelity video with Gemini Omni (Veo 3.1) and refine it iteratively using conversational updates. Requires Chrome background running for BotGuard challenges.

### Option A: Conversational Editing via CLI Chat REPL
This is the most powerful workflow for fine-tuning video clips. You enter the chat REPL, generate a base video, and then iteratively issue edit prompts to adjust camera angles, subjects, or actions without starting from scratch.

```bash
# Prerequisite: ensure Chrome daemon is active
gemcli chrome start

# Enter the Gemini CLI Chat REPL in Pro mode (needed for video)
gemcli chat -m pro

# Turn 1: Generate the base video
> Generate a cinematic video of a gorgeous garden with a glowing golden butterfly landing on a flower.

# Turn 2: Swapping subjects (keep everything else identical)
> Change the butterfly to a bee. Keep the exact background, lighting, and camera angle the same.

# Turn 3: Swapping action / camera movement
> Change the camera angle to be a close-up tracking shot. Change the bee to a small swarm of fireflies.
```

### Option B: Direct CLI Commands
Use for single-shot generations where iterative edits are not needed.

```bash
# Start generation and save output (polls for 1-2 minutes)
gemcli video "A drone shot flying over a tropical beach at golden hour" -o beach.mp4

# Check active quota limits
gemcli limits
```

### Option C: Multi-Turn Video Editing via MCP
For AI agents executing within an application, utilize the `chat` tool's multi-turn conversational capabilities to create and edit videos while maintaining history:

```python
# Turn 1: Generate initial base clip
r1 = mcp__gemini-web-mcp__chat(
    action="send",
    prompt="Generate a cinematic video of a spaceship cruising through a deep violet planetary nebula."
)

# Turn 2: Apply a style transformation while preserving base layout & motion
r2 = mcp__gemini-web-mcp__chat(
    action="send",
    prompt="Create a tactile risograph style transformation of the spacecraft. Keep the spaceship's motion, camera tracking, and planetary nebula composition completely identical. Apply neon pink and deep navy stipple shading.",
    conversation_id=r1["conversation_id"]
)
```

For raw single-shot generation without conversation context:
```python
# Start generation
mcp__gemini-web-mcp__video(action="generate", prompt="Ocean waves crashing")

# Check status
mcp__gemini-web-mcp__video(action="status")

# Download when complete
mcp__gemini-web-mcp__video(action="download", output_path="ocean.mp4")
```

---

## Workflow 5: Music Generation Pipeline

Goal: Generate music tracks with Lyria 3, with optional style presets.

```bash
# Generate a track (waits for completion, displays metadata + download URLs)
gemcli music "A comical R&B slow jam about a sock"

# Generate with a style preset
gemcli music "Cats playing video games" -s 8-bit

# Save as audio (MP3)
gemcli music "Epic orchestral battle theme" -s cinematic -o battle.mp3

# Save as video (MP4 with cover art)
gemcli music "Summer vibes" -s k-pop -o summer.mp4 -f video

# List all 16 style presets
gemcli music --list-styles
```

**Via MCP tools:**
```python
# Generate a track
mcp__gemini-web-mcp__music(action="generate", prompt="A jazz ballad about rain")

# Generate with a style preset
mcp__gemini-web-mcp__music(action="generate", prompt="Cats in space", style="8-bit")

# Generate and auto-download
mcp__gemini-web-mcp__music(
    action="generate",
    prompt="Birthday song for Alex",
    style="birthday-roast",
    output_path="birthday.mp3"
)

# List available style presets
mcp__gemini-web-mcp__music(action="list_styles")

# Download from a previous generation
mcp__gemini-web-mcp__music(
    action="download",
    download_url="https://...",
    output_path="track.mp3"
)
```

**Available Style Presets:** 90s-rap, latin-pop, folk-ballad, 8-bit, workout, reggaeton, rnb-romance, kawaii-metal, cinematic, emo, afropop, forest-bath, k-pop, birthday-roast, folk-a-cappella, bad-music.

**Aliases:** rap, latin, folk, chiptune, edm, rnb, r&b, kawaii, metal, orchestral, ambient, kpop, birthday, roast, country, acappella, bad.

---

## Workflow 6: Deep Research Pipeline

Goal: Run comprehensive research on a topic.

```bash
# Start research (creates plan, then executes)
gemcli research "What are the latest breakthroughs in quantum computing in 2026?"

# Save to file
gemcli research "Compare React, Vue, and Svelte for enterprise apps" -o framework_report.md
```

**Via MCP tools:**
```python
# Start research
mcp__gemini-web-mcp__research(action="start", query="AI agents architecture patterns")

# Check progress
mcp__gemini-web-mcp__research(action="status")
```

---

## Workflow 7: Gems Management

Goal: Create and use custom AI personas.

```bash
# List existing gems
gemcli gems list

# Create a code reviewer gem
gemcli gems create \
    --name "Senior Code Reviewer" \
    --description "Reviews code for quality, security, and performance" \
    --prompt "You are a senior software engineer conducting code reviews. Focus on:
1. Security vulnerabilities
2. Performance implications
3. Code readability and maintainability
4. Best practices and design patterns
Always provide specific, actionable feedback with code examples."

# Use the gem in chat (copy gem_id from create output)
gemcli chat "Review this Python function: def add(a,b): return a+b" --gem <gem_id>

# Delete a gem (always confirm with user first!)
gemcli gems delete <gem_id>
```

**Via MCP tools:**
```python
# List
mcp__gemini-web-mcp__gems(action="list")

# Create
mcp__gemini-web-mcp__gems(
    action="create",
    name="Writing Coach",
    system_prompt="You help improve writing clarity and style."
)

# Delete (always get user confirmation first!)
mcp__gemini-web-mcp__gems(action="delete", gem_id="abc123")
```

---

## Workflow 8: Multi-Profile Setup

Goal: Manage multiple Google accounts.

```bash
# Create profiles for different accounts
gemcli profile create personal
gemcli profile create work

# Authenticate each profile
gemcli login --profile personal
gemcli login --profile work

# Check all profiles
gemcli profile list

# Switch default profile
gemcli profile switch work

# Use specific profile for one-off command
gemcli chat "Hello" --profile personal

# If NotebookLM MCP is installed, shared profiles appear automatically
gemcli profile sources   # Shows which profiles come from NLM
```

---

## Workflow 9: MCP Setup for AI Tools

Goal: Configure gemini-web-mcp in your AI development tools.

```bash
# Check current status
gemcli setup list

# Add to specific tools
gemcli setup add claude-code        # Claude Code CLI
gemcli setup add claude-desktop     # Claude Desktop app
gemcli setup add cursor             # Cursor editor
gemcli setup add gemini-cli         # Google Gemini CLI
gemcli setup add windsurf           # Windsurf editor
gemcli setup add cline              # Cline agent
gemcli setup add antigravity        # Antigravity IDE

# Install skill documentation (teaches AI tools how to use gemcli)
gemcli skill install claude-code
gemcli skill install cursor

# Verify everything
gemcli doctor

# Remove from a tool if needed
gemcli setup remove cursor
gemcli skill uninstall cursor
```

**After setup:**
1. Restart the AI tool
2. The MCP server will be available as `gemini-web-mcp`
3. The skill teaches the AI tool about available commands and best practices

---

## Workflow 10: Diagnostic and Recovery

Goal: Troubleshoot and fix common issues.

```bash
# Full diagnostic (saved state)
gemcli doctor --verbose

# Does the live path work? (token capture + tiny upload; sends nothing)
gemcli -p work doctor --deep

# Which profiles are signed in, and does token capture work on each?
gemcli login --check --all
gemcli keepalive status

# If auth is broken (interactive session only — never from a script/cron):
gemcli login --profile work

# If Chrome login fails:
gemcli login --manual

# Verify MCP clients:
gemcli setup list

# Verify skill installations:
gemcli skill list
```

---

## Workflow 10b: Batch / Pipeline Jobs

Goal: run many generations unattended without tripping over each other.

```bash
# Before the batch: pick healthy profiles
gemcli login --check --all            # alive / stale / DEAD
gemcli keepalive status               # token capture ok / failed per profile

# Run jobs in parallel; jobs on one profile queue automatically.
# Spread across profiles for throughput:
gemcli -p work  image "..." -o a.png &
gemcli -p gns   image "..." -o b.png &
gemcli -p work  chat "Describe this" -f clip.mp4 &
wait

# Long queues on one profile: let jobs wait longer instead of failing "busy"
export GEMCLI_PROFILE_LOCK_TIMEOUT=900
```

Rules for unattended runs:
- Branch on exit codes: `3` → `gemcli login --check --all` and switch profile;
  `1` → read the message (see troubleshooting.md). One retry per step.
- Never run `gemcli login`, `gemcli chrome stop --now`, or kill Chrome from
  the pipeline. `gemcli keepalive install-agent` keeps sessions alive, and the
  daemon restarts itself when idle.
- Treat "Gemini did not read the attachment" as a failed job, not an answer.

---

## Workflow 11: Batch Operations with Extensions

Goal: Use Gemini's extensions (YouTube, Maps, etc.) in chat.

```bash
# Chat with YouTube extension
gemcli chat "@youtube Summarize this video: https://youtube.com/watch?v=..."

# Chat with Maps extension
gemcli chat "@maps Find restaurants near Times Square, NYC"

# Multiple extensions
gemcli chat "@youtube @maps Find travel guides for Tokyo and show nearby attractions"
```

**Via MCP tools:**
```python
mcp__gemini-web-mcp__chat(
    action="send",
    prompt="Summarize this video",
    extensions=["youtube"]
)
```
