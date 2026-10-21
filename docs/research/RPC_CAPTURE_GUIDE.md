# RPC Capture Guide

Standard methodology for discovering and documenting Gemini web interface RPCs.
Use this guide whenever adding support for a new Gemini feature.

The primary capture method uses **Chrome DevTools MCP** — the AI assistant
captures network traffic programmatically while the user triggers the feature
in the browser. No manual copy-paste from DevTools needed.

---

## Quick Reference

| Step | Who | Action |
|------|-----|--------|
| 1 | User | Open `gemini.google.com` in Chrome |
| 2 | AI | Connect via Chrome DevTools MCP, take a snapshot to verify |
| 3 | User | Trigger the feature in the Gemini UI |
| 4 | AI | List network requests, filter for StreamGenerate/batchexecute |
| 5 | AI | Save request + response bodies to files |
| 6 | AI | Decode payload and map response structure |
| 7 | AI | Document findings in `docs/research/features/` |

---

## Prerequisites

The Chrome DevTools MCP server must be connected to the AI session. This gives
the AI assistant access to these tools:

- `list_network_requests` — list all fetch/xhr requests on the page
- `get_network_request` — get full request/response details, save to files
- `take_snapshot` — verify the current page state
- `take_screenshot` — capture visual state for reference
- `list_console_messages` — check for errors
- `click` / `fill` — interact with the page if needed
- `evaluate_script` — run JS to decode payloads in-browser

---

## Capture Workflow

### Step 1: User Opens Chrome

Navigate to `gemini.google.com` and log in. Make sure you're on the page where
the feature is available.

### Step 2: AI Verifies Connection

```
# Verify we can see the page
take_snapshot()

# Check current page URL
list_pages()
```

### Step 3: User Triggers the Feature

The user performs the action in the browser:
- Chat: type a message and send
- Image generation: ask "Generate an image of..."
- Music generation: click "Create music" from the tools menu
- Video generation: ask "Create a video of..."

**Important:** Tell the AI when you've triggered the action so it can capture
the requests immediately.

### Step 4: AI Captures Network Requests

```
# List all fetch/xhr requests since last navigation
list_network_requests(resourceTypes=["fetch", "xhr"])
```

Look for requests matching these URL patterns:

| URL Pattern | Type | Used For |
|-------------|------|----------|
| `StreamGenerate` | POST | All generation (chat, image, video, music, research) |
| `batchexecute` | POST | CRUD operations, polling, metadata queries |
| `upload` | POST | File uploads |

### Step 5: AI Extracts Request/Response Data

For each relevant request, save the full details to files:

```
# Save request and response bodies to files for analysis
get_network_request(
    reqid=<id>,
    requestFilePath="docs/research/captures/feature-request.txt",
    responseFilePath="docs/research/captures/feature-response.txt"
)
```

For async features (video, music, research), capture ALL requests over time:
- The initial StreamGenerate request/response
- Every polling request/response (batchexecute with kwDCne or new RPC ID)
- The final completion response

**Tip:** Use `list_network_requests` repeatedly as polling requests come in.
New requests appear at the end of the list.

### Step 6: AI Decodes and Analyzes

#### StreamGenerate payloads

The request body is form-encoded. Use `evaluate_script` to decode in-browser,
or read the saved request file and decode:

1. URL-decode the `f.req` field
2. Parse as JSON: `[null, "<inner_json_string>"]`
3. Parse the inner JSON string → `inner_req_list` (70-element array)

Key fields in `inner_req_list`:
```
[0]  = [prompt, 0, null, file_data, ...]  — Message + files
[1]  = ["en"]                              — Language
[2]  = [cid, rid, rcid, ...]              — Conversation context (multi-turn)
[7]  = 1                                   — Snapshot streaming flag
[19] = gem_id                              — Custom system prompt (optional)
[30] = [4]                                 — Capabilities array
[59] = UUID                                — Session UUID
[66] = [seconds, nanoseconds]              — Timestamp
[68] = 2                                   — Model tier / response format
```

**Compare against a regular chat request** — any new/changed fields indicate
feature-specific activation.

#### batchexecute payloads

The RPC ID is in the URL query parameter `rpcids` and in the body:
```
f.req = [[ ["<RPC_ID>", "<params_json>", null, "generic"] ]]
```

#### Response parsing

Responses start with `)]}'` anti-XSSI prefix, followed by UTF-16
length-prefixed frames. The AI can use `evaluate_script` to parse in-browser:

