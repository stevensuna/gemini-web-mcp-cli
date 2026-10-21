# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [0.9.7] - 2026-10-13

### Added

- Gemini 4 Argon (`gemini-4-argon`, hash `95a4c0abcba24364`, header category 8) from the 2026-10-13 web picker.
- Thinking level `low`, `medium`, and `high` (`--thinking-level`, `/thinking`). Captured toggles are Low=1, Medium=4, High=2. High is the control previously labeled Extended thinking, so `--extended-thinking` still selects High.
- Chat/Task composer control (`gemcli chat --task`, `/task on`). Task is the agent mode previously called Spark. Chrome's signed request carries the mode.

### Changed

- The fast model label is Gemini 3.8 Flash. It keeps the hash previously shipped as 3.7 and 3.6 (`56fdd199312815e2`). `gemini-3.7-flash` remains an alias.
- Token Factory rewrites the hash, category, and thinking level inside Chrome's captured model header instead of replacing that header with the short template, and it selects the picker for chat as well as for image, video, and music. The live header continues past the thinking pair, and `inner[79]` / `inner[80]` mirror the picker.
- Bundled skill, AGENTS section, command reference, workflows, troubleshooting, README, CLAUDE.md, and AGENTS.md updated for the new web catalog and Chat/Task control.

## [0.9.6] - 2026-10-09

### Fixed

