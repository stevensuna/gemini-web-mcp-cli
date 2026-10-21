# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

MCP server and CLI for the Gemini web interface (gemini.google.com). Clean-room
rebuild using protocol knowledge from gemini-webapi as reference. No code copied.

## Official Release Process

Operator instruction (2026-10-08): fixes destined for installation or distribution must complete the official release cycle. Never install a changed source tree under the previous version and present it as a released fix.

1. Bump `pyproject.toml`, `src/gemini_web_mcp_cli/__init__.py`, `uv.lock`, `desktop-extension/manifest.json`, and the bundled `data/SKILL.md` version together. Date the changelog entry and include the code and bundled skill changes.
2. Run the full lint and test suite, build the wheel and source archive, and build/inspect the MCPB extension. Check version consistency and bundled skill content.
3. Commit and push the release changes, then push the matching `vX.Y.Z` tag. `.github/workflows/release.yml` is the official publication path: Python 3.11/3.12/3.13 checks, package build, trusted PyPI publication, GitHub release, and MCPB asset upload.
4. Wait for every workflow job to succeed. Verify the version and artifacts on PyPI and GitHub. Do not report a release complete merely because the tag was pushed.
5. Install the exact published PyPI version on the intended machine, update its relevant skill from that package, and verify the installed version and fixed behavior. A source-checkout installation does not replace publication.

## Development Commands

Source installations below are for local development. Distribution to the intended machine follows the official release process above.

```bash
# Setup
uv venv && source .venv/bin/activate
uv pip install -e ".[all]"

# Run all tests (600+ tests)
pytest tests/ -v

# Run a single test file
pytest tests/test_parser.py -v

# Run a single test
pytest tests/test_parser.py::TestParseFrames::test_single_frame -v

# Lint
ruff check src/ tests/

# Lint with auto-fix
ruff check --fix src/ tests/

# Reinstall after code changes (ALWAYS clean cache first)
uv cache clean && uv pip install -e ".[all]"

# If installed as a tool, reinstall with:
uv cache clean && uv tool install --force .
```

**Ruff config:** line-length=100, target py311, selects E/F/I/W rules.
**Pytest config:** asyncio_mode="auto" (no need for @pytest.mark.asyncio).

## Architecture

```
src/gemini_web_mcp_cli/
  core/               # Transport, auth, parsing (shared foundation)
    constants.py      # Model hashes, RPC IDs, magic numbers (single source of truth)
    music_presets.py  # 16 Lyria music style definitions
  services/           # Business logic (single source of truth)
  api/                # Anthropic-compatible API server (for hack claude)
  cli.py              # CLI (Click) — thin wrapper over services
  mcp.py              # MCP server (FastMCP) — thin wrapper over services
  hack.py             # Launch AI tools connected to Gemini (hack claude)
  setup.py            # MCP client configuration helper
  skill.py            # Skill installer for AI tools (Claude Code, Cursor, Codex, etc.)
  data/               # Skill documentation (SKILL.md, AGENTS_SECTION.md, references/)
```

All interfaces (CLI, MCP, future API) consume the same service layer. When
Gemini changes an RPC, update one service file and everything works.

### Composition Flow

```
GeminiClient (core/client.py)
  ├── ProfileManager (core/profiles.py)   — multi-profile + NLM cross-product
  ├── AuthManager (core/auth.py)          — CDP login, cookies, 3-layer token refresh
  ├── RPCTransport (core/rpc.py)          — batchexecute + StreamGenerate (Flash)
  ├── TokenFactory (core/token_factory.py) — BotGuard token capture (Pro/Thinking/Music)
  ├── ChromeManager (core/chrome_manager.py) — persistent Chrome daemon lifecycle
  ├── Keepalive (core/keepalive.py)       — per-profile session renewal + health checks
  └── Parser (core/parser.py)             — UTF-16 frame decoder, JSONP stripping

Services (services/*.py)
  ├── ChatService     — wraps client.send(), tracks ConversationMetadata, file uploads
  ├── FileService     — 2-step resumable upload to push.clients6.google.com
  ├── ImageService    — image generation + download
  ├── VideoService    — Veo 3.1 video generation + polling
  ├── MusicService    — Lyria 3 music generation + download + 16 style presets
  ├── ResearchService — Deep Research + polling
  ├── GemsService     — CRUD for custom system prompts + NotebookLM notebook attachment
  └── LimitsService   — per-feature usage quotas via qpEbW RPC

CLI/MCP → Service → GeminiClient → RPCTransport → Gemini API
                                  → TokenFactory (if BotGuard needed)
                                  → ChromeManager (persistent Chrome daemon)

API Server (api/server.py) — Anthropic Messages API → GeminiClient
  └── hack.py launches server + Claude Code with ANTHROPIC_BASE_URL
```

