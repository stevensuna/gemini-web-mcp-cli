# Music Generation (Lyria 3)

> **Update (2026-09):** Music is now **Lyria 3.5**. The composer adds
> Length/Vocals/Genre dropdowns and template cards; Chrome encodes them in
> `inner[55]` (option ids) and `inner[0][9]` (structured codes). gemcli drives
> them via `--length/-L`, `--vocals/-V`, `--genre/-g`, `--template/-T`.


## Status: CAPTURED ✅ — Fully implemented, working as of v0.3.11

Captured Feb 18, 2026 via Chrome DevTools MCP. Raw captures saved in
`docs/research/captures/music/`.

## Overview

Gemini generates 30-second music tracks using Google DeepMind's Lyria 3 model.
Tracks include vocals, lyrics, instrumentals, and auto-generated cover art
(via Nano Banana). Available to all users 18+ as of Feb 18, 2026.

Users can download the result in two formats:
- **Audio only** — MP3 track
- **Video** — MP4 with cover art visuals

The format choice happens at download time, not generation time.

## Key Finding: NOT Async

Unlike video generation, **music generation is NOT async**. It completes
entirely within a single `StreamGenerate` call. No `kwDCne` polling is needed.
The response streams back progressively in ~16 frames over ~30 seconds.

Streaming progression:
1. Frame 0: Initial ack (rid assigned)
2. Frame 1: Tool invocation (`music_gen`, `generate_music`)
3. Frame 2: "Loading Lyria..."
4. Frame 3: "Generating your track..."
5. Frames 4-5: Tool status updates
6. Frames 6+: Progressive response with text + music data
7. Final frames: Chat title, completion signals

## RPC Details

### Generation Request

- **Endpoint**: `StreamGenerate` (standard chat endpoint)
- **No separate RPC**: Music is triggered via the same StreamGenerate call as chat
- **No tools-activation RPC**: Clicking "Create music" in the UI doesn't send
  a pre-generation RPC — it just sets the tool mode in the request payload

#### Key payload fields (differences from regular chat)

```
inner_req_list[49] = 21    — Music tool activation (not present in normal chat)
inner_req_list[17] = [[0]] — Tool invocation flags
```

All other fields are standard StreamGenerate fields:
```
[0]  = [prompt, 0, null, null, null, null, 0]  — Message
[1]  = ["en"]                                   — Language
[2]  = ["","","", ...]                          — Conversation context (empty = new chat)
[3]  = BotGuard token                           — Required for model auth
[4]  = session hash                             — b1d7a3ce6ec7e6f5...
[7]  = 1                                        — Snapshot streaming
[30] = [4]                                      — Capabilities
[59] = UUID                                     — Session UUID
[66] = [seconds, nanoseconds]                   — Timestamp
[68] = 2                                        — Response format
```

#### Request header (model selection)

```
x-goog-ext-525001261-jspb: [1,null,null,null,"56fdd199312815e2",null,null,0,[4],null,null,2]
```

Model hash `56fdd199312815e2` = Fast. Music currently runs on Flash/Fast model.

### Polling

**NOT NEEDED.** Music generation completes within the StreamGenerate response.
No `kwDCne` or other polling RPC is used.

### Response Structure

Music data lives at **`candidate_data[12][86]`** — an array of 7 entries:

```
candidate_data[12][86][0] = MP3 Audio Track
candidate_data[12][86][1] = MP4 Video Track
candidate_data[12][86][2] = Track Metadata
candidate_data[12][86][3] = Lyrics
candidate_data[12][86][4] = null (reserved)
candidate_data[12][86][5] = Cover Art Info
candidate_data[12][86][6] = Content URI / Tool Label
```

#### Entry 0: MP3 Audio Track

```
Structure: [null, [track_data_array]]
track_data[1]  = 4                    — Type indicator (4 = audio)
track_data[2]  = "pigeon_dynasty.mp3" — Filename
track_data[5]  = "$AedXnj..."        — SynthID watermark signature
track_data[7]  = [                    — URLs array
                    preview_url,       — [0] lh3.googleusercontent.com (thumbnail/preview)
                    download_url,      — [1] contribution.usercontent.google.com (actual download)
                    preview_url_2      — [2] same as [0]
                  ]
track_data[8]  = 2                    — URL type flag
track_data[9]  = [seconds, nanos]     — Generation timestamp
track_data[11] = "audio/mpeg"         — MIME type
track_data[16] = [[]]                 — Empty metadata
```

#### Entry 1: MP4 Video Track

```
Structure: [null, [track_data_array]]
track_data[1]  = 2                    — Type indicator (2 = video)
track_data[2]  = "pigeon_dynasty.mp4" — Filename
track_data[5]  = "$AedXnj..."        — SynthID watermark signature
track_data[7]  = [                    — URLs array (same pattern as audio)
                    preview_url,       — [0] lh3.googleusercontent.com
                    download_url,      — [1] contribution.usercontent.google.com
                    preview_url_2      — [2] same as [0]
                  ]
track_data[8]  = 2                    — URL type flag
track_data[9]  = [seconds, nanos]     — Generation timestamp
track_data[11] = "video/mp4"          — MIME type
track_data[17] = [[30, 766000000],    — Duration: 30.766 seconds
                  720,                 — Width (pixels)
                  720]                 — Height (pixels)
```