- Unknown model names now fail cleanly on every command that takes one —
  `research`, `image`, `video`, and `music` previously crashed with a raw
  traceback for IDs outside the Gemini Web catalog (e.g. `gemini-3.8-flash`,
  which exists on the Relay/Antigravity route but not here). All five
  model-taking commands (`chat` was fixed in 0.9.5) now reject the name with a
  one-line "Unknown model: … Available: …" error before authentication or
  uploads. The web catalog tops out at `gemini-3.7-flash`; no 3.8 alias is
  registered until the web UI exposes it. (Alef #261)
- `gemcli music --list-styles` once again lists the presets and exits when
  combined with an unknown `-m`; the listing short-circuits before model
  validation.

### Docs

- Bundled skill: the video-analysis recommendation names Gemini 3.7 Flash
  (the current web default) instead of 3.6, and the route-specific model note
  now covers every command that takes `--model`.

## [0.9.5] - 2026-10-08

### Fixed

- Reject unsupported chat model names with a clean CLI error before authentication, file uploads, or interactive startup. Model guidance distinguishes the Gemini Web catalog from Relay/Antigravity IDs (Alef #261).

## [0.9.4] - 2026-09-29

### Fixed
- **processSession accounts broke again when Gemini switched to binary
  messages** — about an hour after 0.9.0 shipped, Google switched eltanium's
  channel from JSON to binary protobuf (`X-WebChannel-Content-Type:
  application/x-protobuf`). Every request then crashed with a JSON decode
  traceback and no fallback. gemcli now converts Chrome's binary setup
  message to JSON (typed by a skeleton built from JSON captures) and keeps the
  replayed channel in JSON mode, which the server still accepts; both
  encodings are detected per request. Verified live on the binary-encoded
  account: chat, multi-line, Pro, Extended thinking, attachments, follow-ups
  with files, images, music, video and image-to-video.
- An unrecognised processSession request from Chrome raises a clear
  `APIError` instead of a traceback.

---

## [0.9.3] - 2026-09-29

### Fixed
- **Multi-line prompts were cut off at the first line (#2)** — on accounts using
  the StreamGenerate transport, Token Factory typed the prompt into Gemini's
  editor, and a newline cut the captured request off at that line. The model
  answered the first line only (e.g. an image prompt returned an unrelated
  picture) with exit 0. Python now always writes the full prompt into the
  request; Chrome types a single-line copy only to get the BotGuard token.
  Every StreamGenerate request is aborted inside Chrome, so none can be sent
  from there. processSession accounts were not affected.

---

## [0.9.2] - 2026-09-29

### Fixed
- **MCP server crashed on start (`gemini-web-mcp`)** — the dependency was
  `mcp[cli]>=1.0`, and mcp 2.0 (July 2026) renamed `FastMCP`, so every fresh
  install since then failed with `No module named 'mcp.server.fastmcp'`. The
  CLI was unaffected; tests passed because the lockfile pins mcp 1.x. Pinned to
  `mcp[cli]>=1.0,<2`.
- **Gemini's generic failure reply was returned as an answer** — "I seem to be
  encountering an error. Can I try something else for you?" came back with
  exit 0. Short replies that start with Gemini's failure text now raise
  `GeminiReplyError` (exit 1: "Gemini returned an error instead of an
  answer").

---

## [0.9.1] - 2026-09-29

### Fixed
- **`keepalive` JSON `capture` field changed in 0.9.0** — it became
  `"ok (processSession)"` instead of `"ok"`, which breaks scripts that check
  `capture == "ok"`. `capture` is `"ok"` again; the chat transport is a
  separate `transport` field (`streamgenerate` / `processSession`). The
  human-readable output still shows `token capture ok (processSession)`.
- **Images saved as JPEG with a `.png` name** — Gemini serves JPEG; `-o x.png`
  now writes a real PNG (also `.jpg`/`.jpeg`/`.webp`), keeping the original
  bytes if conversion fails.
- **Reply candidate id (`rcid`) was never set** in conversation metadata, so
  StreamGenerate follow-ups with attachments sent an empty one; it is now
  taken from the reply.
- **Server model label** — versioned labels such as "3.8 Flash" are
  recognised, so the confirmed model name is reported again.

### Docs
- Command reference: `doctor --deep` and keep-alive document the chat
  transport they report.

---

## [0.9.0] - 2026-09-29

Support for Gemini's new chat transport.

### Added
- **processSession transport** — Google is moving some accounts from
  `StreamGenerate` to a WebChannel session at
  `geminiweb-pa.clients6.google.com/v1/processSession`. On those accounts every
  Token Factory capture failed after ~45s, Chrome sent the prompt twice (junk
  conversations, wasted quota), and uploads, images, video, music and Pro
  failed. Token Factory now captures either transport: on processSession it
  records the channel-open URL, aborts the data POST in Chrome (nothing is
  sent), and Python opens its own channel with Chrome's cookies and sends the
  BotGuard-signed setup message plus the prompt. The model header (now
  protobuf) is rewritten to the requested model. Verified live: Flash, Pro,
  Extended thinking, attachments, images (Nano Banana 2 and Pro), music,
  video, image-to-video, follow-ups and parallel jobs. Research notes and redacted
  captures: `docs/research/transport/`.
- `doctor --deep` and `keepalive status` show each profile's chat transport
  (`token capture ok (processSession)`).

### Fixed
- **Follow-ups started a new conversation** — Token Factory opened
  `/app/c_<id>`, which Gemini treats as a blank chat; it now opens `/app/<id>`.
- **A prompt Chrome sent without capture was retried** — if the tab moves to a
  new conversation while no request was captured, gemcli now stops with
  `PromptEscaped` (exit 1) instead of retrying and falling back to HTTP, which
  sent the prompt two or three times.
- The Token Factory error help no longer suggests `pkill -f
  'remote-debugging-port'` (kills every Chrome automation on the machine) or
  claims the feature "requires the Pro model"; it points to
  `gemcli -p <profile> doctor --deep`.

---

## [0.8.3] - 2026-09-29

Stability under heavy / parallel use (#4, #5, #6, #7).

### Fixed
- **Parallel requests on one profile overwrote each other** — every request
  drives the profile's single Gemini tab in Chrome to get a BotGuard token,
  with no coordination between processes. Two jobs at once swapped prompts,
  tool state and tokens, and often failed with a false "Session expired —
  auto sign-in failed" (reproduced: 1 of 3 parallel chats on v0.8.2). Every
  step that drives, launches, restarts or closes a profile's Chrome now holds
  a per-profile lock (CLI, MCP, keep-alive, `login`, `chrome stop`), so jobs
  queue (3 of 3 succeed). A job waits up to `GEMCLI_PROFILE_LOCK_TIMEOUT`
  (300s), then fails with "Profile '…' is busy" (exit 1).
- **One process closed Chrome under another** — a process that launched
  Chrome closed it on exit or after 120s idle even while another process was
  mid-request; a Chrome slow to answer CDP (>2s) was treated as a zombie and
  killed. Shutdown now waits for the lock and otherwise leaves Chrome running;
  slow Chrome is skipped, not killed; a factory reconnects when its Chrome
  went away.
- **The daemon restart (12h / 1.5 GB) killed in-flight requests** — it now
  runs only while no request is using the daemon.
- **Chrome daemon start gave up after 4s and looped (#4)** — waits up to 30s
  (`GEMCLI_CHROME_START_TIMEOUT`), reports whether Chrome exited and which
  process holds the profile's `SingletonLock`, kills the whole process group on
  failure, and timestamps `chrome start` output. `chrome start` exits 0 when
  the daemon is already running (the LaunchAgent relaunched it every 5 min).
- **Long-running Chrome could hang** — Token Factory launched Chrome with
  stdout/stderr pipes nobody read; once full, Chrome blocked. Now discarded.
- **Failed attachments returned an invented answer (#6)** — when token
  capture failed, requests with files or image/video/music tools were resent
  without Chrome, and Gemini answered without the file. They now fail
  ("Not retrying without Chrome"). Replies that open by saying the file
  couldn't be opened raise `AttachmentNotRead` (exit 1) with the reply
  attached; `GEMCLI_ATTACHMENT_CHECK=0` disables the check.

### Added
- **`gemcli doctor --deep` (#5)** — captures a BotGuard token in the
  profile's Chrome (aborted inside Chrome, so nothing reaches Gemini) and
  uploads a tiny file; prints the failing stage and exits 1 on failure.
  Plain `doctor` now labels its auth checks "saved" and honors `-p`.
- **Keep-alive token-capture probe (#5)** — `keepalive run` records
  `capture: ok | failed: … | skipped: …` per signed-in profile next to the
  session status; `keepalive status` shows it; a failed capture exits 1.
  `--no-probe` skips it.
- **Browser path (#7)** — `GEMCLI_BROWSER` / `gemcli config set browser` accept
  a path to a Chromium binary (e.g. Chrome for Testing).
- **`gemcli chrome stop --now`** — `chrome stop` now waits for running jobs;
  `--now` doesn't.

### Changed
- **Agent guidance (skill, AGENTS section, `--ai`, troubleshooting)** — new
  Failure Triage: on exit 3 check `gemcli login --check --all` before acting,
  switch profiles, and run `gemcli login` only in an interactive session,
  never from scripts/cron/LaunchAgents/pipelines; per-message actions for
  exit 1; heavy-use guidance.

---

## [0.8.2] - 2026-09-24

### Fixed
- **The Chrome daemon disappeared after 12 hours** — when the daemon passed
  its age (12h) or memory (1.5 GB) limit, the health check logged
  "restarting" but only stopped it, leaving background jobs without Chrome
  until someone ran `gemcli chrome start`. It now starts a fresh daemon on the
  same profile and port (any free port as a fallback) and reports it as
  running. If Chrome cannot start from that process, it warns and reports the
  daemon as not running. Verified live: a daemon backdated past the limit was
  replaced (new PID, same port) and authenticated seconds later.

---

## [0.8.1] - 2026-09-23

### Fixed
- **`-p <profile>` showed another account's data when the Chrome daemon ran**
  — browser-cookie calls (`limits`, gems, downloads) read cookies from the
  daemon regardless of the requested profile, so every profile reported the
  daemon account's usage under its own name. The daemon is now used only for
  the profile it holds, and a Chrome signed in to a different account
  (`oPEP7c` ≠ profile email) is refused.
- **Saved cookies were injected into Chrome** — when a Chrome looked signed
  out, gemcli copied `auth.json` cookies into it (daemon, Token Factory, login,
  `chrome status`), including another profile's cookies into the daemon.
  Removed everywhere; `browser_auth` is now read-only (#3).
- **Token Factory copied the login profile** — it ran on `<profile>_tf`, a
  full copy of the Chrome profile (including its device-bound session). It now
  runs on the profile's own user-data-dir, closes Chrome with `Browser.close`
  so renewed cookies are flushed, and matches orphaned Chrome processes by
  exact path (the old pattern would have killed `mail4jbd2` for `mail4jbd`).
- **Token Factory readiness** now decides "signed in" by the account email,
  not `SNlM0e` (the signed-out page has one too).
- **`login --check --all` reported live profiles as `DEAD`** — a rejected
  saved `auth.json` copy is now reported as `stale` ("run `gemcli keepalive
  run`"), since the profile's own Chrome may still be signed in; only a
  signed-out daemon is `DEAD`. `stale` does not exit `3`.

### Changed
- **Usage-limit docs** no longer claim a fixed "2400 credits, resets ~every
  5h" window: pool size depends on the plan (e.g. 2,400 or 48,384 credits),
  and each row's reset time is what Google reports in `Resets In`.

---

## [0.8.0] - 2026-09-23

### Added
- **Session keep-alive (`gemcli keepalive`)** — keeps every profile's Google
  session alive for unattended use (#3). `keepalive run` opens each logged-in
  profile's **own** Chrome headless (never a copy, never injecting cookies),
  loads Gemini so Chrome renews the session the normal way, closes it cleanly
  so renewed cookies are flushed, and mirrors the fresh cookies into
  `auth.json`. The Chrome daemon's profile is refreshed from the daemon without
  touching its page. Results are appended to `logs/keepalive.jsonl`.
- **One-click recovery (`keepalive run --recover`)** — if a session expired,
  opens the profile's Chrome off-screen, clicks "Sign in", and clicks Google's
  account chooser only for the matching account. It never types anything; a
  password, passkey, or "verify it's you" page reports the profile `DEAD`.
- **`gemcli keepalive install-agent --every <hours> [--recover]`** — macOS
  LaunchAgent that runs the keep-alive periodically in the login session;
  `keepalive status` shows the schedule and each profile's last result;
  `keepalive uninstall-agent` removes it.
- **`gemcli login --check --all`** — read-only health check of every profile
  (no Chrome launched); exits `3` if any profile needs a manual sign-in.
- **Session lifecycle research** — `docs/research/auth/session-lifecycle.md`
  documents why sessions were being revoked and the design rules that follow.

### Fixed
- **Auto sign-in reported success while signed out** — the signed-out Gemini
  page also carries an `SNlM0e`, so Token Factory's auto sign-in "succeeded"
  before the redirect happened. Success now requires the account email
  (`WIZ_global_data.oPEP7c`).
- **`gemcli --ai` guide** — `gemcli login` no longer described as prompting
  for DevTools cookies (that is `--manual`); adds exit codes and keep-alive.
- **`uv.lock`** version synced with the package version.

### Changed
- README, CLAUDE.md, skill, AGENTS section, command reference, and
  troubleshooting guide document the keep-alive and session health checks.
- `load_launch_agent()` / `unload_launch_agent()` accept a plist path and
  label so other LaunchAgents can reuse them; `same_chrome_profile_path()`
  moved from the CLI to `core/chrome_manager.py`.

Verified live: all 7 profiles renewed through their own Chrome in ~1 minute,
both from a terminal and from the LaunchAgent, with every Chrome closed
cleanly and every mirrored `auth.json` accepted by Gemini.

---

## [0.7.2] - 2026-09-23

### Changed
- **Skill and AI docs updated for the 0.7.1 auth changes** — `SKILL.md`,
  `AGENTS_SECTION.md`, and the troubleshooting reference now document exit
  codes (`3` = auth error, `1` = other failure), extend the agent auth-recovery
  protocol (retry once → try another profile → ask the user to sign in, never
  loop on login), and warn that `gemcli login --force` also signs Chrome itself
  out of the account, so agents should avoid it and never run it in the
  background.

---

## [0.7.1] - 2026-09-23

### Fixed
- **Token Factory used the wrong profile** — without `--profile`, it fell back
  to a literal `"default"` profile instead of the active one. It read an empty
  auth state (so auto sign-in had no email and timed out with "Session expired
  — auto sign-in failed"), wrote refreshed cookies to a stray
  `profiles/default/auth.json`, and registered its Chrome under the wrong name
  in the port map. It now resolves the active profile (#3).
- **Browser cookie write-back never ran** — after every Token Factory request,
  syncing Chrome's rotated cookies back to `auth.json` crashed silently (wrong
  constructor argument), so `auth.json` drifted out of date (#3).
- **Logging into one profile killed a sibling profile's Chrome** — orphan
  cleanup matched `--user-data-dir` by substring, so `gemcli login -p mail4jbd`
  also killed the Chrome daemon running `mail4jbd2` (and `<profile>_tf`
  copies). It now matches the exact profile directory.
- **Failed commands exited 0** — auth, generation, and Token Factory errors now
  exit non-zero: `3` for auth errors (re-login needed), `1` otherwise, so
  `gemcli ... || fallback` scripts work (#3).
- Verified live: a Pro/Token Factory session that previously died within ~12
  minutes stayed healthy through a 35-minute soak with repeated Pro requests.

---

## [0.7.0] - 2026-09-19

### Added
- **Gemini Omni video controls** — `gemcli video` now supports orientation
  (`-O landscape|portrait`), model tiers (`-m flash|pro|lite|thinking`), and
  Create-videos templates (`-T "Logo reveal"`, `"Anime"`, ...) with an optional
  prompt. The MCP `video` tool gains `orientation` and `template`. Verified
  live: portrait 720x1280 and landscape 1280x720 downloads.
- **Video reference inputs** — `gemcli video -f <image>` (repeatable) and MCP
  `files` upload reference images/videos so Omni can animate a still or use a
  reference (verified live: portrait and landscape images animated into
  matching 10s videos). Reference renders take 5-15 minutes; session polling
  timeout raised to 15 minutes.
- **Image aspect ratios** — `gemcli image -A 1:1|9:16|3:4|4:3|16:9` (aliases
  square/portrait/landscape) plus MCP `aspect`, driven through the Images
  composer's aspect control. Verified live: 9:16 output at 768x1376.
- **Lyria 3.5 music controls** — `gemcli music` gains `--length/-L`
  (`short`/`standard`), `--vocals/-V` (`custom`/`vocals`/`instrumental`),
  `--genre/-g` (17 genres + aliases), and `--template/-T` (24 templates), also
  exposed on the MCP `music` tool. Legacy `--style` presets remain.
- **Limits account context and profile flipping** — `gemcli limits` now prints
  the account and profile it queried, then **grouped** usage rows (most features
  share one plan pool and report the same account-wide percentage; Video and
  Deep Think report their own), credits left, and a link to the live usage page. Skill/AGENTS/CLI docs document the
  quota-flip workflow (`gemcli -p <profile> limits` then
  `gemcli -p <profile> video ...` / `gemcli profile switch`).

### Changed
- **Usage limits semantics (verified against gemini.google.com/usage)** — the
  qpEbW fields are a **usage percentage** (`Used`) and a **credit pool**
  (`Credits Left`; 2400 credits per rolling window), not per-feature counts.
  Display, JSON output, and docs updated accordingly. Feature labels refreshed
  to current branding: Video (Gemini Omni), Music (Lyria 3.5), Deep Think,
  Pro Prompts.
- **qpEbW request format** — the RPC now requires an explicit feature list and
  processes one `[1, feature_id]` pair per call; `LimitsService` batches one
  payload per feature in a single `batchexecute` request.
- **Skill, `--ai` docs, desktop-extension metadata, AGENTS section** — fully
  refreshed for the new video/image/music capabilities, limits semantics, and
  profile switching.

### Fixed
- **Usage-exhausted tools failed silently** — a disabled tool (usage limit)
  now raises `UsageLimitExceeded` instead of falling back to a direct HTTP
  request that produced a wrong artifact.
- **Stale cached cookies broke RPCs** — browser-cookie RPC batches retry once
  with live cookies from Chrome when pre-populated auth.json cookies return no
  data (fixes `gemcli limits` on older sessions).
- **Token Factory UI automation for the new composers** — tool activation
  handles both drawer layouts ("Videos" / "Create video"), template cards,
  aspect-ratio dropdowns, the mode picker (hash `data-test-id` + selected-state
  verification + Extended-thinking reconciliation), and music dropdown buttons
  that rename after selection ("Length, Short").
- **RPC fallback body builder** — writes the image aspect-ratio fields
  (`inner[55]`, `inner[0][9]`) in addition to video orientation.

## [0.6.13] - 2026-08-19

### Added
- **Gemini 3.7 Flash support** — Added `gemini-3.7-flash` and
  `gemini-3.7-flash-extended` aliases across the CLI, MCP server, and
  Anthropic-compatible API.
- **Independent Extended thinking toggle** — Added CLI flags, interactive
  `/thinking on|off`, MCP `extended_thinking`, and Anthropic `thinking` support
  while preserving the legacy `thinking` alias.

### Changed
- **Skill and model documentation** — Updated the bundled Gemini skill,
  references, model discovery output, and hack launcher for the current model
  picker.

### Fixed
- **Version consistency** — Synchronized the package, lockfile, changelog,
  extension manifest, and installed skill version to `0.6.13`.

## [0.6.12] - 2026-07-22

### Fixed
- **File/video attachments silently dropped** — `GeminiClient._send_via_token_factory()` accepted `file_data` but never injected it into the BotGuard-signed body, so the model always responded "no file attached" for every file type (video, image, text). File attachments are now patched into Chrome's captured body (`inner[0][3]`) before relay. Verified live: video ("Color bars"), image ("Testcard"), and text all analyzed correctly.
- **Per-type file-type code** — `ChatService` hardcoded the file-type marker `16` for every attachment. Google now uses a per-category code (confirmed via live capture: video = `2`). Added a MIME-category mapping (video=2, image=3, audio=4, text/other=16).

### Added
- **File upload limits documented in the skill** — `SKILL.md`, `references/command_reference.md`, and `docs/research/features/file-upload.md` now carry the current Gemini Apps limits (as of July 2026): up to 10 files/prompt; video ≤ 2 GB (total ≤ 5 min free / 1 hour Pro); other files ≤ 100 MB; audio ≤ 10 min free / 3 hours Pro; plus context-window and rolling-quota guidance.
- **Video analysis model guidance** — SKILL.md recommends the default Gemini 3.6 Flash for video analysis and explains when to reach for Pro (long videos near the 1-hour cap, deep multi-step reasoning).

---

## [0.6.11] - 2026-07-22

### Changed
- **Gemini 3.6 Flash & 3.5 Flash-Lite support** — Updated model hashes for the July 21, 2026 Google model rollout. `fast` now routes to Gemini 3.6 Flash (`56fdd199312815e2`), `lite` to Gemini 3.5 Flash-Lite (`8c46e95b1a07cecc`), and `pro`/`thinking` to the current 3.1 Pro / Extended thinking selection. Hashes captured and verified against the live signed-in Gemini web UI.
- **Full model-header selection** — `Model.header` now sends the complete `x-goog-ext-525001261-jspb` header (including the `[4,5,6,8]` capability list and the model-tail fields) instead of only varying the hash. Required because 3.1 Pro and Extended thinking share the same hash (`e6fa609c3fa255c0`) and are distinguished only by the header tail (`3,1` = Pro Standard, `3,2` = Extended).

### Added
- **New model aliases** — `gemini-3.6-flash`, `gemini-3.6-thinking`, `gemini-3.5-flash-lite`, `flash-lite`, and `lite` (now supported across CLI, MCP, and the Anthropic-compatible API server). Added `gemini-flash-lite` to the API `/v1/models` list.

### Fixed
- **Pro/Thinking routing collision** — `thinking` previously fell back to 3.1 Pro because both shared a hash with no distinguishing header tail; Extended thinking now routes correctly via header tail `3,2`.
- **Flash-Lite hash** — Corrected `lite` to the server-confirmed `8c46e95b1a07cecc` (the earlier WIZ-order guess `1d44b34bcaa1c04d` was rejected by the server).
- **`pro` hash** — Updated to the live `e6fa609c3fa255c0` (was the legacy Omni hash `9d8ca3786ebdfbea`).

---

## [0.6.10] - 2026-06-02

### Fixed
- **Persistent Chrome daemon memory/CPU exhaustion** — `check_daemon_health()` now auto-stops the persistent Chrome daemon (started via `gemcli chrome start`) when its uptime exceeds 12 hours or its RSS exceeds 1.5 GB. The next caller (Token Factory or `_ensure_browser_cookies`) auto-launches a fresh ephemeral Chrome. Closes #1.
- **macOS LaunchAgent thrash** — Increased LaunchAgent `ThrottleInterval` from 30s to 300s so the periodic daemon restart doesn't tight-loop if Chrome exits quickly.

---

## [0.6.9] - 2026-05-28

### Added
- **Chrome idle auto-shutdown** — Token Factory now automatically shuts down Chrome after a configurable idle period (default 120 s, override with `GEMCLI_CHROME_IDLE_TIMEOUT=<seconds>`; set to `0` to disable). Chrome restarts transparently on the next request. Only applies to locally-launched Token Factory instances — daemon Chrome (`gemcli chrome start`) is never touched.

### Fixed
- **TOCTOU race in idle shutdown** — Added a generation counter to `_idle_shutdown` so an in-flight timer callback that has already started executing cannot call `shutdown()` after `capture()` has cancelled the timer, eliminating potential crashes (`None` WebSocket URL mid-capture) under concurrent load.
- **`GEMCLI_CHROME_IDLE_TIMEOUT` validation** — A non-numeric env var value (e.g. `2m`) now logs a warning and falls back to the 120 s default instead of crashing `TokenFactory.__init__` with `ValueError`.

---

## [0.6.8] - 2026-05-25

### Fixed
- **`gemcli login` with Chrome daemon running** — Login now temporarily stops a matching `gemcli chrome start` daemon before opening the visible auth browser, then restarts the daemon after authentication. This prevents login from attaching to an invisible headless daemon and waiting forever.
- **Chrome profile lifecycle cleanup** — Hardened CDP cleanup for orphaned profile Chrome processes, stale mapped CDP ports, PID-less daemon records, and live `SNlM0e` token extraction after browser login.

---

## [0.6.7] - 2026-05-24

### Added
- **Gemini 3.1 Flash-Lite Support** — Added support for the newly rolled-out Gemini 3.1 Flash-Lite model (`8c46e95b1a07cecc`) with dynamic model switches and aliases (`flash-lite`, `gemini-3.1-flash-lite`). Discovered and verified live on-device configurations via Chrome DevTools.
- **Gemini Omni Video Prompting Guide** — Added a comprehensive reference manual (`src/gemini_web_mcp_cli/data/references/VIDEO_PROMPTING_GUIDE.md`) detailing the exact prompting strategies, cinematography camera directions, waxy crayon/graphite/risograph style transfers, kinetic typography, visual storyboards, and interactive multi-turn workflows for the new Gemini Omni (Veo 3.1) video generation engine.

### Changed
- **Skill reference (`SKILL.md`)** — Renamed section 4 to "Video Generation (Gemini Omni / Veo 3.1)", added direct link to the new video prompting reference guide, and integrated quick rules, templates, and CLI command examples.
- **Workflows documentation (`workflows.md`)** — Completely refactored the video generation workflow to support multi-turn conversational editing, CLI chat REPL iterations (butterflies, bees, fireflies swap), and programmatic FastMCP multi-turn video edits.

---

## [0.6.6] - 2026-05-22

### Added
- **Gemini 3.5 Model Support** — Updated model hashes for the newly released Gemini 3.5 Flash (`fbb127bbb056c959`), Gemini 3.5 Thinking (`5bf011840784117a`), and Gemini 3.1 Pro / Omni (`9d8ca3786ebdfbea`).
- **Flexible Model Aliases** — Added aliases for easy model switching, including `gemini-3.5-flash`, `gemini-3.5-thinking`, `gemini-3.1-pro`, `gemini-omni`, and `omni`.

### Fixed
- **Token Factory UI Integration** — Completely rewrote tool activation/deactivation Javascript to support Google's new "Upload & tools" drawer structure, aria-label selectors, and onboarding modals.

---

## [0.6.5] - 2026-05-13

### Added
- **Nano Banana Image Prompting Guide** — Added a premium-grade standalone prompting guide (`src/gemini_web_mcp_cli/data/references/IMAGE_PROMPTING_GUIDE.md`) detailing templates, recipes, aspect ratios, lighting setups, text limits, and positive framing best practices for Nano Banana 2 and Pro.
- **Updated `SKILL.md`** — Enhanced the image generation section in `SKILL.md` with quick rules, templates, and example commands.

---

## [0.6.4] - 2026-05-13

### Added
- **Silent Token Factory Session Refresh** — Headless Chrome now silently recovers expired Chrome daemon sessions using saved `auth.json` cookies using a fast HTTP-based `SNlM0e` fetch before falling back to full auto sign-in.
- **Login stability** — `gemcli login` attempts silent HTTP session refreshes before forcing full Google re-authentication when stale cookies are detected.

---

## [0.6.3] - 2026-05-13

### Fixed
- **Version string** — `gemcli --version` and the skill now correctly report the installed version. `__init__.py` was not updated alongside `pyproject.toml` in v0.6.2.

---

## [0.6.2] - 2026-05-12

### Fixed
- **SSH login on macOS** — `gemcli login` now detects SSH sessions (`SSH_CONNECTION` / `SSH_TTY`) and automatically runs Chrome headlessly. Previously Chrome opened a window on the machine's physical display, invisible to the SSH user. Session refreshes work fully headless; new logins fail fast with a clear message pointing to `gemcli login --manual` or Screen Sharing.
- **SSH Keychain errors** — adds `--password-store=basic` on SSH to suppress `errSecInteractionNotAllowed` floods from macOS Keychain being inaccessible in non-GUI sessions.

### Changed
- **`BrowserTransport`** — SSH headless enforcement and `--password-store=basic` now also applied to `BrowserTransport.start()` for consistency.
- **Chrome arg deduplication** — extracted `_chrome_base_args()` helper; four separate Chrome launch sites now share a single source of truth for the base flags.
- **Docs** — added "Login Over SSH (macOS)" section to troubleshooting guide; updated skill reference with SSH behavior note.

---

## [0.6.1] - 2026-05-12

### Fixed
- **Windows Edge login timeout** — increased CDP startup timeout from 15s to 25s on Windows to handle GPU process initialization delays.
- **Windows browser launch** — added `--disable-gpu` flag on Windows to avoid Edge GPU process crashes that delay CDP port availability.
- **Windows process isolation** — `CREATE_NEW_PROCESS_GROUP` ensures the browser doesn't get swallowed by an existing browser instance's process tree.
- **Windows SingletonLock cleanup** — removes stale lock files from crashed sessions before launching.
- **Stale error messages** — "Cannot connect to Chrome" now shows the actual detected browser name and actionable guidance.

---

## [0.6.0] - 2026-05-12

### Added
- **Multi-browser detection** — gemcli now supports Chrome, Brave, Edge, Arc, Chromium, Vivaldi, Opera, and Comet on macOS, Linux, and Windows. Set preference via `GEMCLI_BROWSER` env var or `gemcli config set browser <name>`.
- **`gemcli config set browser`** — new config key to persist browser preference (valid: auto, chrome, brave, edge, arc, chromium, vivaldi, opera, comet).
- **Hermes Agent skill support** — `gemcli skill install` now supports Hermes Agent (NousResearch) alongside existing tools.
- **Centralized JSON I/O** — new `core/json_io.py` with `read_json_dict` / `write_json_file` used by profiles, CDP, chrome manager, and setup.
- **Profile config mtime caching** — `ProfileManager` avoids redundant file reads when config hasn't changed on disk.

### Changed
- **Browser detection caching** — `_find_browser_binary()` now caches results keyed by preference, avoiding repeated filesystem scans in long-lived processes (MCP server, Token Factory retries).
- **Error messages** — all "Chrome not found" errors now list supported browsers and suggest `GEMCLI_BROWSER` or `gemcli config set browser`.
- **`gemcli doctor`** — browser section now shows the detected browser name/path and hints for configuration if none found.
- **`gemcli login`** — messages say "browser" instead of "Chrome" and show the detected browser name.
- **Hardened file I/O** — all `read_text()` / `write_text()` calls across the codebase use explicit `encoding="utf-8"` for Windows compatibility.
- **Narrowed exception handlers** — replaced broad `except Exception` with specific exception types throughout.
- **Unified tool detection** — `setup.py` delegates to `skill.py`'s `_is_tool_installed` instead of maintaining a parallel detection dict.
- **Eliminated lazy imports** — moved deferred imports in `chrome_manager.py` and `cdp.py` to top-level for consistency.
- **Removed one-off wrappers** — inlined `_find_chrome_binary()` in CLI doctor, dropped `_read_json_config` / `_write_json_config` from setup.

### Fixed
- **Default image model** — switched back from Flash to Pro for `ImageService.generate()`.

---

## [0.5.9] - 2026-05-11

### Changed
- Internal release (multi-browser detection groundwork, JSON I/O consolidation, encoding hardening).

---

## [0.5.8] - 2026-05-10

### Fixed
- **Token Factory headless auth recovery** — automatic sign-in now handles Google's email-entry OAuth page when no saved browser account chooser exists, using the saved profile email before continuing the flow.
- **Image/video/music generation after Chrome auth drift** — Token Factory now syncs saved `auth.json` cookies into the active Chrome CDP session and verifies live `SNlM0e` before falling back to OAuth UI sign-in. This avoids unnecessary forced logins when Python auth is valid but the daemon Chrome profile is stale or signed out.
- **Chrome daemon auth reporting** — `gemcli chrome status` now checks verified Gemini browser auth (`__Secure-1PSID` plus live `SNlM0e`) and reports more precise stale-cookie states instead of treating any Google auth cookie as authenticated.

### Changed
- **Shared browser auth verifier** — extracted CDP browser auth sync/status logic into a reusable helper used by Token Factory, Chrome daemon status, and browser-cookie extraction paths.
- **Chrome daemon launch flags** — aligned the persistent daemon with Token Factory's Chrome user agent and automation-control flag so both browser paths behave consistently.

## [0.5.7] - 2026-05-05

### Changed
- **CDP code quality pass** — extracted shared `_create_cdp_websocket()` helper (IPv4 normalisation, `suppress_origin` fallback, `StaleTargetError` detection) used by `execute_cdp_command`, `run_js`, and `download_via_page_fetch`, eliminating the triplicated connection-setup boilerplate. Extracted `_navigate_with_stale_recovery()` helper that collapses the two identical stale-target recovery blocks in `extract_cookies_via_cdp` into a single call, and skips the navigate when the recovered page is already at the target URL. Removed 4 redundant `window.__cap = null` calls in `token_factory.py` — all were no-ops since `XHR_INTERCEPTOR_JS` resets `__cap` on install and the subsequent `navigate_to_url` destroys the page JS context.

---

## [0.5.6] - 2026-05-05

### Fixed
- **`gemcli login` crash with stale CDP target** — when Chrome's tab was recreated between page discovery and the stale-session re-navigation, `extract_cookies_via_cdp` raised an unhandled `StaleTargetError`. Both vulnerable `navigate_to_url` calls now catch `StaleTargetError`, re-discover the page, and retry with a fresh WebSocket URL.

---

## [0.5.5] - 2026-05-05

### Fixed
- **Token Factory generational decay** — image/video/music generation silently failed after 6-8 successive generations due to accumulated stale state. Four root causes resolved:
  - `window.__cap` is now explicitly cleared after each successful XHR capture and before each interceptor install, preventing stale captures from blocking the `!window.__cap` guard on subsequent generations.
  - Added `time.sleep(1)` after tool deactivation (Images/Videos/Music) to let the Gemini UI fully process the deactivation before Chrome navigates away, preventing half-deactivated tool state from corrupting the next generation's BotGuard signature.
  - Added a generation counter that forces a full page reload every 5 captures, refreshing `WIZ_global_data.SNlM0e` tokens that go stale server-side after many rapid generations.
  - Rewrote `run_js()` to use a single WebSocket connection for `Runtime.enable` + `Runtime.evaluate` (was two separate connections), cutting CDP connection churn from ~25–70 opens per capture to ~13–35, reducing Chrome CDP target instability.

---

## [0.5.4] - 2026-04-16

### Added
- **macOS LaunchAgent for Persistent Chrome** — `gemcli chrome install-agent` installs a launchd plist that starts the Chrome daemon automatically at login in the GUI (Aqua) session. This solves the issue where `gemcli chrome start` fails from background processes (like AI agent slots) that lack WindowServer access. Added `gemcli chrome uninstall-agent` to remove it.

### Fixed
- **Silent failure on image generation** — the default image model was switched back from Flash to Pro. Flash fallback was failing silently ("please try again with 'Create Image' enabled") for users without Gemini Advanced.
- **Image generation API text response handling** — if image generation fails and Gemini returns a text response containing failure hints ("create image", "i can't create"), the CLI now surfaces a clear, actionable error instead of silently printing raw text.
- **Parallel Chrome navigation race conditions** — added polling, multi-tier fallback, and URL state verification (`get_gemini_page_ws_url` and `find_or_create_gemini_page`) to ensure multiple background tasks don't overwrite the active tab mid-navigation.
- **Stale WebSocket Target IDs** — Token Factory and CDP clients now gracefully capture 500 WebSocket errors (`StaleTargetError`) and clear the stale port-map entry seamlessly instead of crashing, falling back to a fresh Chrome launch.

---

## [0.5.3] - 2026-04-14

### Changed
- **Migration refactor** — extracted `_migrate_skill_dir()` helper, eliminating duplicated rename/rmtree logic. cc-claw migration scope fixed: removed erroneous project-relative path (only user-level `~/.cc-claw/` is a valid migration source). Exported README now includes Alef Agent install instructions.

---

## [0.5.2] - 2026-04-14

### Changed
- **CC-Claw renamed to Alef Agent** — `gemcli skill install alef-agent` replaces `cc-claw`. Installs to `~/.alef-agent/workspace/skills/gemini-web-skill`. Existing cc-claw installs are automatically migrated to the new path on next `gemcli skill` invocation.

---

## [0.5.1] - 2026-03-31

### Fixed
- **Chrome Lifecycle Stabilization (CRITICAL)** — completely overhauled Chrome management to eliminate recurring "zombie" processes and lock-file contention that caused silent hangs.
  - **Health-checked discovery**: actively validates that a Chrome instance has responsive pages (`/json`), not just an open port, preventing zombie hijacking.
  - **Profile-aware isolation**: prevents the CLI and MCP server from hijacking unrelated browser instances (e.g. Antigravity's Chrome).
  - **Automated remediation**: purges stale lock files (`SingletonLock`, `SingletonSocket`, `SingletonCookie`) and gracefully kills unrecoverable Chrome processes automatically.
  - Added `gemcli chrome cleanup` command for proactive manual zombie scanning and remediation.
  - Enhanced `gemcli chrome status` and `gemcli doctor` to explicitly detect and warn about zombie and unresponsive states.

---

## [0.5.0] - 2026-03-26


### Added
- **`gemcli gems create --tool <name>`** — set the default tool for a gem at creation time. Accepts friendly aliases (`none`, `image`, `video`, `music`, `canvas`, `deep-research`, `learning`). Resolves to the internal GemDefaultTool code (e.g. `image` → 14). Previously the flag existed in the service layer but was never exposed to the CLI.
- **`gemcli gems create -f <path>`** — attach one or more local files as knowledge sources to a newly created gem. Repeatable flag (`-f file1.pdf -f file2.txt`). Brings CLI to full parity with the service layer.
- **`gemcli chat --gem <gem_id>`** — send a chat message to a specific custom gem by ID, bypassing standard model resolution. Enables CI/headless automation of gem personas from the CLI.
- **`gem_id` parameter on MCP `chat` tool** — agents can now target custom gems programmatically via `gem_id` in the `chat` MCP tool. Enables agentic gem persona usage without the CLI.

### Fixed
- **CDP `ConnectionRefusedError` on macOS (CRITICAL)** — `localhost` resolves to `::1` (IPv6) on macOS while Chrome binds its debug port on `127.0.0.1` only. All CDP WebSocket URLs in `core/cdp.py` now normalize `ws://localhost` → `ws://127.0.0.1`, restoring reliable gem operations in headless/CI environments.
- **`gemcli gems delete` blocks headless/CI** — the delete command required an interactive TTY confirmation prompt (`Are you sure?`) which caused hangs in non-interactive scripts and CI pipelines. Replaced with a `--yes` / `-y` flag; the confirmation prompt is shown only when the flag is absent.

---

## [0.4.9] - 2026-03-17


### Fixed
- **Image generation unreliable — Token Factory tool activation (CRITICAL)** — Image generation via `gemcli image` and the MCP `image` tool was inconsistent: sometimes producing images, sometimes returning text-only responses. Root cause: `tool_id=14` (IMAGE_TOOL_ID) was passed from `ImageService.generate()` to `client.send()` but never forwarded to `TokenFactory.capture()`. Chrome sent whatever its default chat mode was, relying on Gemini's prompt heuristics to detect image intent — which became unreliable after a Google server-side update. Fix: Token Factory now accepts `tool_id` and uses CDP to click the Tools drawer → "Images" toggle in Chrome's Gemini UI before typing the prompt and capturing the BotGuard-signed request. This makes image generation deterministic. Same mechanism supports Videos (`tool_id=11`) and Music (`tool_id=21`).

---

## [0.4.8] - 2026-03-15

### Fixed
- **Image download 15-minute token drift** — Image generation downloads via `httpx` fallback would fail with a `text/html` login redirect after ~15 minutes of session uptime due to the Gemini `SNlM0e` token naturally rotating, while the initial captured cookies were retained. Fixes include active synchronization of any fresh Token Factory cookies back to the `AuthManager` state, and a robust retry hook that forces a fresh CDP cookie extraction if the CDN redirects an image format request to a login wall.

---

## [0.4.7] - 2026-03-15

### Added
- **CC-Claw skill support** — `gemcli skill install cc-claw` installs the Gemini skill to `~/.cc-claw/workspace/skills/gemini-web-skill/`.

---

## [0.4.6] - 2026-03-15

### Fixed
- **Chrome 145 headless regression (CRITICAL)** — Chrome v145 broke `--headless=new`: the debugging port no longer binds, making Token Factory, auth recovery, and Chrome daemon completely non-functional. Switched all 4 files (`token_factory.py`, `auth.py`, `cdp.py`, `chrome_manager.py`) to `--headless` (old mode) which works correctly on Chrome 145.
- **Token Factory page creation flakiness** — `find_or_create_gemini_page` was called once with no retry. If the headless Chrome debugger wasn't responsive yet, Token Factory failed silently. Now retries up to 5 times (15s total).

### Added
- **Automatic sign-in recovery** — when session cookies expire mid-operation, Token Factory now clicks the "Sign in" button via CDP, lets Chrome's saved credentials auto-complete the OAuth flow (~0 seconds), extracts fresh cookies, and saves the refreshed auth state to disk. Zero user interaction. Falls back to `AuthError` if auto-recovery fails (e.g., password page, no saved credentials).

---

## [0.4.5] - 2026-03-15

### Added
- **Profile rename** — new `gemcli profile rename <old> <new>` command renames a profile along with its Chrome profile directory, Token Factory profile, auth.json paths, and active profile config. Cannot rename NLM-sourced profiles.
- **Port-to-profile mapping** — Chrome instances now register their CDP port in a shared `chrome-port-map.json` mapping file (pattern adapted from NotebookLM MCP CLI). Multiple gemcli tools (CLI, MCP, Token Factory) and cross-product tools (NotebookLM, Antigravity) can coexist without port conflicts.
- **Profile-aware Chrome discovery** — `find_existing_gemcli_chrome()` only reuses Chrome instances belonging to the same profile, preventing the Token Factory from hijacking another tool's browser session.
- **Browser cookie pre-population** — `GeminiClient` now pre-populates browser cookies from auth state on init. RPCs that require browser cookies (limits, gems) work immediately without needing a Chrome session or dummy API calls.
- **Profile switch detection (MCP)** — the MCP server detects when auth cookies change on disk (e.g., via `gemcli login switch`) and reinitializes the client automatically.

### Fixed
- **`gemcli limits` returning "Browser cookies required" after successful login (CRITICAL)** — root cause was a dual-auth system mismatch: the 37 real session cookies from `gemcli login` were stored in auth state but never passed to browser-cookie RPCs. The Token Factory's Chrome profile only had 8 generic tracking cookies. Fixed by pre-populating from auth state.
- **Chrome port conflicts blocking CLI and MCP** — any Chrome instance on ports 9222–9231 would block `gemcli` from starting a Chrome daemon, even if it belonged to a different tool. Replaced global port scanning with profile-aware port mapping and dynamic port selection.
- **Token Factory reusing wrong Chrome** — the Token Factory used `find_existing_chrome()` which could connect to Antigravity's browser or other unrelated Chrome instances. Now uses `find_existing_gemcli_chrome()` with profile filtering.

### Removed
- **`send(".")` hacks** — removed dummy API calls (`send(".")`) from CLI limits command and MCP limits/gems tools that were used to force browser cookie population. No longer needed with auth state pre-population.

---

## [0.4.4] - 2026-03-13

### Changed
- **Skill install paths use `.agents/skills/`** — `gemcli skill install gemini-cli` now installs to `~/.agents/skills/` (user) and `.agents/skills/` (project) instead of the old `~/.gemini/skills/`. Aligns with Gemini CLI v0.33.1+ which scans `.agents/skills/` with higher priority as the cross-tool compatible alias. Antigravity project path also fixed from `.agent/` (singular) to `.agents/`.

---

## [0.4.3] - 2026-03-08

### Added
- **Codex native MCP support** — `gemcli setup add codex` / `gemcli setup remove codex` now use `codex mcp add/remove` CLI commands instead of redirecting to skill install. Codex appears as a configurable tool in `gemcli setup add all` with proper detection and status.
- **Claude Desktop `.mcpb` extension** — new `desktop-extension/` directory with `manifest.json` (MCP manifest v0.2) + `run_server.py` (cross-platform `uvx` finder for macOS/Linux/Windows). Packaged as `.mcpb` zip and attached to GitHub releases. This solves Claude Desktop's restricted PATH issue where GUI apps can't find CLI tools.
- **MCPB build script** — `scripts/build_mcpb.py` syncs version from `pyproject.toml` into `manifest.json` and packages the extension.
- **GitHub Actions MCPB pipeline** — release workflow now builds and uploads the `.mcpb` extension alongside PyPI artifacts.

### Changed
- **Claude Desktop removed from CLI setup** — `claude-desktop` is no longer a valid argument for `gemcli setup add/remove`. Users should download the `.mcpb` extension from the GitHub release instead.
- **Full binary paths for JSON clients** — `_add_mcp_server()` now resolves the full path to `gemini-web-mcp` via `shutil.which()`, ensuring GUI apps launched from the Dock can find the binary.

---

## [0.4.2] - 2026-03-08

### Added
- **`setup add all` / `setup remove all`** — interactive multi-tool setup ported from the NotebookLM MCP CLI sibling project. `gemcli setup add all` scans the system for AI tools, shows a Rich table with detection and configuration status, and lets you choose which tools to configure (all, specific numbers, or none). `gemcli setup remove all` removes MCP from all configured tools with explicit confirmation (defaults to No for safety).
- **Rich-click colored CLI help** — replaced plain Click with `rich-click` for styled, colorful `--help` output across all commands (bordered panels, colored usage, styled options). Drop-in upgrade — same API, better aesthetics.

### Fixed
- **Codex skill paths** — updated from legacy `.codex/AGENTS.md` format to official `.agents/skills/SKILL.md` per OpenAI Codex documentation. Detection logic now checks `~/.agents/` existence.

### Changed
- **CLI argument validation** — `setup add` and `setup remove` switched from `click.Choice()` to manual validation to support dynamic values (`all`, `json`) alongside registry keys. Invalid clients now show a clean error with available options.

---

## [0.4.1] - 2026-03-08

### Fixed
- **Legacy skill migration** — `gemcli skill install` now detects and migrates legacy `gemini-skill` installs to the new `gemini-web-skill` name, preventing stale skill files from persisting after the rename.

---

## [0.4.0] - 2026-03-08

### Changed
- **Skill renamed to `gemini-web-skill`** — the installable AI tool skill was renamed from `gemini-skill` to `gemini-web-skill` across all formats (Claude Code, Cursor, Windsurf, Codex, etc.) to avoid naming conflicts with the official Gemini CLI.

---

## [0.3.33] - 2026-03-03

### Fixed
- **Stale cookie detection during login** — `gemcli login` would falsely report "Authentication successful!" when `__Secure-1PSID` existed in the Chrome profile but was expired. Now validates cookies by checking for the SNlM0e session token after extraction. If missing, automatically clears stale cookies from Chrome via CDP and waits for the user to re-login — no more need for `gemcli login --force` when cookies expire.

---

## [0.3.32] - 2026-03-03

### Fixed
- **Token Factory profile copy fails when Chrome is running** — `shutil.copytree` crashed with `shutil.Error` when the source Chrome profile had runtime artifacts (Unix sockets, dangling symlinks) created by an active Chrome process. The profile copy now skips `SingletonSocket`, `SingletonCookie`, `RunningChromeVersion`, and `SingletonLock`. Also fixed `__version__` not matching `pyproject.toml` (was stuck at 0.3.30).

---

## [0.3.31] - 2026-03-03

### Fixed
- **BotGuard cryptographic body signing** — Google's Gemini API changed to require BotGuard cryptographically signed request bodies for all requests. The CLI and MCP server now route all chat requests through the Token Factory, which launches Chrome, types the real user prompt, and captures/relays the exact cryptographically signed body. This completely restores text generation and fixes the `0 candidates` error that affected Python-built request bodies. Note: File uploads are currently under separate investigation.

---

## [0.3.30] - 2026-03-03

### Fixed
- **Streaming file upload for large videos** — File uploads (100MB+ videos) no longer load the entire file into memory via `read_bytes()`. The upload now streams in 1MB chunks using an async generator, reducing RAM usage from file-size to ~1MB constant and preventing event loop blocking. Upload timeout scales dynamically with file size (base 60s + 2s/MB, minimum 120s) instead of the previous hardcoded 300s. Progress logging reports every ~10MB for visibility into long uploads. Explicit `Content-Length` header ensures compatibility with chunked streaming.

---

## [0.3.29] - 2026-03-01

### Fixed
- **Silent token recovery** — When `SNlM0e` tokens expire (causing "Are you signed in?" errors during image/video/music generation), the CLI now automatically recovers by launching headless Chrome in the background, extracting fresh cookies and tokens via CDP, and saving them — all without any user interaction. Previously, users had to manually run `gemcli login --force` to fix expired tokens.

---

## [0.3.28] - 2026-03-01

### Added
- **Image URL extraction in Chat** — The `chat` MCP tool and `gemcli chat` CLI commands now actively extract and return the direct URLs of freshly generated images from Gemini (e.g., when Gemini uses its internal Imagen 3 capabilities to modify or generate an image during a chat session).

---

## [0.3.27] - 2026-03-01

### Added
- **Force login flag** — Added a `--force` / `-f` flag to the `gemcli login` command. This completely clears all cookies and forces a fresh authentication flow. Useful when Google invalidates specific tokens (like `SNlM0e`) while leaving basic cookies intact, which previously tricked the CLI into closing the login window prematurely.

### Fixed
- **Invisible Chrome port conflicts** — The background Token Factory now runs its headless Chrome instances starting at port `9300+`. Previously, it used the same `9222+` range as the visible `gemcli login` Chrome, causing the CLI to connect to the invisible background process and hang on "Waiting for you to log in...".
- **BotGuard headless detection** — Added `--disable-blink-features=AutomationControlled` and a realistic macOS `User-Agent` to the headless Token Factory Chrome launch arguments to prevent BotGuard from serving a broken page state.

---

## [0.3.26] - 2026-03-01

### Fixed
- **Chrome profile locking when MCP server and CLI run concurrently (HIGH)** — the Token Factory's headless Chrome competed for Chrome's `SingletonLock` with `gemcli login` and `gemcli chat` CLI commands using the same profile directory. Now the Token Factory uses an isolated copy of the login profile (`<profile>_tf/`), eliminating all contention. The copy is reused across restarts and only refreshed when the source profile's cookies change (i.e. after re-login).
- **Stale Chrome processes not fully killed** — `_kill_stale_chrome` now waits up to 5 seconds for graceful exit and escalates to `SIGKILL` for any survivors. Previously used a fixed `time.sleep(2)` which was insufficient for Chrome renderer subprocesses.
- **Orphaned Chrome on SIGTERM** — `atexit` handlers do not fire when the OS delivers `SIGTERM` (Python uses the default handler which terminates immediately). Added `SIGTERM`/`SIGINT` signal handlers that call `shutdown()` before exit, ensuring Chrome cleanup when the MCP subprocess is killed by its parent process (e.g. Node.js `StdioClientTransport`).

---

## [0.3.25] - 2026-03-01

### Added
- **Interactive JSON config generation** — `gemcli setup add json` generates a customized json snippet for configuring the MCP server in any tool. Supports `uvx` and absolute paths, outer and inner dictionary schemas, printing with syntax highlights, and macOS clipboard support via `pbcopy`.

---

## [0.3.24] - 2026-03-01
### Fixed
- **TokenFactoryError returned as successful text (CRITICAL)** — all 6 MCP tools (`chat`, `image`, `video`, `music`, `research`, `gems`) caught `TokenFactoryError` and returned JSON error strings with `isError: false`. MCP clients treated these as valid data, causing silent failures. Now exceptions propagate through FastMCP which correctly sets `isError: true`.
- **Chrome profile locking from stale processes** — when an existing Chrome instance held the `SingletonLock` on the profile directory, the Token Factory would fail to launch a second instance. Now kills stale Chrome processes and removes `SingletonLock` before launching.
- **Orphaned Chrome processes on exit** — when the MCP server subprocess died, Chrome was never cleaned up. Added `atexit` handler to ensure `shutdown()` runs, and `shutdown()` now cleans up `SingletonLock` files.

### Removed
- `_token_factory_error_response()` helper — no longer needed since errors propagate naturally.

---

## [0.3.23] - 2026-02-26

### Added
- **Nano Banana 2 image generation** — default image model is now Nano Banana 2 (Gemini 3.1 Flash Image), which Google shipped server-side on Feb 26, bringing Pro-level quality (text rendering, world knowledge, subject consistency) at Flash speed. `gemcli image -m pro` uses Nano Banana Pro (Gemini 3 Pro Image) for Pro/Ultra subscribers.
- **Nano Banana 2 quota tracking** — new Feature 21 in `gemcli limits` tracks Nano Banana 2 usage (100/day). Nano Banana Pro quota (Feature 19, 20/day) tracked separately.
- **Gem knowledge file uploads** — attach uploaded files (images, PDFs, documents) as knowledge sources when creating or updating gems via the 2-step `ProcessFile` resumable upload endpoint.
- **Google Drive file attachment for Gems** — attach Google Drive files as knowledge sources to gems. Drive files are processed via the `ProcessFile` batch endpoint.
- **`drive_search` action** for the `gems` MCP tool — search Google Drive directly from the gems workflow.
- **Enhanced gem listing** — `gems list` now shows attached resources (files, Drive docs, notebooks), default tool, and full instructions.
- **Email displayed in profiles** — `gemcli login --check` and `gemcli profile list` now show the Google account email for each profile (extracted from `WIZ_global_data.oPEP7c`).

### Fixed
- **Gem create/update payload format** — corrected the 18-element array structure for gem RPC calls.
- **Gems browser cookie requirement** — Token Factory trigger added to gems MCP tool for BotGuard-gated operations.
- **`login --check` always reporting expired tokens** — `Network.getAllCookies` returns cookies from all domains (youtube.com, doubleclick.net, etc.); same-name cookies from different domains collided in the flat dict, causing Gemini to serve a page without `SNlM0e`. Now filters to only `google.com`-domain cookies before saving, matching the Token Factory's existing behavior.

---

## [0.3.21] - 2026-02-23

### Fixed
- **Image download uses `=s1536` suffix** — the previous `=s2048` suffix caused CDN upscaling artifacts that broke watermark plugin compatibility. Google caps at 1024x1024 regardless, but `=s1536` produces pixel-consistent results that match the plugin's 48px alpha map. Native resolution (512x512) also didn't match the alpha map calibration.

---

## [0.3.20] - 2026-02-23

### Fixed
- **Image generation failing ("No images generated")** — root cause diagnosed via Chrome DevTools MCP capture of the live Gemini web UI:
  1. Added `tool_id=14` (IMAGE_TOOL_ID) at `inner_req_list[49]` — the web UI sends this when "Create image" tool is selected
  2. **Switched default model from Pro to Flash** — the web UI uses Flash for image generation. Pro + tool_id=14 returns empty responses (0 candidates). Flash + BotGuard + tool_id=14 works perfectly.
- Image generation now requires Chrome for BotGuard (same as video/music) but no longer requires the Pro model.

### Changed
- **Image generation default model**: Pro → Flash. Matches the Gemini web UI behavior.

---

## [0.3.19] - 2026-02-23

### Fixed
- **Image generation failing headlessly ("No images generated")** — added `tool_id=14` (IMAGE_TOOL_ID) and `force_token_factory=True` to image generation requests. Without explicit tool activation at `inner_req_list[49]`, Gemini relied on prompt heuristics and returned empty responses, especially in headless/background environments. Same class of bug as the video fix in v0.3.18.

---

## [0.3.18] - 2026-02-23

### Added
- **`VIDEO_TOOL_ID` and `IMAGE_TOOL_ID` constants** — explicit tool activation IDs for `inner_req_list[49]`, matching the codes discovered in `GemDefaultTool` (video=11, image=14, music=21).

### Fixed
- **Video generation producing images instead of videos** — added `tool_id=11` (VIDEO_TOOL_ID) to video generation requests at `inner_req_list[49]`. Without explicit tool activation, Gemini relied on prompt heuristics and frequently routed to image generation instead of Veo 3.1. Music generation already had this correct with `tool_id=21`.

---

## [0.3.17] - 2026-02-23

### Added
- **NotebookLM notebook attachment for Gems** — attach NotebookLM notebooks as knowledge sources when creating or updating gems. Reverse-engineered the `NXpLKc` RPC for listing notebooks and the client-side protobuf token format (no server round-trip needed, unlike Drive/uploaded files).
- **`list_notebooks` action** for the `gems` MCP tool — returns all NotebookLM notebooks with IDs, titles, and source counts.
- **`--notebook` CLI option** for `gemcli gems create` — repeatable flag to attach NotebookLM notebooks by UUID.
- **Notebook resources in gem listing** — `gems list` (CLI/MCP) now shows attached notebooks with source type `"notebook"` and the notebook UUID.

### Fixed
- **Multi-knowledge-entry payload format** — all knowledge entries (files, Drive docs, notebooks) are now wrapped in a single inner array (`[[entry1, entry2, ...]]`) matching the browser's behavior. Previously each entry was wrapped separately, causing only the first entry to be saved when attaching multiple knowledge sources.

---

## [0.3.16] - 2026-02-22

### Changed
- Moved plugins directory from `~/.config/gemcli/plugins/` to `~/.gemini-web-mcp-cli/plugins/` for consistency with existing config layout.

---

## [0.3.15] - 2026-02-22

### Changed
- Re-release after git history cleanup. No functional changes from 0.3.14.

---

## [0.3.14] - 2026-02-22

### Added
- **Usage limits checking** — new `gemcli limits` CLI command and `limits` MCP tool. Reverse-engineered the `qpEbW` RPC to report per-feature usage quotas (video, music, images, prompts, research, etc.) with remaining count and rolling reset time. Requires Chrome for browser cookies.
- **Video quota detection** — `wait_for_completion()` now detects quota rejection messages ("Sorry, I can't generate more videos") and raises `VideoGenerationError` immediately instead of polling for 5 minutes until timeout. MCP returns `status: "quota_exceeded"` to AI agents.
- **LimitsService** (`services/limits.py`) — new service wrapping the `qpEbW` (USAGE_INFO) RPC with `Feature` enum, `FeatureLimit` model, and structured JSON output.
- **Optional plugin directory** (`~/.config/gemcli/plugins/`) — support for drop-in plugins for potential future extensibility.

---

## [0.3.13] - 2026-02-21

### Fixed
- **Sparse protobuf response parsing** — Google A/B tests a compressed JSON format where arrays with many null elements become `[{"field_num": value}]` dicts with 1-based protobuf field numbers. This caused `has_music: false` and `has_video: false` on affected accounts. Fixed `get_nested()` in `parser.py` to handle both formats transparently.

---

## [0.3.12] - 2026-02-21

### Fixed
- Token Factory `at=` access token handling — video and music generation failed because Chrome's live `SNlM0e` token wasn't being included in replayed requests
- Video/music polling 400 errors from token mismatch between Python cache and Chrome session
- Prompt truncation in Token Factory — uses dummy string for BotGuard capture, injects real prompt in Python
- Various CDP and login stability fixes

---

## [0.3.9] - 2026-02-20

### Added
- `gemcli hack claude -m pro` — model selection flag for hack claude sessions
- Model identity injection so Gemini can correctly identify which model it's running as

### Fixed
- Pro model context loss, system prompt refusal, and prompt format issues in hack claude

---

## [0.3.0] - 2026-02-20

### Added
- **File upload support** — upload images, PDFs, documents, audio to Gemini for conversation context (`gemcli chat -f <file>`, MCP `chat` tool `files` parameter)
- **`gemcli hack claude`** — launch Claude Code connected to Gemini models via local Anthropic-compatible API server

### Fixed
- CDP Chrome startup reliability (polling loop, IPv6 resolution)
- Login profile selection terminal input handling
- FastAPI/uvicorn dependency packaging

---

## [0.2.2] - 2026-02-19

### Added
- **Video generation (Veo 3.1)** — `gemcli video`, MCP `video` tool, polling-based async generation
- **CDP page fetch download** — browser-context `fetch()` for media downloads, bypassing partitioned cookie restrictions

### Fixed
- Media download 403 errors from missing partitioned cookies
- Frame merge now preserves music/video/image data across streaming frames

---

## [0.2.0] - 2026-02-18

### Added
- **Music generation (Lyria 3)** — `gemcli music`, MCP `music` tool, 16 style presets, audio/video formats
- **Persistent Chrome daemon** — `gemcli chrome start/stop/status` for background processes
- **BotGuard for tool-based generation** — music requires BotGuard even on Flash model

---

## [0.1.x] - 2026-02-16

### 0.1.0 — Initial Alpha
Full CLI (`gemcli`) and MCP server (`gemini-web-mcp`) for the Gemini web interface: chat, image generation, deep research, gems management, multi-profile support, skill system, diagnostics (`gemcli doctor`), and MCP client setup for 8+ AI tools.

### 0.1.1 — CI/CD + PyPI
GitHub Actions release workflow (test, build, publish). First PyPI release. Lint fixes.

### 0.1.2 — Dependency Fix
Moved `mcp[cli]` to core dependencies for `uv tool install` compatibility.

### 0.1.3 — Skill Path Fix
Fixed OpenClaw skill installation directory path.

---

[0.5.0]: https://github.com/jacob-bd/gemini-web-mcp-cli/compare/v0.4.9...v0.5.0
[0.4.9]: https://github.com/jacob-bd/gemini-web-mcp-cli/compare/v0.4.8...v0.4.9
[0.4.8]: https://github.com/jacob-bd/gemini-web-mcp-cli/compare/v0.4.7...v0.4.8
[0.4.7]: https://github.com/jacob-bd/gemini-web-mcp-cli/compare/v0.4.6...v0.4.7
[0.4.6]: https://github.com/jacob-bd/gemini-web-mcp-cli/compare/v0.4.4...v0.4.6
[0.4.5]: https://github.com/jacob-bd/gemini-web-mcp-cli/compare/v0.4.4...v0.4.5
[0.4.3]: https://github.com/jacob-bd/gemini-web-mcp-cli/compare/v0.4.2...v0.4.3
[0.4.2]: https://github.com/jacob-bd/gemini-web-mcp-cli/compare/v0.4.1...v0.4.2
[0.4.1]: https://github.com/jacob-bd/gemini-web-mcp-cli/compare/v0.4.0...v0.4.1
[0.4.0]: https://github.com/jacob-bd/gemini-web-mcp-cli/compare/v0.3.34...v0.4.0
[0.3.30]: https://github.com/jacob-bd/gemini-web-mcp-cli/compare/v0.3.29...v0.3.30
[0.3.27]: https://github.com/jacob-bd/gemini-web-mcp-cli/compare/v0.3.26...v0.3.27
[0.3.26]: https://github.com/jacob-bd/gemini-web-mcp-cli/compare/v0.3.25...v0.3.26
[0.3.25]: https://github.com/jacob-bd/gemini-web-mcp-cli/compare/v0.3.24...v0.3.25
[0.3.24]: https://github.com/jacob-bd/gemini-web-mcp-cli/compare/v0.3.23...v0.3.24
[0.3.23]: https://github.com/jacob-bd/gemini-web-mcp-cli/compare/v0.3.22...v0.3.23
[0.3.22]: https://github.com/jacob-bd/gemini-web-mcp-cli/compare/v0.3.21...v0.3.22
[0.3.21]: https://github.com/jacob-bd/gemini-web-mcp-cli/compare/v0.3.20...v0.3.21
[0.3.20]: https://github.com/jacob-bd/gemini-web-mcp-cli/compare/v0.3.19...v0.3.20
[0.3.19]: https://github.com/jacob-bd/gemini-web-mcp-cli/compare/v0.3.18...v0.3.19
[0.3.18]: https://github.com/jacob-bd/gemini-web-mcp-cli/compare/v0.3.17...v0.3.18
[0.3.17]: https://github.com/jacob-bd/gemini-web-mcp-cli/compare/v0.3.16...v0.3.17
[0.3.16]: https://github.com/jacob-bd/gemini-web-mcp-cli/compare/v0.3.15...v0.3.16
[0.3.15]: https://github.com/jacob-bd/gemini-web-mcp-cli/compare/v0.3.14...v0.3.15
[0.3.14]: https://github.com/jacob-bd/gemini-web-mcp-cli/compare/v0.3.13...v0.3.14