```javascript
// Run this in the browser to decode a response
() => {
    // Grab the last StreamGenerate response from performance entries
    const entries = performance.getEntriesByType('resource')
        .filter(e => e.name.includes('StreamGenerate'));
    return entries.map(e => e.name);
}
```

Or parse the saved response file directly — strip the `)]}'` prefix and
decode the length-prefixed frames.

#### Navigating nested arrays

Gemini responses use deeply nested JSON arrays. For each candidate:

```
candidate_data[0]        = rcid (reply candidate ID)
candidate_data[1][0]     = text content
candidate_data[37][0][0] = thought process (Pro/Thinking)
candidate_data[12][1]    = web images
candidate_data[12][7][0] = generated images
candidate_data[12][?]    = NEW FEATURE DATA — look here
```

**Most generated content lives under `candidate_data[12]`** at different
sub-indices. Systematically check each index under `[12]` to find new data.

### Step 7: AI Documents Findings

Create a feature markdown file at `docs/research/features/<feature-name>.md`
using the template below, and update `docs/research/README.md`.

---

## Feature Documentation Template

```markdown
# Feature Name

## Status: CAPTURED / NOT CAPTURED / PARTIAL

## Overview
Brief description of what the feature does.

## RPC Details

### Generation Request
- **Endpoint**: StreamGenerate / batchexecute
- **RPC ID** (if batchexecute): <id>
- **Key payload fields**: Feature-specific fields in inner_req_list

### Polling (if async)
- **RPC ID**: kwDCne (ASYNC_POLL) or <new_id>
- **Poll interval**: <seconds>
- **Completion signal**: <how to detect done>

### Response Structure
- **Text**: candidate_data[1][0]
- **Feature data**: candidate_data[12][X][Y]
- **Download URLs**: candidate_data[12][X][Y][Z]

### Download URLs
- **Domain**: <CDN domain>
- **Auth required**: Yes/No (cookies needed?)
- **Format**: <file format>

## cURL Replay
(sanitized cURL command with placeholder cookies)

## Questions Answered
- Q: Is it triggered via StreamGenerate or separate RPC?
  A: <answer>
- Q: Is it async (start + poll)?
  A: <answer>
- Q: Do download URLs require auth cookies?
  A: <answer>
```

---

## Async Polling Pattern

Many features (video, music, research) use async generation:

1. **Initial request** → StreamGenerate → acknowledgment + conversation metadata
2. **Poll** → batchexecute with `kwDCne` (ASYNC_POLL) → status
3. **Completion** → poll response has `data[0] == True` or contains download URLs
4. **Download** → HTTP GET to CDN URL with auth cookies

When capturing async features, the AI should run `list_network_requests`
repeatedly to catch all polling cycles. Save each response — intermediate
responses may reveal progress indicators.

---

## Capture Tips

### For the AI assistant

1. **Save everything to files** — use `requestFilePath`/`responseFilePath`
   params on `get_network_request` so the data persists for analysis.

2. **Capture timing matters** — for async features, start listing network
   requests immediately after the user triggers the action, and keep checking
   periodically until the generation completes.

3. **Compare with known patterns** — diff the captured `inner_req_list`
   against a regular chat request to isolate feature-specific fields.

4. **Use `evaluate_script`** — run JavaScript in the page to decode
   form-encoded payloads, extract specific response fields, or inspect
   DOM elements that might reveal the feature's structure.

5. **Check console messages** — `list_console_messages` may show errors
   or debug info from the Gemini frontend.

### Common pitfalls

1. **Cookies matter**: Download URLs may need the full cookie set
   (not just auth cookies). If downloads fail, capture ALL cookies.

2. **BotGuard**: Non-Flash models require BotGuard tokens. If replay
   returns Flash instead of expected model, Token Factory is needed.

3. **UTF-16 lengths**: Frame lengths count UTF-16 code units, not bytes.
   Supplementary characters (emoji, CJK) count as 2 units each.

4. **Multiple frames**: A single response may span multiple frames.
   Parse ALL frames and merge — important data may be in the last frame.

5. **Tools activation**: Some features require clicking a "Tools" menu item
   first. Watch for pre-generation RPC calls when activating the tool.

---

## Fallback: Manual Capture

If Chrome DevTools MCP is not available, use manual DevTools:

1. Open Chrome DevTools (`Cmd+Option+I`)
2. Network tab → filter Fetch/XHR → enable Preserve log
3. Trigger the feature in the Gemini UI
4. Right-click request → Copy as cURL
5. Save to a text file for analysis