#### Entry 2: Track Metadata

```
[
  "Pigeon Dynasty",           — [0] Track title
  null,                        — [1] (unused)
  "Urban Aviary Anthems",      — [2] Album name
  null,                        — [3] (unused)
  "Comedy Rap",                — [4] Genre
  ["Playful", "Energetic",    — [5] Mood tags
   "Absurdist"]
]
```

#### Entry 3: Lyrics

```
[
  null,                         — [0]
  null,                         — [1]
  "[0.0:] Yo, let's talk...",   — [2] Timestamped lyrics (full text with timestamps)
  "Caption: This track is...",  — [3] Music analysis/description caption
  false                         — [4] has_lyrics flag (bool)
]
```

Timestamp format in lyrics: `[seconds.fraction:] lyric text`

#### Entry 5: Cover Art Info

```
[
  1,                            — [0] Flag
  null,                         — [1]
  "The image depicts..."        — [2] Safety review / alt-text description
]
```

#### Entry 6: Content URI / Tool Label

```
[
  "http://googleusercontent.com/generated_music_content/0",  — [0] Internal content URI
  null, null, null, null, null,
  ["Music",                     — [6][0] Tool display name
   "https://...gemini/.../192px.svg",  — [6][1] Tool icon URL
   null,
   "music_gen"]                 — [6][3] Tool ID
]
```

#### VTT Subtitles (also present in raw response)

A VTT (WebVTT) subtitle file is also generated:
```
track_data[1]  = 3                    — Type indicator (3 = subtitle)
track_data[2]  = "pigeon_dynasty.vtt" — Filename
track_data[7]  = ["", download_url, ""] — URLs (download at [1])
track_data[11] = "text/vtt"           — MIME type
```

### Download URLs

- **Domain**: `contribution.usercontent.google.com`
- **Pattern**: `/download?c=<token>&filename=<name>&opi=103135050`
- **Method**: Simple GET request (no RPC needed)
- **Auth required**: Yes — requires full cookie set from the browser session
- **Audio format**: MP3 (`audio/mpeg`)
- **Video format**: MP4 (`video/mp4`, 720x720, ~30 seconds)
- **Subtitles**: VTT (`text/vtt`)
- **URLs are temporary**: Signed with token, likely expire after some time

### Download URL Extraction

```
Audio MP3:  candidate_data[12][86][0][1][7][1]
Video MP4:  candidate_data[12][86][1][1][7][1]
VTT subs:   (look for entry with track_data[11] == "text/vtt")
```

## Text Response

The text response (`candidate_data[1][0]`) contains a brief message like:
> "I've created a funny comedy rap song about birds for you! You can play it
> right here in our chat."

## Conversation Metadata

Standard metadata returned:
```
data[1][0] = "c_af2bdac9adb62456"  — Conversation ID
data[1][1] = "r_4143483a1a6ace40"  — Response ID
```

Candidate ID:
```
candidate_data[0] = "rc_b38ff605fc2de5d1"  — Reply candidate ID
```

## Captured Files

| File | Description |
|------|-------------|
| `captures/music/streamgenerate-request.txt` | Full StreamGenerate request body |
| `captures/music/streamgenerate-response.txt` | Full StreamGenerate response (16 frames) |
| `captures/music/L5adhe-poll-request.txt` | L5adhe RPC request (unrelated to music) |
| `captures/music/L5adhe-poll-response-1.txt` | L5adhe response |
| `captures/music/L5adhe-poll-response-last.txt` | L5adhe response |
| `captures/music/PCck7e-request.txt` | PCck7e RPC request (post-generation) |
| `captures/music/PCck7e-response.txt` | PCck7e response |

## Questions Answered

- **Q: Is it triggered via StreamGenerate or separate RPC?**
  A: StreamGenerate — same endpoint as regular chat.

- **Q: What activates music mode?**
  A: `inner_req_list[49] = 21` activates the music tool.

- **Q: Is it async (start + poll)?**
  A: **NO.** Music completes within the StreamGenerate response. No polling needed.

- **Q: Where does music data live in the response?**
  A: `candidate_data[12][86]` — array of 7 entries (MP3, MP4, metadata, lyrics, etc.)

- **Q: Do download URLs require auth cookies?**
  A: Yes, full cookie set required for `contribution.usercontent.google.com`.

- **Q: Is there track metadata?**
  A: Yes — title, album name, genre, mood tags at `candidate_data[12][86][2]`.

- **Q: Are lyrics included?**
  A: Yes — timestamped lyrics at `candidate_data[12][86][3][2]`, plus a VTT subtitle file.

## Known Issues & Fixes

### HTTP 400 on music generation (fixed v0.3.11)

**Symptom**: `MusicGenerationError: HTTP 400` on `StreamGenerate`.

**Root cause**: The `at=` parameter in the request body was either missing or
set to Python's cached `transport.access_token`, which doesn't match the
session credentials in Chrome's cookies. Gemini validates `at=` against the
live cookie set — a mismatch returns 400.

**Fix**: Token Factory now always extracts Chrome's live `SNlM0e` token from
`window.WIZ_global_data` and uses it as `at=`. Never omit or substitute it.
