# PromptEscaped transport repair

## Status

Investigation complete; patch and live verification pending. Local maintenance
branch: `fix/prompt-escaped-transport`. This is a local patch to 0.9.7, not an
upstream release. The requested checkout installation takes precedence over
CLAUDE.md's upstream publication procedure. No release tag or main merge is planned.

## Root cause and wire evidence

A single controlled chat send in the existing authenticated Chrome daemon on
port 9224 used **fetch**, not XMLHttpRequest. The existing `XHR_INTERCEPTOR_JS`
only hooks XMLHttpRequest.prototype.open/setRequestHeader/send. Consequently,
the request never reaches either recognition branch, Chrome sends it, and the
new conversation URL triggers `_raise_if_prompt_escaped()`.

Redacted capture: `docs/research/transport/2026-10-21-fetch-streamgenerate.json`.
The capture hook redacted request strings before returning them over CDP. No
cookie API was called by the diagnostic capture. Header values were not recorded;
fetch header names were also not recorded by this hook.

| Field | Existing contract | Captured request | Consequence |
| --- | --- | --- | --- |
| Browser API | XMLHttpRequest hook only | fetch POST | Hook is bypassed entirely |
| Endpoint | URL contains StreamGenerate | https://gemini.google.com/_/BardChatUi/data/assistant.lamda.BardFrontendService/StreamGenerate | Endpoint still matches |
| Query | Replay captured query | bl, f.sid, hl, _reqid, rt=c | Preserve query; redact runtime values |
| Form | f.req and at | f.req and at | No form migration needed |
| Envelope | JSON [null, JSON-string(inner)] | Same, 99-element inner array | Existing in-place patch preserves fields |
| Prompt | inner[0][0] | Reply with exactly CAPTURE_OK. | Same position |
| BotGuard | inner[3], inner[4] | Redacted strings of length 1551 and 32 | Same positions |
| Model | Capture/rewrite model header | Header values not collected | Must verify flash through actual replay |
| Response | JSONP prefix + length-prefixed frames | HTTP 200; `)]}'\n\n177\n[[...]]` | Existing parser format |
| URL construction | Prefix https://gemini.google.com to captured URL | fetch used an absolute URL | Normalize relative and absolute URLs |

No batchexecute RPC identifier selects this chat: StreamGenerate is a dedicated
endpoint. Other captured batchexecute requests were auxiliary and are omitted.
The processSession recognizer expects a POST URL with X-HTTP-Session-Id for open,
then a string form containing ___data__ for setup. That transport was not used
by this chat send.

## Live-send log

All times use Asia/Ho_Chi_Minh (UTC+07:00). No retry loops are authorized.

| # | Time | Surface | Hypothesis / purpose | Result |
| --- | --- | --- | --- | --- |
| 1 | 2026-10-21 14:30:41 +07:00 | Actual Gemini composer via existing Chrome CDP | Identify the browser API and current request shape using Reply with exactly CAPTURE_OK. | One fetch StreamGenerate POST, HTTP 200, response frames observed. DOM contained CAPTURE_OK (this check alone includes the user prompt and is not independent answer proof). |

## Boundaries

No login, auth reset, session copy, or release publication was performed.
BRIEF.md was already untracked and is outside this change.
ResearchService.start() and confirm() call client.send(), so they share chat
transport selection; research polling uses a separate RPC. Research live behavior
is not yet verified and is not required for this repair.
