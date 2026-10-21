# Chat + Streaming Protocol

## Overview

Chat is the primary interface to Gemini. Messages are sent via the StreamGenerate
endpoint and responses arrive as length-prefixed streaming frames.

## Endpoint

```
POST https://gemini.google.com/_/BardChatUi/data/assistant.lamda.BardFrontendService/StreamGenerate
```

## Query Parameters

| Param | Required | Description |
|-------|----------|-------------|
| `_reqid` | Yes | Random 5-digit integer, incremented by 100000 per request |
| `rt` | Yes | `c` (fixed) |
| `bl` | No | Build label from `cfb2h` |
| `f.sid` | No | Session ID from `FdrFJe` |

## Request Headers

Standard Gemini headers (see known-rpcs.md) plus model-specific header:

```
x-goog-ext-525001261-jspb: [1,null,null,null,"<model_hash>",null,null,0,[4],null,null,1]
```

## Request Body

Form-encoded (`application/x-www-form-urlencoded`):

- `at` = SNlM0e access token
- `f.req` = JSON payload (see below)

### f.req Payload Structure

```python
f_req = json.dumps([None, json.dumps(inner_req_list)])
```

**inner_req_list** is a 69+ element list. Key indices:

| Index | Content | Description |
|-------|---------|-------------|
| `[0]` | `[prompt, 0, None, file_data, None, None, 0]` | Message content + file attachments |
| `[2]` | metadata list (10 elements) | Conversation context for multi-turn |
| `[7]` | `1` | Enable snapshot streaming |
| `[19]` | gem_id or None | Optional Gem (custom system prompt) |

All other indices are `None`.

### File Data Format (index [0][3])

When attaching files:
```python
file_data = [[file_identifier, 1, file_name]]
# file_identifier from upload endpoint, e.g. "/contrib_service/ttl_1d/..."
```

### Metadata (index [2]) - Conversation Context

10-element list for multi-turn conversations:

| Index | Name | Description |
|-------|------|-------------|
| `[0]` | cid | Conversation ID |
| `[1]` | rid | Response ID |
| `[2]` | rcid | Reply candidate ID |
| `[3]`-`[9]` | Various | Additional context (often None) |

For new conversations: all empty strings/None.
For follow-ups: populate from previous response's `part_json[1]`.

## Response Protocol

### Streaming Frame Format

Responses use Google's length-prefixed framing:

```
)]}'

[length]\n[json_payload]\n[length]\n[json_payload]\n...
```

1. Strip `)]}'` prefix
2. For each frame:
   - Read decimal length (UTF-16 code units)
   - Read that many UTF-16 code units of JSON
   - Parse JSON array

### UTF-16 Code Unit Counting

Length uses JavaScript's `String.length` (UTF-16):
- BMP characters (U+0000-U+FFFF): 1 unit
- Supplementary characters (U+10000+): 2 units (surrogate pair)

### Parsed Response Structure

Each frame contains a JSON array. The inner content:

```
frame[0][2] = JSON string (parse again)
```

Parsed inner JSON (`part_json`):

| Path | Content |
|------|---------|
| `part_json[1]` | Metadata (conversation context for next turn) |
| `part_json[4]` | Candidates list |
| `part_json[25]` | Completion indicator |

Per candidate (`candidate_data = part_json[4][i]`):

| Path | Content |
|------|---------|
| `candidate_data[0]` | rcid (reply candidate ID) |
| `candidate_data[1][0]` | Text content (full, not delta) |
| `candidate_data[37][0][0]` | Thought process (for thinking models) |
| `candidate_data[12][1]` | Web images list |
| `candidate_data[12][7][0]` | Generated images list |

### Error Detection

Error code at: `frame[0][5][2][0][1][0]`

## Delta Calculation (for streaming)

Each streaming frame contains the **full text so far**, not incremental deltas.
The client must compute deltas by comparing against the previously sent text.

### Algorithm (fingerprint-based alignment)

1. Remove volatile symbols (whitespace + punctuation) to get "fingerprint length"
2. Find the position in the new text where the fingerprint length matches the old text
3. Adjust for trailing volatile symbols
4. Return everything after that position as the delta

This handles:
- Markdown flicker (backticks appearing/disappearing during streaming)
- Escape character drift
- Whitespace changes between frames

## Multi-Turn Conversations

1. Send first message with empty metadata (`["", "", "", ...]`)
2. Receive response; extract `part_json[1]` as new metadata
3. Send next message with the received metadata in `inner_req_list[2]`
4. Repeat

## Model Selection

Pass the model header alongside standard headers:

```python
headers = {
    **standard_headers,
    "x-goog-ext-525001261-jspb": '[1,null,null,null,"<hash>",null,null,0,[4],null,null,1]'
}
```

Omit the model header to use the default/unspecified model.

## Retry Logic

- 5 retry attempts for generation
- Delay: `(max_retries - current_retry + 1) * 5` seconds (linear backoff)
- Watchdog: If no new content received for `watchdog_timeout` seconds, retry
- On error code 1013 (temporary): Auto-retry
- On error code 1037 (usage limit): Raise, don't retry
- On error code 1050 (model mismatch): Raise, don't retry
