# HanaokaYuzu/Gemini-API: Chat & Streaming Implementation Analysis

This document provides a complete analysis of the chat and streaming implementation from the [HanaokaYuzu/Gemini-API](https://github.com/HanaokaYuzu/Gemini-API) Python library (reverse-engineered Gemini web interface).

**Branch:** `master`  
**Base URL:** `https://raw.githubusercontent.com/HanaokaYuzu/Gemini-API/master/`

---

## 1. Complete Source Code

### 1.1 client.py (Complete)

```python
import asyncio
import codecs
import io
import time
import random
import re
from asyncio import Task
from pathlib import Path
from typing import Any, AsyncGenerator, Optional

import orjson as json
from httpx import AsyncClient, Cookies, ReadTimeout, Response

from .components import GemMixin
from .constants import Endpoint, ErrorCode, GRPC, Headers, Model
from .exceptions import (
    APIError,
    AuthError,
    GeminiError,
    ModelInvalid,
    TemporarilyBlocked,
    TimeoutError,
    UsageLimitExceeded,
)
from .types import (
    Candidate,
    Gem,
    GeneratedImage,
    ModelOutput,
    RPCData,
    WebImage,
)
from .utils import (
    get_access_token,
    get_delta_by_fp_len,
    get_nested_value,
    logger,
    parse_file_name,
    parse_response_by_frame,
    rotate_1psidts,
    running,
    upload_file,
)


class GeminiClient(GemMixin):
    # ... init, init(), close(), reset_close_task(), start_auto_refresh() ...
    # ... generate_content(), generate_content_stream(), _generate() ...
    # ... start_chat(), delete_chat(), _batch_execute() ...
```

Key methods covered in detail below.

### 1.2 decorators.py (Complete)

```python
import asyncio
import functools
import inspect
from collections.abc import Callable

from ..exceptions import APIError


DELAY_FACTOR = 5


def running(retry: int = 0) -> Callable:
    """
    Decorator to check if GeminiClient is running before making a request.
    Supports both regular async functions and async generators.
    """
    def decorator(func):
        if inspect.isasyncgenfunction(func):

            @functools.wraps(func)
            async def wrapper(client, *args, current_retry=None, **kwargs):
                if current_retry is None:
                    current_retry = retry

                try:
                    if not client._running:
                        await client.init(
                            timeout=client.timeout,
                            auto_close=client.auto_close,
                            close_delay=client.close_delay,
                            auto_refresh=client.auto_refresh,
                            refresh_interval=client.refresh_interval,
                            verbose=client.verbose,
                            watchdog_timeout=client.watchdog_timeout,
                        )

                    if not client._running:
                        raise APIError(
                            f"Invalid function call: GeminiClient.{func.__name__}. Client initialization failed."
                        )

                    async for item in func(client, *args, **kwargs):
                        yield item
                except APIError:
                    if current_retry > 0:
                        delay = (retry - current_retry + 1) * DELAY_FACTOR
                        await asyncio.sleep(delay)
                        async for item in wrapper(
                            client, *args, current_retry=current_retry - 1, **kwargs
                        ):
                            yield item
                    else:
                        raise

            return wrapper
        else:

            @functools.wraps(func)
            async def wrapper(client, *args, current_retry=None, **kwargs):
                if current_retry is None:
                    current_retry = retry

                try:
                    if not client._running:
                        await client.init(...)

                    if not client._running:
                        raise APIError(...)

                    return await func(client, *args, **kwargs)
                except APIError:
                    if current_retry > 0:
                        delay = (retry - current_retry + 1) * DELAY_FACTOR
                        await asyncio.sleep(delay)
                        return await wrapper(
                            client, *args, current_retry=current_retry - 1, **kwargs
                        )
                    raise

            return wrapper

    return decorator
```

### 1.3 parsing.py (Delta & Frame Functions)

```python
# Delta calculation
def get_delta_by_fp_len(new_raw: str, last_sent_clean: str, is_final: bool) -> tuple[str, str]:
    """Calculate text delta by aligning stable content and matching volatile symbols."""
    # ... see detailed algorithm below

# Frame parsing
def parse_response_by_frame(content: str) -> tuple[list[Any], str]:
    """Parse Google's length-prefixed framing protocol."""
    # ... see detailed protocol below
```

---

## 2. Request Payload Structure

### 2.1 StreamGenerate Endpoint

- **URL:** `https://gemini.google.com/_/BardChatUi/data/assistant.lamda.BardFrontendService/StreamGenerate`
- **Method:** POST
- **Content-Type:** `application/x-www-form-urlencoded;charset=utf-8`

### 2.2 Query Parameters

```python
params = {
    "_reqid": _reqid,          # Random 5-digit + 100000 increment per request
    "rt": "c",
    "bl": self.build_label,    # From get_access_token, optional
    "f.sid": self.session_id,  # From get_access_token, optional
}
```

### 2.3 Request Body (`f.req`)

The `f.req` field is a **double-JSON-encoded** string:

```python
request_data = {
    "at": self.access_token,   # SNlM0e token from page
    "f.req": json.dumps([
        None,
        json.dumps(inner_req_list).decode("utf-8"),  # Inner list as string
    ]).decode("utf-8"),
}
```

### 2.4 Inner Request List Structure (69 elements)

```python
inner_req_list = [None] * 69

# Index 0: Message content
inner_req_list[0] = [
    prompt,           # User prompt string
    0,
    None,
    req_file_data,    # [[[url], filename], ...] or None
    None,
    None,
    0,
]

# Index 2: Conversation metadata (REQUIRED for multi-turn)
inner_req_list[2] = chat.metadata if chat else ["", "", "", None, None, None, None, None, None, ""]
# New chat: 10 elements, all empty/None
# Continuing chat: [cid, rid, rcid, ...] from previous response

# Index 7: Snapshot streaming flag
inner_req_list[7] = 1  # Enable Snapshot Streaming

# Index 19: Gem ID (system prompt)
inner_req_list[19] = gem_id  # Optional, e.g. "9d8ca3786ebdfbea"
```

### 2.5 Message Content Format (with files)

```python
message_content = [
    prompt,        # str
    0,
    None,
    req_file_data,  # list of [[[url], filename], ...]
    None,
    None,
    0,
]

# req_file_data example:
# [
#     [["https://content-push.googleapis.com/..."], "image.png"],
#     [["https://content-push.googleapis.com/..."], "document.pdf"],
# ]
```

### 2.6 File Upload Integration

1. **Upload:** Each file is POSTed to `https://content-push.googleapis.com/upload` with `Push-ID: feeds/mcudyrk2a4khkz`. Response body is the file identifier URL.
2. **Format:** `[[[url], filename], ...]` — list of `[url_list, filename]`.
3. **Before sending:** `_batch_execute` with `BARD_ACTIVITY` RPC is called twice (before and after uploads) to enable `bard_activity_enabled`.

---

## 3. Model Selection (x-goog-ext Header)

Models are selected via the `x-goog-ext-525001261-jspb` header (JSPB-encoded JSON):

```python
# constants.py
class Model(Enum):
    UNSPECIFIED = ("unspecified", {}, False)
    G_3_0_PRO = (
        "gemini-3.0-pro",
        {"x-goog-ext-525001261-jspb": '[1,null,null,null,"9d8ca3786ebdfbea",null,null,0,[4],null,null,1]'},
        False,
    )
    G_3_0_FLASH = (
        "gemini-3.0-flash",
        {"x-goog-ext-525001261-jspb": '[1,null,null,null,"fbb127bbb056c959",null,null,0,[4],null,null,1]'},
        False,
    )
    G_3_0_FLASH_THINKING = (
        "gemini-3.0-flash-thinking",
        {"x-goog-ext-525001261-jspb": '[1,null,null,null,"5bf011840784117a",null,null,0,[4],null,null,1]'},
        False,
    )
```

- **Index 4** of the JSPB array is the model identifier (hex string).
- Custom models: pass `{"model_name": "...", "model_header": {"x-goog-ext-525001261-jspb": "..."}}`.

---

## 4. Conversation State (Metadata)

### 4.1 Metadata Structure

Metadata is a **10-element list**:

```python
# New session
metadata = ["", "", "", None, None, None, None, None, None, ""]

# After first response (from part_json[1])
metadata = [cid, rid, rcid, ...]  # Server provides full list
```

- **cid** (index 0): Chat ID (e.g. `"c_..."`)
- **rid** (index 1): Reply ID
- **rcid** (index 2): Reply candidate ID

### 4.2 When Metadata Is Updated

1. **During streaming:** `chat.metadata = m_data` when `part_json[1]` is present.
2. **On completion:** `chat.metadata = [None] * 9 + [context_str]` when `part_json[25]` is a string (context).
3. **On last_output:** When `chat.last_output` is set, `metadata` and `rcid` are taken from `ModelOutput`.

### 4.3 ChatSession Internal State

```python
class ChatSession:
    __metadata: list  # [cid, rid, rcid, ...] (10 elements)
    geminiclient: GeminiClient
    last_output: ModelOutput | None
    model, gem

    # Properties: cid=__metadata[0], rid=__metadata[1], rcid=__metadata[2]
```

### 4.4 Multi-Turn Flow

1. **First turn:** `inner_req_list[2] = ["", "", "", None, None, None, None, None, None, ""]`
2. **Server response:** Returns `part_json[1]` with `[cid, rid, rcid, ...]`
3. **Next turn:** `inner_req_list[2] = chat.metadata` (from previous response)
4. **Result:** Conversation history is restored via metadata.

---

## 5. Streaming Protocol

### 5.1 Response Format

1. **Prefix:** Responses may start with `)]}'` (XSSI guard).
2. **Framing:** Google length-prefixed framing: `[length]\n[json_payload]\n`
3. **Length:** UTF-16 code units (JavaScript `String.length`), not bytes.

### 5.2 Frame Parsing Algorithm (`parse_response_by_frame`)

```
1. Strip leading whitespace
2. Match _LENGTH_MARKER_PATTERN: (\d+)\n
3. length = parsed integer (UTF-16 units)
4. Compute char_count for that many UTF-16 units from start_content
5. If units_found < length → incomplete frame, keep in buffer
6. Extract chunk = content[start_content:end_pos].strip()
7. Parse as JSON, extend parsed_frames
8. Return (parsed_frames, remainder)
```

**UTF-16 handling:** Characters with `ord(c) > 0xFFFF` count as 2 units.

### 5.3 Response Part Structure

Each parsed frame is a list of **envelope parts**. For each part:

- **Error code:** `part[5][2][0][1][0]`
- **Inner JSON string:** `part[2]` → parse to get `part_json`

### 5.4 Part JSON Structure

```python
part_json = json.loads(inner_json_str)

# Key paths:
m_data     = part_json[1]      # Metadata [cid, rid, rcid, ...]
context_str = part_json[25]   # Completion context (string when done)
candidates = part_json[4]     # List of candidate objects
```

### 5.5 Candidate Object Structure

```python
candidate_data = candidates_list[i]

rcid    = candidate_data[0]           # Reply candidate ID
text    = candidate_data[1][0]       # Main text (use [22][0] if card_content URL)
thoughts = candidate_data[37][0][0]  # Thinking chain (thinking models)

# Web images
for web_img in candidate_data[12][1]:
    url = web_img[0][0][0]
    title = web_img[7][0]
    alt = web_img[0][4]

# Generated images
for gen_img in candidate_data[12][7][0]:
    url = gen_img[0][3][3]
    img_num = gen_img[3][6]
    alt = gen_img[3][5][0]

# Final chunk detection
is_final = isinstance(candidate_data[2], list) or candidate_data[8][0] == 2
```

### 5.6 Text Cleanup

- Replace `http://googleusercontent.com/card_content/\d+` with `candidate_data[22][0]`.
- Remove `http://googleusercontent.com/\w+/\d+\n*` patterns.

---

## 6. Delta Calculation Algorithm

### 6.1 Purpose

Streaming sends **full accumulated text** in each frame, not deltas. The client must compute the **new** text since the last frame to avoid duplicates and handle:
- Markdown/code-block flicker
- Temporary escaping (`\`*` etc.)
- Volatile characters (whitespace, punctuation)

### 6.2 Algorithm (`get_delta_by_fp_len`)

**Inputs:**
- `new_raw`: Latest full text from server
- `last_sent_clean`: Last text we “sent” (after cleanup)
- `is_final`: Whether this is the final chunk

**Output:** `(delta, new_full_text)` — new characters and updated full text for next round.

**Steps:**

1. **Clean new text (unless final):**
   ```python
   new_c = get_clean_text(new_raw) if not is_final else new_raw
   ```
   - Remove trailing `\n````
   - Remove `_FLICKER_ESC_RE`: `\\+[`*_~].*$`

2. **Fast path (prefix match):**
   ```python
   if new_c.startswith(last_sent_clean):
       return new_c[len(last_sent_clean):], new_c
   ```

3. **Fingerprint length (fp_len):**
   - `get_fp_len(s)` = length after removing whitespace + punctuation
   - Used to align on “stable” content

4. **Find alignment point `p_low`:**
   - If `target_fp_len > 0`: scan `new_c`, count non-volatile chars until `curr_fp_len == target_fp_len` → `p_low = i + 1`
   - Else: use simple char-by-char prefix match

5. **Suffix matching:**
   - `suffix` = chars after last non-volatile char in `last_sent_clean`
   - Match `suffix` against `new_c[p_low:]`, handling `\` escapes
   - Advance `j` past matched portion

6. **Return:**
   ```python
   return new_c[p_low + j:], new_c
   ```

### 6.3 Volatile Symbols

```python
_VOLATILE_SYMBOLS = string.whitespace + string.punctuation
```

These are ignored when aligning by fingerprint length to reduce drift from escaping and formatting changes.

---

## 7. Streaming Processing Flow

### 7.1 Main Loop

```python
buffer = ""
decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")

async for chunk in response.aiter_bytes():
    buffer += decoder.decode(chunk, final=False)
    if buffer.startswith(")]}'"):
        buffer = buffer[4:].lstrip()
    parsed_parts, buffer = parse_response_by_frame(buffer)

    got_update = False
    async for out in _process_parts(parsed_parts):
        yield out
        got_update = True

    if got_update or is_thinking:
        last_progress_time = time.time()
        session_state["last_progress_time"] = last_progress_time
    else:
        if (time.time() - last_progress_time) > stall_threshold:
            raise APIError("Response stalled (zombie stream).")

# Final flush
buffer += decoder.decode(b"", final=True)
if buffer:
    parsed_parts, _ = parse_response_by_frame(buffer)
    async for out in _process_parts(parsed_parts):
        yield out
```

### 7.2 Session State (for retries)

```python
session_state = {
    "last_texts": {},      # {rcid: last_full_text, "idx_i": last_full_text}
    "last_thoughts": {},   # Same for thoughts
    "last_progress_time": time.time(),
}
```

`session_state` is passed into `_generate` and updated during streaming so retries can resume from the correct position.

### 7.3 Completion Conditions

Stream is considered complete when:
- `part_json[25]` is a string (context_str), OR
- `is_final_chunk` is true for a candidate

If not, the code raises `APIError("Stream interrupted or truncated.")` to trigger a retry.

---

## 8. Error Handling

### 8.1 Error Code Path

`part[5][2][0][1][0]` contains error codes:

| Code | Error |
|------|-------|
| 1037 | UsageLimitExceeded |
| 1050 | ModelInvalid (inconsistent) |
| 1052 | ModelInvalid (header invalid) |
| 1060 | TemporarilyBlocked (IP) |
| 1013 | Temporary (retry) |

### 8.2 Retry Decorator Logic

- **`@running(retry=5)`** on `_generate`, **`retry=2`** on `_batch_execute`
- On `APIError`: sleep `(retry - current_retry + 1) * DELAY_FACTOR` seconds, then retry
- `DELAY_FACTOR = 5` → delays: 5, 10, 15, 20, 25 seconds
- **Watchdog:** If no update for `watchdog_timeout` seconds while connection is open, raise `APIError("Response stalled (zombie stream).")` to trigger retry

---

## 9. Image Extraction

### 9.1 Web Images (search results)

- Path: `candidate_data[12][1]`
- URL: `web_img[0][0][0]`
- Title: `web_img[7][0]`
- Alt: `web_img[0][4]`

### 9.2 Generated Images

- Path: `candidate_data[12][7][0]`
- URL: `gen_img[0][3][3]`
- Alt: `gen_img[3][5][0]`
- `GeneratedImage` uses proxy + cookies for fetch

---

## 10. Constants Reference

```python
# Endpoints
Endpoint.GENERATE = "https://gemini.google.com/_/BardChatUi/data/assistant.lamda.BardFrontendService/StreamGenerate"
Endpoint.BATCH_EXEC = "https://gemini.google.com/_/BardChatUi/data/batchexecute"
Endpoint.UPLOAD = "https://content-push.googleapis.com/upload"

# RPC IDs
GRPC.BARD_ACTIVITY = "ESY5D"
GRPC.DELETE_CHAT = "GzXR5e"
```

---

## 11. Summary: Rebuilding Chat from Scratch

To reimplement chat/streaming:

1. **Auth:** `__Secure-1PSID`, `__Secure-1PSIDTS`, SNlM0e access token, `build_label`, `session_id`
2. **Request:** POST to StreamGenerate with `f.req` = double-JSON-encoded `[None, json.dumps(inner_req_list)]`
3. **Inner list:** `[0]=message_content`, `[2]=metadata`, `[7]=1`, `[19]=gem_id` (optional)
4. **Metadata:** 10-element list `[cid, rid, rcid, ...]` — start with empties, then use server-provided values for follow-ups
5. **Streaming:** Parse `)]}'` + length-prefixed frames (UTF-16), extract `part[2]` and parse as JSON
6. **Delta:** Use `get_delta_by_fp_len` on full text to compute new text; track `last_texts` per `rcid`
7. **Retry:** Exponential backoff on APIError, watchdog on stalls
8. **Model:** Set `x-goog-ext-525001261-jspb` per model
9. **Files:** Upload to content-push URL, then `[[[url], filename], ...]` in message_content
