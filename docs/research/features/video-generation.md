# Video Generation (Veo 3.1)

> **Update (2026-09):** The Videos tool is now branded **Gemini Omni**.
> The composer exposes orientation (`inner[55]` = 16 landscape / 17 portrait,
> flag at `inner[0][9]`), a mode picker mirrored in `inner[79]`/`inner[80]`
> (Flash=1, Pro=3, Lite=6; thinking toggle 1/2), and template cards stored at
> `inner[0][9]`. The Token Factory drives these controls in Chrome before
> capture. See `AGENTS.md` and the skill VIDEO_PROMPTING_GUIDE for details.


## Status: IMPLEMENTED ✅

Working as of v0.3.11 (Feb 2026). `gemcli video "..." -o out.mp4`

## Overview

Gemini generates short videos using Google's Veo 3.1 model. Triggered through
the standard StreamGenerate chat endpoint — no separate video RPC exists. The
model decides to generate video based on the prompt content and the presence of
the `at=` access token in the request body.

## Key Findings

### Triggering Veo (Critical)

**`at=` must be present in the request body.** Without it, Gemini routes to
chat/image generation mode and ignores the video intent entirely.

- `at=` must be Chrome's live `SNlM0e` token (extracted from `window.WIZ_global_data`)
- Using Python's cached token fails with HTTP 400 (token/cookie mismatch)
- The Token Factory extracts the live SNlM0e and always includes it as `at=`

**BotGuard token is required** (same as Pro/Thinking models). Without it,
the request is treated as plain chat.

**Prompt must explicitly request a video.** Example: `"Create a short video of..."`
Ambiguous prompts (e.g. `"a cat playing piano"`) may produce an image instead.

### Request Payload

Uses standard StreamGenerate (`inner_req_list`, 70 elements). `tool_id=11`
at `inner[49]` explicitly activates Veo 3.1 routing. Without it, Gemini relies
on prompt heuristics and often generates an image instead of a video.

```
inner[0]  = [prompt, 0, null, null, null, null, 0]
inner[3]  = BotGuard token    — required
inner[4]  = BotGuard hash     — required
inner[49] = 11                — VIDEO_TOOL_ID (activates Veo 3.1)
inner[68] = 2                 — response format flag (always present)
at=<SNlM0e>                   — MUST be present in POST body
```

### Initial Response

The StreamGenerate response immediately acknowledges with a text message:
```
"I'm generating your video. This could take a few minutes, so check
 back to see when your video is ready."
```

And includes a progress placeholder:
```
candidate_data[12][...] = internal chip URL
http://googleusercontent.com/video_gen_chip/0
```

A **conversation ID** is returned in `data[1][0]` — used for polling.

### Polling: hNvQHb RPC

Video generation is **async** — takes 60-90 seconds. Poll using `hNvQHb`
(conversation reload) with browser cookies + Chrome's live `at=` token.

```python
# Poll body via batchexecute:
RPC: hNvQHb
payload: [[conversation_id, null, null], null, "en"]
cookies: Chrome's full cookie set (28 cookies)
at=: Chrome's live SNlM0e token (NOT Python's cached token)
```

Poll every 15 seconds, up to 300 seconds.

### Response Structure (when complete)

When Veo finishes rendering, `candidate[12]` expands to `len=60` and
video data appears at `candidate[12][59]`:

```
candidate[12][59]                    — outer container (list)
candidate[12][59][0]                 — entries array
candidate[12][59][0][0]              — entry: [tracks, metadata, ...]
candidate[12][59][0][0][0]           — tracks array
candidate[12][59][0][0][0][0]        — track data array
candidate[12][59][0][0][0][0][7]     — [preview_url, download_url, preview_url_2]
candidate[12][59][0][0][0][0][7][1]  — download URL ✅
candidate[12][59][0][0][0][0][11]    — "video/mp4"
candidate[12][59][0][0][0][0][17]    — [[duration], width, height]
```

#### Track metadata fields

```
track_data[7][1]    — Download URL (contribution.usercontent.google.com)
track_data[11]      — "video/mp4"
track_data[17]      — [[8, 0], 1280, 720]  (8s duration, 1280x720)
```

#### Final text response

```
candidate[1][0] = "Your video is ready! ..."
```

Also: `candidate[37]` appears when complete (len=2, nested list) — this is
parallel metadata but `candidate[12][59]` is the canonical video data path.

### Download

- **Domain**: `contribution.usercontent.google.com`
- **Auth**: YES — requires full Chrome cookie set (standard cookies alone fail
  due to partitioned cookie store). Use CDP page fetch (`download_via_page_fetch`
  in `core/cdp.py`) which runs `fetch()` from the Gemini page context with
  `credentials: 'include'`.
- **Format**: MP4 (`video/mp4`)
- **Typical size**: ~4-5 MB for an 8-second clip

### Model Info

Observed model reported in response metadata:
```
models/veo-3.1-fast-generate-002;backend_beyond
```

Typical generation stats:
- Duration: 8 seconds
- Resolution: 1280x720
- Generation time: ~60-90 seconds

## Implementation

```
services/video.py       — VideoService.generate() → poll → download
core/client.py          — execute_rpc_with_browser_cookies() for hNvQHb polling
core/cdp.py             — download_via_page_fetch() for authenticated download
```

Key extraction helpers in `services/video.py`:
- `extract_video_url(video_data)` — gets download URL, with recursive fallback scanner
- `extract_video_metadata(video_data)` — model, duration, width, height

## Gotchas

1. **`at=` stripping breaks Veo** — if `at=` is omitted from the body, Gemini
   returns an image or chat response. Always include Chrome's live SNlM0e.
2. **Token mismatch in polling** — using Python's `transport.access_token` for
   `batchexecute` polling returns HTTP 400. Use `_browser_access_token` instead.
3. **tool_id=11 required** — without `inner[49]=11`, Gemini uses prompt heuristics
   and often falls back to image generation. The tool code was discovered from the
   `GemDefaultTool.CREATE_VIDEO` enum (same codes used in Gem default tool picker).
4. **Quota** — Veo generation counts against daily video quota. Test conservatively.
5. **Quota detection** — `wait_for_completion()` now detects quota rejection
   messages (e.g. "Sorry, I can't generate more videos") and raises
   `VideoGenerationError` immediately instead of polling for 5 minutes.
   Use `gemcli limits` or the `limits` MCP tool to check quota before generating.
