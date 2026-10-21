# PromptEscaped transport repair

## Status

Chat restored and verified through the installed CLI and MCP stdio server.
Local maintenance branch: `fix/prompt-escaped-transport`. This is a local patch to 0.9.7, not an
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
| 2 | 2026-10-21 14:34:25 +07:00 | Installed CLI, default profile, flash | Verify fetch capture plus Python replay produces a real answer | Exit 0, CLI_OK. |
| 3 | 2026-10-21 14:35:08 +07:00 | Installed MCP server over stdio, default profile, flash | Verify the MCP chat consumer uses the repaired shared transport | Exit 0, isError=false, text=MCP_OK, conversation present. |

Total: 3 logical live sends. UI triggers for smoke tests were intercepted and
aborted; the application replay sent the real prompt. No doctor, research,
extra chat, or retry loop was run during this task.

## Patch

- `src/gemini_web_mcp_cli/core/token_factory.py`: add a fetch hook alongside the
  unchanged XHR recognition branches. Capture the same StreamGenerate or
  processSession shapes, including headers and body. Keep the first capture,
  abort all matching data sends with AbortError, and pass auxiliary requests and
  processSession channel-open requests through. Support string/URL inputs,
  Request objects, header overrides, and URLSearchParams bodies.
- Normalize captured StreamGenerate URLs with urljoin so both legacy relative
  XHR URLs and current absolute fetch URLs replay correctly.
- `tests/test_chat_interceptor.py`: execute the actual hook in Node against mocked
  browser APIs with synthetic data; cover fetch, XHR, duplicate suppression,
  processSession open/data separation, passthrough, Request cloning and header
  overrides. Check the redacted capture against the existing body patcher.
- `tests/test_token_factory.py`: verify capture returns the correct URL for both
  relative and absolute inputs.
- No new transport, payload reconstruction, dependency, model hash, or fallback
  was introduced. The old XHR and processSession paths remain supported.

## Verification

- Full suite: `.venv/bin/pytest tests/ -q`: **683 passed, 15 warnings in 7.93s**.
  The warnings are httpx per-request cookie deprecations; no tests failed or skipped.
- `.venv/bin/ruff check src/ tests/`: passed.
- `git diff --check`: passed.
- Negative control: running the old hook from commit f35c006 in the same offline
  harness forwarded the fetch chat and left capture null. The new hook aborts it
  before the underlying fetch is called. These tests require Node and skip when
  it is absent; Node was present here and all hook tests executed.
- Initial focused run: 1 failed, 8 passed. The failed assertion omitted the
  Content-Type that the standard Request constructor adds to a string body.
  Expected headers were corrected to include that value. Initial lint also
  found long test lines; these were wrapped and lint passed. Neither failure was
  hidden or bypassed by removing coverage.
- Reinstalled with `uv cache clean gemini-web-mcp-cli` then
  `uv tool install --force .`. Installation completed from this checkout as
  version 0.9.7. uv fell back from hardlinks to file copies across filesystems.
  SHA-256 comparison confirmed installed token_factory.py equals the committed
  source. No upstream release is claimed.
- The source suite uses the repository lock environment (Python 3.13); uv tool
  installation independently resolved current dependencies. Both live smoke
  tests ran the installed executables, not the editable test environment.

Decisive installed CLI output (exit 0):

```text
$ gemcli -p default chat -m flash 'Reply with exactly the single word CLI_OK.'
CLI_OK
```

Decisive MCP stdio output (client exit 0, one tools/call):

```text
chat arguments: {"action":"send","model":"flash","prompt":"Reply with exactly the single word MCP_OK."}
MCP isError: False
{"text": "MCP_OK", "model_used": "flash", "has_conversation_id": true, "error": null}
```

The MCP client initialized a real stdio session with the installed
`~/.local/bin/gemini-web-mcp`, called chat once, parsed its JSON answer, and
asserted MCP_OK and no tool error. Conversation identifiers were omitted from
saved output. model_used reports the requested model; independent verification
of the server's model hash was not performed.

## Boundaries

No login, auth reset, session copy, or release publication was performed.
BRIEF.md was already untracked and is outside this change.
ResearchService.create_plan() and start() call client.send(), so they share chat
transport selection; research polling uses a separate RPC. Research live behavior
was not live-tested; it is not required for this repair.
