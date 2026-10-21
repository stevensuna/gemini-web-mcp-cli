# Known RPC Reference

## Endpoints

| Name | URL | Method | Purpose |
|------|-----|--------|---------|
| INIT | `https://gemini.google.com/app` | GET | Init page, extract tokens |
| GENERATE | `https://gemini.google.com/_/BardChatUi/data/assistant.lamda.BardFrontendService/StreamGenerate` | POST | Streaming chat generation |
| BATCH_EXEC | `https://gemini.google.com/_/BardChatUi/data/batchexecute` | POST | Batch RPC execution |
| UPLOAD | `https://push.clients6.google.com/upload/` | POST | File upload (resumable) |
| ROTATE_COOKIES | `https://accounts.google.com/RotateCookies` | POST | Refresh __Secure-1PSIDTS |
| GOOGLE | `https://www.google.com` | GET | Pre-fetch cookies |

## RPC IDs (batchexecute)

| RPC ID | Constant | Purpose | Payload Example |
|--------|----------|---------|-----------------|
| `MaZiqc` | LIST_CHATS | List all chat conversations | `[]` |
| `hNvQHb` | READ_CHAT | Read a specific chat | `[chat_id]` |
| `GzXR5e` | DELETE_CHAT | Delete a chat conversation | `[chat_id]` |
| `CNgdBe` | LIST_GEMS | List gems (system + custom) | `[null, 0]` (system) / `[null, 1]` (custom) |
| `oMH3Zd` | CREATE_GEM | Create a custom gem | `[name, description, prompt, ...]` |
| `kHv0Vd` | UPDATE_GEM | Update an existing gem | `[gem_id, [name, description, prompt, ...]]` |
| `UXcSJb` | DELETE_GEM | Delete a custom gem | `[gem_id]` |
| `ESY5D` | BARD_ACTIVITY | Enable Bard activity | `[1]` |
| `aPya6c` | STATUS_POLL | Status polling | TBD |
| `kwDCne` | ASYNC_POLL | Deep Research / video gen progress | `[cid, ...]` |
| `PCck7e` | POST_PROCESS | Post-processing | TBD |
| `qpEbW` | USAGE_INFO | Per-feature usage limits (browser cookies required) | `[]` |

## Tool Activation (inner_req_list[49])

| Tool | ID | Description |
|------|----|-------------|
| Music (Lyria 3) | 21 | Activates music generation mode in StreamGenerate |

## Music Style Presets (inner[0][9][6])

When using a remix style preset, `inner[0]` is extended from 7 to 10 elements. The preset data is placed at `inner[0][9]` as a "file attachment" structure:

```
inner[0][9] = [
    null, null, null, null, null, null,
    [null, null, [], preset_id, [preset_id, name, [[image_url, 1], [audio_url, 3]], system_prompt]]
]
```

16 presets captured from live Gemini UI (Feb 2026):

| Preset | ID | Description |
|--------|----|-------------|
| 90's rap | 7SAXCf75CToiwWi | East Coast boom bap, golden age hip hop |
| Latin pop | 7GRty74JGzGRHRA | Modern Latin pop, alt-reggaeton |
| Folk ballad | AwRCEdJqEyXWXbB | Contemporary indie folk, acoustic singer-songwriter |
| 8-bit | 5YcQ7ninNzGzST8 | Chiptune, 8-bit gaming soundtrack |
| Workout | 48cmHB66Mu2UTWu | High-octane EDM, workout motivation |
| Reggaeton | xtzZQGYDaQfivzP | Modern reggaeton, neoperreo |
| R&B romance | 9ccBNEUfLMWL3tq | Comical romantic R&B slow jam |
| Kawaii metal | B8Ex4U4GdEoD2oR | J-Pop / metalcore fusion |
| Cinematic | eZcEiADTSQPTw48 | Orchestral cinematic score |
| Emo | 35PvCx4QmjYKs3i | Midwest emo, math rock, post-hardcore |
| Afropop | A6PiNVTzfyqf2WC | Melodic afro-pop, contemporary highlife |
| Forest bath | AtyAtQ8jwjm5GKb | Ambient soundscape with nature sounds |
| K-pop | 4xsPHm5U3apV59Z | Modern K-pop with Korean/English |
| Birthday roast | 74LvchoZaKQ22jq | Country song gently roasting someone |
| Folk a cappella | 32oyidk5mmTG8Ro | Appalachian a cappella, three-part harmony |
| Bad music | BNvHQbhDZNpRuYx | Experimental glitch-comedy, intentionally awful |

## RPCs To Capture

