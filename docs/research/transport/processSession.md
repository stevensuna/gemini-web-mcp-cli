# processSession: Gemini's WebChannel chat transport

Measured live on profile `eltanium` on 2026-09-29, build
`boq_assistant-bard-web-server_20260928.08_p0`. Some accounts send chats this
way instead of `StreamGenerate`. Google chooses the transport per account; the
page decides client-side when you press Send.

Raw captures in this folder (cookies, auth hashes, `X-Server-Token`, BotGuard
token and location are redacted):

- `2026-09-29-chrome-exchange.json`: every processSession and batchexecute
  request and response from one Chrome send ("Reply with exactly: ok")
- `2026-09-29-chrome-backchannel.txt`: the response stream from that send
- `2026-09-29-python-replay-backchannel.txt`: the response stream from a Python
  replay ("Reply with exactly: replay ok")

## Summary

- It is a Closure **WebChannel** session to
  `https://geminiweb-pa.clients6.google.com/v1/processSession`, sent from the main
  frame with ordinary `XMLHttpRequest`s. The Token Factory XHR hook missed it only
  because it matches `StreamGenerate` in the URL.
- The request is the **same StreamGenerate `inner` array**, wrapped in a new
  envelope, with the prompt text moved into a separate message.
- **BotGuard is unchanged**: token at `inner[3]`, challenge hash at `inner[4]`.
- **Model selection is unchanged in meaning**: the `x-goog-ext-525001261` header
  is sent as protobuf (`-bin`) instead of JSPB (`-jspb`), inside the channel's
  `$httpHeaders` URL parameter.
- **No `at=` (SNlM0e)**. Auth is `SAPISIDHASH` plus cookies, and an
  `X-Server-Token`, all inside `$httpHeaders`.
- **The response body is StreamGenerate-shaped**: `[1]` ids, `[4]` candidates,
  `[10]` title, `[25]` completion token. The existing candidate parsing applies.
- **Python replay works** (verified 2026-09-29). Chrome builds the setup message
  and its data POST is aborted, so nothing is sent from Chrome. Python then opens
  its own channel with Chrome's cookies, sends the setup message and the real
  prompt, and reads the answer.

## Wire protocol

All requests are `POST`/`GET` to `.../v1/processSession` with
`Origin: https://gemini.google.com`, `Referer: https://gemini.google.com/` and
the Google cookies. Forward-channel POSTs use
`Content-Type: application/x-www-form-urlencoded`.

### 1. Open the channel (POST, body `count=0`)

Query: `VER=8`, `RID=<random int>`, `CVER=22`, `X-HTTP-Session-Id=gsessionid`,
`zx=<random>`, `t=1`, and `$httpHeaders=<CRLF-joined header lines>`:

```
Authorization:SAPISIDHASH <ts>_<sha1> SAPISID1PHASH <ts>_<sha1> SAPISID3PHASH <ts>_<sha1>
X-Goog-AuthUser:0
X-Goog-Api-Key:AIzaSyAPW83vB9zFQqfpMup_cMJdELqDQkWvTho
X-Server-Token:<opaque, from the page>
x-goog-ext-525001261-bin:<base64 protobuf: model selection>
x-goog-ext-73010989-bin:CAA=
x-goog-ext-525005358-bin:<base64 protobuf: {1: session UUID, 2: 1}>
x-goog-ext-73010990-bin:CAAQABgA
X-WebChannel-Content-Type:application/json+protobuf
```

Response header `x-http-session-id: <gsessionid>`. Body (WebChannel frame):
`51\n[[0,["c","<SID>","",8,15,30000]]]\n`.

### 2. Backchannel (GET, streaming)

Query: `gsessionid`, `VER=8`, `RID=rpc`, `SID`, `AID=<last seen array id>`,
`CI=0`, `TYPE=xmlhttp`, `zx`, `t=1`. The response streams frames
`<length>\n<json>`. The length counts UTF-16 code units, like StreamGenerate.
Each frame is `[[arrayId, payload], ...]`.

### 3. Forward messages (POST)

Query: `VER=8`, `gsessionid`, `SID`, `RID=<previous+1>`, `AID=<last seen array
id>`, `zx`, `t=1`. Body: `count=N&ofs=<index of first message>&req0___data__=<json>&...`.
Ack: `8\n[<backchannel present>,<last array id>,7]\n`.

Chrome sends, in order:

| ofs | message | purpose |
|-----|---------|---------|
| 0 | `[[[1, "<model hash>", "en", "<session UUID>"], 0, null, null, null, null, null, [null, null, null, null, [<inner>, null, null, 1]]]]` | setup: model hash + the StreamGenerate `inner` array (prompt blank) |
| 1 | `[null, [1, null, null, null, null, null, null, null, ["<prompt>"]]]` | the prompt text |
| 2 | `[null, null, null, [1]]` | half-close, sent after the final candidate arrives |

Python may send ofs 0 and 1 together (`count=2`). That works.

### 4. Terminate

`POST ...&TYPE=terminate` with no body (`navigator.sendBeacon`).

## The setup message (`inner`)

`inner` (99 elements on 2026-09-29) is the same array as StreamGenerate's
`f.req` inner JSON. It is at `setup[0][7][4][0]`:

- `inner[0] = ["", 0, null, <files>, null, null, 0]`: the prompt is blank here.
  Files use the StreamGenerate format at `inner[0][3]` (verified from a Chrome
  send): `[[[file_id, 3, null, "text/plain"], "note.txt", null x6, [0]]]`
- `inner[1] = ["en"]`, `inner[2]` = conversation ids (null for a new chat)
- `inner[3]` = BotGuard token (`!...`, ~1.5 KB), `inner[4]` = challenge hash
- `inner[59]` (and the envelope UUID) = session UUID, which matches `x-goog-ext-525005358`

## Model header (`x-goog-ext-525001261-bin`)

Protobuf field numbers are the old JSPB array indexes + 1:

| field | value | JSPB equivalent |
|-------|-------|-----------------|
| 1 | 1 | `[0]` |
| 5 | `"56fdd199312815e2"` (model hash) | `[4]` |
| 8 | 0 | `[7]` |
| 9 | packed `[4,5,6,8,16]` | `[8]` |
| 12 | 2 | `[11]` |
| 15 | 1 (model category) | `[14]` (tail first number) |
| 16 | 1 (thinking toggle) | `[15]` (tail second number) |
| 17 | UUID | new |
| 20 | `{1:{1:4,2:948799999}, 2:{1:<unix s>,2:<ns>}}` | new |

Token Factory sets the model through the UI picker, so Chrome builds this
header. Python reuses it as captured.

## Response frames

Each data payload is `[[null, ["<seq>", null, null, null, null, null, [[<flag>,
["<id>"], null, [null, null, null, <body>]]]]]]`. `<body>` is shaped like a
StreamGenerate body.

| seq | contents |
|-----|----------|
| 1 | `body[1] = ["c_<cid>", ""]` |
| 2 | `body[1]` ids, `body[17]` rid, `body[20]` token |
| 3..n | `body[4]` candidates (`rc_...`, text at `[1][0]`), `body[39]` model hash, `body[42]` label ("3.8 Flash") |
| final candidate | `flag = 1`, `body[14] = 1`, `body[63] = 1` |
| next | `body[10] = ["<title>"]` |
| next | `body[25]` completion token (`AwAAAA...`) |

After the client half-closes (ofs 2), the server sends one more seq and then
`[[null, null, null, []]]` (end of stream). Interleaved: `["noop"]` keep-alives
and the initial `[[[]]]`.

## Capturing in Chrome without sending

The existing prototype-level XHR hook works if it also matches processSession:

- let the open POST (URL contains `X-HTTP-Session-Id`) through and record its URL
  (it carries `$httpHeaders`, i.e. auth + model header)
- record and `abort()` every processSession POST whose body contains
  `req0___data__`

Verified: Chrome's URL stays on `/app`, no conversation is created, and capture
completes about 1.3s after Send.

## Binary encoding (switched on for eltanium ~21:00, 2026-09-29)

About an hour after the JSON captures above, the same account's page started
declaring `X-WebChannel-Content-Type: application/x-protobuf` and sending each
forward message as base64 binary protobuf (same endpoint, same page build).
Backchannel frames become `[[aid, ["<base64 protobuf>"]]]`. The page picks the
encoding client-side (`Content-Type = a.ha ? "application/x-protobuf" :
"application/json+protobuf"`); the server still accepts JSON.

gemcli keeps the replayed channel in JSON mode (`use_json_encoding`) and
converts Chrome's binary setup to JSPB (`core/protojspb.py`): protobuf field N
is JSPB index N-1. Bytes alone are ambiguous (0x3d is "=" or the int 61, the 1:1
aspect id), so a type skeleton from JSON captures (`core/setup_shape.py`) says
which fields are strings. Converted chat/image/music/video setups match their
JSON equivalents exactly (`2026-09-29-binary-setup-*.b64` vs
`2026-09-29-streamgenerate-inner-*.json`, BotGuard tokens overwritten). A
field the skeleton does not know and the heuristic gets wrong is rejected by
the server with its name (`Invalid value at '<field>'`): add it to the skeleton
from a fresh JSON capture (StreamGenerate accounts use the same `inner`).

## Follow-ups

Chrome puts the conversation in `inner[71] = ["c_<cid>", null x6, ""]` (not
`inner[2]` as in StreamGenerate), and only when the tab is on `/app/<cid>`
without the `c_` prefix. `webchannel.set_conversation()` fills it if Chrome did
not.

## Verified live (2026-09-29, eltanium)

| Case | Result |
|------|--------|
| Flash chat | ok, ~10s |
| Pro (`-m pro`, header rewritten in Python) | server confirmed `e6fa609c3fa255c0` |
| Text attachment (`inner[0][3]`) | file read correctly |
| Image (Nano Banana 2, and Nano Banana Pro with `-A 1:1`) | image returned and downloaded |
| Extended thinking | correct answer |
| Music (Lyria, short instrumental) | 72s MP3 downloaded |
| Video (Omni, landscape) | 10s 1280x720 MP4 downloaded |
| Image-to-video (`-f` reference image) | reference animated |
| 3 parallel chats on one profile | all succeed, queued by the profile lock |
| Follow-up | same conversation id, context kept |
| `doctor --deep` | capture ok, `chat transport: processSession` |

## Still to measure

- how long `X-Server-Token` and the SAPISIDHASH timestamp stay valid (a fresh
  capture is made per request today)