### Model Switching via Token Factory

Model switching requires BotGuard tokens that only a real browser can generate.
The **Token Factory** approach solves this: Chrome generates BotGuard tokens,
Python sends the actual HTTP request with the token + ALL browser cookies + a
fresh `at=` access token.

**Proven working (Feb 2026):** Python HTTP replay with stolen BotGuard token
returns Pro (`e6fa609c3fa255c0`) when ALL 28 browser cookies are included.
Even Python-native TLS (httpx) works — TLS fingerprinting is NOT an issue.

```
Flash (default):  Direct HTTP via RPCTransport  (no browser needed)
Pro / Thinking:   Token Factory — Chrome generates BotGuard token,
                  Python sends HTTP with token + ALL cookies + at=
Image (NB2):      Token Factory — BotGuard + tool_id=14 (Flash=Nano Banana 2, Pro=NB Pro)
Music (Lyria 3):  Token Factory — BotGuard + tool_id=21 required
Video (Veo 3.1):  Token Factory — BotGuard + tool_id=11 + at= required for Veo routing
```

- **RPCTransport** (`core/rpc.py`): Direct HTTP to StreamGenerate. Fast, lightweight.
  Server ignores model header without BotGuard — always returns Flash.
- **Token Factory** (`core/token_factory.py`): Production. Captures BotGuard tokens.
  1. Chrome sits on gemini.google.com (background, headless)
  2. A short dummy string `[BotGuard Capture]` is typed to trigger XHR capture
     without the browser lagging or truncating long prompts
  3. XHR interceptor captures BotGuard token + headers before request is sent
  4. Chrome's live `SNlM0e` token extracted from `window.WIZ_global_data`
     and stored as `captured.access_token` (critical: mismatching Python's cached
     token with Chrome's cookies causes HTTP 400)
  5. ALL cookies grabbed via CDP `Network.getAllCookies`
  6. Python rebuilds the full request body with the real prompt + BotGuard token
     + Chrome's live `at=` SNlM0e token
  7. BotGuard token at `inner[3]`, challenge hash at `inner[4]`
  8. `at=` MUST always be included — omitting it causes Gemini to skip Veo/Lyria
     routing and fall back to chat/image mode
- **ChromeManager** (`core/chrome_manager.py`): Persistent Chrome daemon lifecycle.
  For background processes (LaunchAgent, cron) that can't launch Chrome on demand.
  `gemcli chrome start` launches Chrome once, Token Factory finds it via port scan.
  PID/port stored at `~/.gemini-web-mcp-cli/chrome-daemon.json`.
- **BrowserTransport** (`core/cdp.py`): Legacy approach. Controls headless Chrome
  via CDP to click UI elements. Works but heavy. Being replaced by Token Factory.

### Response Parsing (Non-Trivial)

Google uses UTF-16 length-prefixed frames. `parser.py` handles:
- JSONP prefix stripping (`)]}'` → `""`)
- UTF-16 code unit counting (BMP = 1 unit, supplementary = 2 via surrogates)
- Nested JSON extraction via safe path navigation

### Request Payload

StreamGenerate uses a 70-element `inner_req_list` array. Field purposes are
documented inline in `rpc.py::build_streamgenerate_body()`. Many fields are
reverse-engineered from the live Gemini UI.

## Model Hashes (confirmed from live UI, Oct 13, 2026)

The model is selected by the full `x-goog-ext-525001261-jspb` header, not the hash
alone. The tail is `<category>,<thinking level>`. Thinking level is Low=1,
Medium=4, High=2. High is the old Extended thinking toggle. The same level
applies to whichever model is selected. The Chat/Task control under the prompt
is separate from the model picker.

| UI Label       | Hash              | Header tail | Notes                |
|----------------|-------------------|-------------|----------------------|
| 3.5 Flash-Lite | 8c46e95b1a07cecc  | 6,1         | Fastest answers      |
| 3.8 Flash      | 56fdd199312815e2  | 1,1         | All-around help. Same hash as the old 3.7/3.6 label |
| 3.1 Pro        | e6fa609c3fa255c0  | 3,1         | Advanced reasoning   |
| 4 Argon        | 95a4c0abcba24364  | 8,1         | Complex tasks        |

Direct HTTP without BotGuard token gets Flash (`56fdd199312815e2`).
With stolen BotGuard token + ALL browser cookies, model header is respected.

## Data Models (core/models.py)

- `RPCPayload` — RPC call: rpc_id, payload JSON, identifier
- `ConversationMetadata` — Multi-turn: cid (conversation), rid (response), rcid (candidate)
- `StreamResponse` — Parsed response: metadata, candidates, model hash
- `BatchResult` — Single batchexecute result
- `AuthTokens` — snlm0e, cfb2h, fdrfje
- `AuthState` — Full auth: cookies, tokens, chrome_profile_path, last_refreshed

## Error Hierarchy (core/exceptions.py)

`GeminiError` base, with: `AuthError`, `APIError`, `UsageLimitExceeded` (1037),
`ModelInvalid` (1050/1052), `TemporarilyBlocked` (1060), `TimeoutError`,
`ImageGenerationError`, `VideoGenerationError`, `MusicGenerationError`,
`ResearchError`, `ProfileError`.

## Config Paths

- `~/.gemini-web-mcp-cli/config.json` — Active profile, default model
- `~/.gemini-web-mcp-cli/profiles/<name>/auth.json` — Per-profile auth
- Cross-product: reads `~/.notebooklm-mcp-cli/profiles/` (live, never copied)
- NLM Chrome profiles: `~/.notebooklm-mcp-cli/chrome-profiles/<name>/`

## Entry Points (pyproject.toml)

- `gemcli` → `gemini_web_mcp_cli.cli:main`
- `gemini-web-mcp` → `gemini_web_mcp_cli.mcp:main`

## Testing Patterns

- Unit tests only (no integration/live API tests)
- Tests cover core layer: auth, constants, parser, profiles, rpc
- Skill system tests: install/uninstall, version injection, CLI commands (40 tests)
- Parser tests use real captured Gemini response data

### Session Lifecycle: Critical Notes (issue #3, Sep 2026)

Full findings: `docs/research/auth/session-lifecycle.md`.

- **One Chrome owns each session.** Using one session from several clients
  (login profile + a `_tf` copy + Python, each rotating cookies) got sessions
  revoked within minutes (RotateCookies → 401). Never copy a profile dir or
  inject saved cookies into a Chrome that owns a session.
- **`auth.json` is a mirror.** Chrome renews short-lived cookies, so a saved
  copy can be rejected while Chrome is still signed in. Read live cookies from
  the running Chrome when possible.
- **Signed in = account email.** The signed-out Gemini page also has an
  `SNlM0e`; check `WIZ_global_data.oPEP7c` (or `"oPEP7c"` in the HTML).
- **Deleting Google cookies signs Chrome itself out** (and `login --force` does
  exactly that), losing the one-click "Continue as" sign-in.
- **Profile names:** never fall back to a literal `"default"` profile — use
  `AuthManager.resolved_profile_name` (explicit profile or the active one).
- **`pgrep -f` matches substrings:** match `--user-data-dir` exactly
  (`_user_data_dir_pgrep_pattern`), or `mail4jbd` also matches `mail4jbd2`.
- **Exit codes:** CLI errors go through `_fail()` — `3` for `AuthError`
  (`EXIT_AUTH_REQUIRED`), `1` otherwise.
- **No cookie injection, no profile copies.** Token Factory launches on the
  profile's own user-data-dir; `browser_auth` is read-only; the daemon is used
  only for the profile it holds, and a Chrome signed in to another account is
  refused (`_ensure_browser_cookies` compares `oPEP7c` with the profile email).
- **Keep-alive** (`gemcli keepalive run`): loads Gemini in each profile's own
  Chrome, closes it with `Browser.close` so renewed cookies are flushed, and
  mirrors cookies to `auth.json`. `--recover` only clicks, never types.

### Concurrency: one driver per profile (Sep 2026)

- Token Factory drives one shared Gemini tab, so every step that drives,
  launches, restarts or closes a profile's Chrome holds `core/locks.py`'s
  `profile_lock(profile)` (flock, cross-process, reentrant per thread).
  Parallel callers queue (`GEMCLI_PROFILE_LOCK_TIMEOUT`, default 300s), then
  get `ProfileBusy` — deliberately not a `TokenFactoryError`, so it never
  triggers the plain-HTTP fallback.
- Without the lock, parallel captures overwrite each other and surface as a
  false "Session expired — auto sign-in failed" (reproduced on v0.8.2).
- Daemon age/RSS restarts only happen when the lock is free; a slow CDP
  response is skipped, never treated as a zombie and killed.
- Never launch Chrome with `stdout/stderr=PIPE` unless you read them: a
  long-lived Chrome blocks once the pipe buffer fills.
- Attachments and tools never fall back to plain HTTP (issue #6).
- Health checks must test the real path: `core/probe.py` captures a token
  (the XHR interceptor aborts in Chrome, so nothing is sent) and uploads a
  tiny file; used by `doctor --deep` and keep-alive (`capture` field).
- Never run `gemcli login` from background jobs; it stops the daemon.

### Chat transports: StreamGenerate and processSession (Sep 2026)

Full findings + redacted captures: `docs/research/transport/processSession.md`.

- Google picks the chat transport **per account**; the page decides on Send.
  Some accounts use a WebChannel session at
  `geminiweb-pa.clients6.google.com/v1/processSession` instead of StreamGenerate.
  Both go through `XMLHttpRequest`, so one hook (`XHR_INTERCEPTOR_JS`) captures
  either; `CapturedRequest.transport` says which. Nothing is cached per profile.
- processSession: the channel-open POST (URL has `X-HTTP-Session-Id` and
  `$httpHeaders` = SAPISIDHASH auth, `X-Server-Token`, protobuf model header
  `x-goog-ext-525001261-bin`) is let through and recorded; the data POST (setup
  message) is aborted. `core/webchannel.py::replay()` opens a fresh channel
  from Python with Chrome's cookies.
- The setup message wraps the StreamGenerate `inner` array at
  `setup[0][7][4][0]` (BotGuard `inner[3]`, hash `inner[4]`, files `inner[0][3]`,
  conversation `inner[71] = ["c_<cid>", null x6, ""]`, NOT `inner[2]`). The
  prompt goes in a separate message. The channel parses strict JSON-protobuf:
  a list in a scalar field fails with `__sm__` status 3.
- Response bodies are StreamGenerate-shaped (`parse_stream_body`). Final
  candidate has flag 1; after the completion token (`body[25]`) the client
  half-closes (`[null,null,null,[1]]`) and the server ends the stream.
- Conversation URLs are `/app/<hex>` without the `c_` prefix.
- The page may encode the channel as **binary protobuf** (`X-WebChannel-Content-Type:
  application/x-protobuf`, switched per account). The server still accepts JSON,
  so the replay forces JSON (`use_json_encoding`) and converts Chrome's binary
  setup with `core/protojspb.py`, typed by `core/setup_shape.py` (generated from
  JSON captures). An unknown field guessed wrong fails loudly with its name.
- If Chrome sends a prompt the hook missed (tab moves to `/app/<cid>`), raise
  `PromptEscaped` — never retry or fall back (duplicate prompts).

### File Upload Protocol (discovered via Chrome DevTools MCP, Feb 2026)

Upload uses a 2-step resumable protocol to `push.clients6.google.com`:
1. `POST /upload/` with `x-goog-upload-command: start`, body `File name: <name>`
   → Response header `x-goog-upload-url` contains the upload URL
2. `POST <upload_url>` with `x-goog-upload-command: upload, finalize`, body = file bytes
   → Response body = `/contrib_service/ttl_1d/...` identifier

File data in StreamGenerate: `inner[0][3] = [[[file_id, 16, null, mime_type], filename, null*6, [0]]]`
BotGuard token is required when files are attached.

### NotebookLM Notebook Attachment for Gems (discovered Feb 2026)

Notebooks can be attached as knowledge sources to gems. Unlike Drive/uploaded files,
notebook tokens are generated **client-side** (no server round-trip).

- **RPC `NXpLKc`** lists notebooks: payload `[]`, response `[[[path, title, [ts, ns], count], ...]]`
- **Notebook path format**: `"notebooks/{uuid}"` (e.g., `"notebooks/32c3a781-0cc5-4b69-..."`)
- **Token**: base64-encoded protobuf placed at `knowledge[i][5]`, same position as `$Aed` tokens
- **Protobuf fields**: field1.15.1=path, field2=20 (type code), field3=title, field9=14 (source), field12=""
- **List response**: `entry[0][14]=["notebooks/{uuid}"]`, `entry[1]=20`, `entry[8]=14`
- **Knowledge array format**: ALL entries (files + notebooks) in single inner array: `[[entry1, entry2, ...]]`

### Token Factory: Critical Notes

- **`at=` must always be sent in the body** — omitting it falls back to chat mode
  (no Veo, no Lyria). Chrome's live `SNlM0e` from `window.WIZ_global_data` is used.
- **Typed prompt is only a trigger** — Token Factory types a newline-free copy
  of the prompt to trigger the XHR intercept (a typed newline cut the capture
  off at that line, issue #2). Python always writes the real prompt into the
  request (StreamGenerate `inner[0][0]`; processSession prompt message).
- **Token reuse for polling** — `_browser_access_token` is stored after the initial
  capture and reused in `execute_rpc_with_browser_cookies()` for polling calls
  (`hNvQHb`). Using Python's cached `transport.access_token` instead causes HTTP 400.