| Feature | Expected RPC ID | Status |
|---------|----------------|--------|
| Image Generation (Imagen) | StreamGenerate (tool_id=14) | **Implemented** (Feb 2026) |
| Music Generation (Lyria 3) | StreamGenerate (tool_id=21) | **Captured** (Feb 18, 2026) |
| Video Generation (Veo 3.1) | StreamGenerate (tool_id=11) | **Implemented** (Feb 2026) |
| Deep Research | TBD | Not captured |
| Canvas operations | TBD | Not captured |
| Code Execution | TBD | Not captured |

## Model Hashes

Model selection uses the `x-goog-ext-525001261-jspb` header:

```
[1,null,null,null,"<model_hash>",null,null,0,[4],null,null,1]
```

| Model | Hash | Name |
|-------|------|------|
| Gemini 3.0 Pro | `9d8ca3786ebdfbea` | `gemini-3.0-pro` |
| Gemini 3.0 Flash | `fbb127bbb056c959` | `gemini-3.0-flash` |
| Gemini 3.0 Flash Thinking | `5bf011840784117a` | `gemini-3.0-flash-thinking` |

Custom models: Provide `model_name` and `model_header` dict with the same header key.

## Error Codes

Returned in response at path `part[5][2][0][1][0]`:

| Code | Name | Description | Action |
|------|------|-------------|--------|
| 1013 | TEMPORARY_ERROR | Randomly raised with certain models | Retry (transient) |
| 1037 | USAGE_LIMIT_EXCEEDED | Usage limit hit | Back off, wait |
| 1050 | MODEL_INCONSISTENT | Model mismatch with conversation | Use correct model or new conversation |
| 1052 | MODEL_HEADER_INVALID | Model unavailable or bad header | Check model hash |
| 1060 | IP_TEMPORARILY_BLOCKED | IP blocked by Google | Wait, change IP |

## Request Headers

### Standard Headers (all requests to gemini.google.com)

```
Content-Type: application/x-www-form-urlencoded;charset=utf-8
Host: gemini.google.com
Origin: https://gemini.google.com
Referer: https://gemini.google.com/
User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36
X-Same-Domain: 1
```

### RotateCookies Headers

```
Content-Type: application/json
```

### File Upload Headers

```
Push-ID: feeds/mcudyrk2a4khkz
```

## batchexecute Request Format

**URL**: `POST {BATCH_EXEC}?rpcids={ids}&_reqid={reqid}&rt=c&source-path=/app&bl={build_label}&f.sid={session_id}`

**Body** (form-encoded):
- `at` = SNlM0e access token
- `f.req` = `json.dumps([[ [rpc_id, payload_json, null, "generic"], ... ]])`

**_reqid**: Random 5-digit integer, incremented by 100000 between batches.

## StreamGenerate Request Format

**URL**: `POST {GENERATE}?_reqid={reqid}&rt=c&bl={build_label}&f.sid={session_id}`

**Body** (form-encoded):
- `at` = SNlM0e access token
- `f.req` = `json.dumps([null, json.dumps(inner_req_list)])`

**inner_req_list** (69+ elements):
- `[0]` = `[prompt, 0, null, file_data, null, null, 0]` (7 elements)
  - With music style preset: extended to 10 elements, `[0][9]` = preset file data
- `[2]` = metadata (10-element list: `[cid, rid, rcid, ...]` for multi-turn)
- `[7]` = `1` (snapshot streaming)
- `[19]` = gem_id (optional)
- `[49]` = tool_id (optional: 11=video, 14=image, 21=music)

## Response Parsing Protocol

### Frame Format (streaming)

Length-prefixed frames: `[length]\n[json_payload]\n`

- Length is in **UTF-16 code units** (JavaScript `String.length`)
- BMP chars (U+0000-U+FFFF) = 1 unit; supplementary (U+10000+) = 2 units
- Strip `)]}'` prefix before parsing

### Response Structure

For each parsed frame/part:
- `part[2]` = inner JSON (parse again)
- `part_json[1]` = metadata (conversation context: cid, rid, rcid, ...)
- `part_json[4]` = candidates list
- `part_json[25]` = completion indicator
- Per candidate:
  - `candidate_data[0]` = rcid
  - `candidate_data[1][0]` = text content
  - `candidate_data[37][0][0]` = thought process
  - `candidate_data[12][1]` = web images
  - `candidate_data[12][7][0]` = generated images
  - `candidate_data[12][86]` = generated music (7-entry array: MP3, MP4, metadata, lyrics, null, cover art, content URI)
- Error: `part[5][2][0][1][0]` = error code
