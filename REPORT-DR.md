# Deep Research round 2

## Acceptance status

**Partial verification. The requested MCP-start → fresh-process status →
fresh-process report acceptance sequence has not passed.** The first MCP start
attempt failed before confirmation. No replacement MCP run is being sent within
this task's live budget.

Branch: `fix/deep-research`, created from `fix/prompt-escaped-transport` at
`0edd99d`. No merge or upstream release.

## Evidence and root causes

The existing ResearchService did not select Deep Research at all. Its
`create_plan()` called ordinary `client.send()`. The CLI only printed that first
response; it did not call `start()`, wait for completion, or write `--output`.
The MCP start branch also omitted confirmation, advertised automatic research
without starting it, and implemented neither report nor download. Each service
instance lost its conversation metadata at process exit. Polling `kwDCne` with
`[]` and a source path had no demonstrated completion/report contract.

Two diagnostic composer triggers were used, both on the existing authenticated
Chrome daemon, port 9224. The first enabled the actual Deep research tool and
returned a real research plan with a Start research control. Its observer did
not decode Request bodies. The second installed the existing round-1 hook and
an observer that cloned the Request body before invoking that hook.

Redacted wire fixture:
`docs/research/transport/2026-10-21-dr-wire.json`.

| Property | Observed DR request | Round-1 hook |
| --- | --- | --- |
| API | `fetch(Request)`; no init argument | Supported |
| Endpoint | `/_/BardChatUi/data/assistant.lamda.BardFrontendService/StreamGenerate` | Matches |
| Form | `f.req`, `at` | Request clone decoded |
| Envelope | `[null, JSON-string(inner)]`, 99 fields | Existing patcher preserves shape |
| Prompt | `inner[0][0]` | Existing position |
| Observed tool/options fields | `inner[49] = 1`; `inner[30] = [4,16,19]` also observed | No invented numeric field patch |
| Capture | `window.__cap` contained a string body and `streamgenerate` transport | Original fetch aborted |

**PromptEscaped was not reproduced.** Evidence does not support a new DR
endpoint, worker/frame, or request API. The installed round-1 token_factory.py
hash already matched source before changes. Consequently no speculative
interceptor or model-picker patch was retained. Offline tests now exercise the
observed DR Request shape through the actual existing hook and body patcher.

An intermediate implementation explicitly selected DR, replayed the captured
request through Python, and tried to reopen the returned conversation for the
real confirmation control. Its installed MCP start got HTTP 200 and a parsed
candidate, but the returned conversation redirected to `/app` without a Start
research control. The tool returned `isError=true`. A read-only `hNvQHb` probe
returned null, including for a conversation that visibly contained a report.
The underlying replay/persistence and read-RPC discrepancy remains unresolved.
These observations do not prove DR is impossible to implement through HTTP.

The daemon also had two Gemini tabs. Selecting the first available tab is not
sufficient isolation for this workflow. A diagnostic SI conversation later
showed a completed report, but no controlled confirmation for that conversation
was recorded. Its provenance is therefore not acceptance proof and its report
is not substituted for a successful MCP run.

The earlier claimed MCP process death was also not reproduced. PromptEscaped
inherits Exception, not BaseException/SystemExit. No causal claim about that
earlier termination is made. The explicit ToolError boundary and an offline
real-stdio continuation test now verify tool-error containment.

## Final implementation

Research uses the actual Gemini UI in a dedicated background tab on the same
profile's Chrome, rather than relying on the unverified async RPC contracts.
This is a browser-backed implementation, not a repaired HTTP DR protocol.

- `services/research.py`: enable Deep research before sending; optionally select
  the requested model; require the real plan confirmation widget; click Start
  research once; observe the research report panel and enabled Export menu
  before declaring completion. A normal answer, plan, or streaming report is
  insufficient. No automatic send retries.
- Pin the dedicated CDP target id instead of selecting an arbitrary tab. A fresh
  instance can reopen the conversation when its saved target has closed.
- Store one active research per profile in
  `~/.gemini-web-mcp-cli/profiles/<profile>/research.json`: schema version,
  conversation id, target id, phase, and completed report. Atomic replacement
  uses a 0600 temporary file. No cookies or authentication tokens are stored in
  this state file. Profile locks serialize browser/state operations.
- `mcp.py`: start creates the plan and confirms it; status/report/download use
  durable service state. Validate arguments before client initialization.
  Convert failures, including initialization failures, to FastMCP ToolError.
- `cli.py`: create, confirm, wait, print the completed report, and honor `-o`.
  With no model argument the dedicated tab's browser selection is used.
- `tests/test_research.py`, `tests/test_mcp_research.py`, and
  `tests/test_chat_interceptor.py`: persistence, 0600 mode, profile separation,
  malformed state, pinned targets, confirmation, completion detection,
  wrong-conversation rejection, timeout, download, action dispatch, and real
  stdio error survival. Browser hook tests retain XHR/fetch/processSession
  coverage. No chat transport source change remains.

A completed report is cached durably. Status/report/download can then return it
without the original server process or browser tab. While research is active,
the authenticated Chrome session and current English UI selectors are required.
An interrupted planning/starting phase is retained rather than blindly resent.
There is no new cancel/replace action; only one active run per profile is allowed.

## Checks

- Full suite: `.venv/bin/pytest tests/ -q`: **712 passed, 15 warnings, 8.65s**.
  Warnings are existing httpx per-request-cookie deprecations; no tests skipped.
- `.venv/bin/ruff check src/ tests/`: passed.
- `git diff --check`: passed.
- Offline stdio negative control: inject PromptEscaped during research client
  initialization; tools/call returns `isError=true`; the same session then
  accepts ping and lists tools.
- Initial focused DR-shape assertion used index 51 instead of observed index 49
  and failed. It was corrected against the enumerated redacted fixture. Several
  initial lint checks found long test lines/imports; those were corrected.
- The intermediate HTTP-backed start was installed and failed live. It was
  replaced by the browser-backed service; that failure is retained above.

## Live-send log

All times are Asia/Ho_Chi_Minh (UTC+07:00). Diagnostic times are approximate,
based on observer-script creation and immediate tool execution.

| Time | Surface | Purpose | Outcome |
| --- | --- | --- | --- |
| ~2026-10-21 15:06:25 | Native DR composer, diagnostic trigger 1 | Identify DR request API and plan behavior | fetch StreamGenerate; real plan. Body observer needed Request cloning. Later completed report observed, without a recorded controlled confirmation; not acceptance proof. |
| ~2026-10-21 15:07:30 | Native DR composer, diagnostic trigger 2 | Test existing hook with Request-body observer | Captured and aborted; redacted 99-field envelope saved. No further diagnostic triggers. |
| 2026-10-21 15:10:25 | Installed MCP research start, model flash | First end-to-end attempt, intermediate implementation | Captured/replayed HTTP 200; returned conversation could not be opened; isError=true, no confirmation sent. Server returned an error result rather than closing stdout. |
| 2026-10-21 15:18:25 → 15:21:44 | Installed CLI research | CLI end-to-end attempt with dedicated native UI tab | Exit 0; actual Start research clicked; completed report written, 9,112 bytes. |
| 2026-10-21 15:20:08 | Fresh installed MCP process: status | Verify durable state from the active CLI run | isError=false, status=running. No generation send. |
| 2026-10-21 15:23:05 | Fresh installed MCP process: report | Retrieve the completed CLI research | isError=false, status=completed; full text matches CLI output file. |
| 2026-10-21 15:23:08 | Another fresh installed MCP process: download | Verify durable report export | isError=false; downloaded file matches CLI output byte-for-byte. |

Two diagnostic triggers and two acceptance attempts were made. The failed MCP
attempt stopped before research confirmation; no replacement run, login,
authentication reset, or extra chat was sent. Status/report checks are read-only
with respect to research generation. The CLI's normal progress polling is not a
retry of any generation send.

## Live outputs and installation

First installed MCP start (failed):

```text
isError= True
Error executing tool research: Research plan has no Start research control; no confirmation sent.
```

Fresh-process MCP status during the CLI run:

```text
isError= False
{"status":"running","cid":"<omitted>"}
```

Installed CLI (exit 0, approximately 3m19s):

```text
$ gemcli -p default research 'In what year was the International System of Units (SI) established? Produce a brief factual report citing BIPM Resolution 12 of the 11th CGPM.' -o /tmp/dr-cli-report.md
Creating research plan...
[actual plan printed]
Research running...
The Establishment of the International System of Units: A Metrological Examination of Resolution 12 of the 11th CGPM
[completed report printed]
```

Decisive excerpt from the actual completed report:

> The International System of Units (SI) was formally established in 1960 by
> the 11th Conférence Générale des Poids et Mesures (CGPM), which convened in
> Paris from 11 to 20 October 1960 under the authority of the Bureau
> International des Poids et Mesures (BIPM).

The report also includes this specific citation:

```text
Proceedings of the 11th CGPM (1960), 1961, p. 87; DOI: 10.59161/CGPM1960RES12E
```

Full generated text is retained at
`docs/research/transport/2026-10-21-cli-dr-report.txt`. This demonstrates retrieval
of generated report text, not independent verification of its factual claims.

Fresh installed MCP process for report, separate from both start and status:

```text
isError= False
{"status":"completed","text":"The Establishment of the International System of Units: ..."}
```

The display above abbreviates text; the client parsed the full JSON and asserted
its text equals the CLI output file. A fourth fresh process called download:

```text
isError= False
{"path":"/tmp/dr-mcp-report.md"}
```

All three forms (CLI file, MCP report text, MCP download file) contain identical
9,112-byte text with SHA-256:

```text
057f0ecc1ebaeb617c741303d1716013ae74a822a86e2da5c3febee76d335632
```

Reinstalled from this workdir with `uv cache clean gemini-web-mcp-cli` then
`uv tool install --force .`. Installation succeeded; uv used file copies across
filesystems. Final installed changed files match source byte-for-byte:

| File | SHA-256 |
| --- | --- |
| `cli.py` | `74de6dc7ea1585063a50b52a2b8c40e621f812d2eba0a54e055ba09278161d7e` |
| `mcp.py` | `7c9a042a7a6930159da60a7c56a5aa1c43d7a03760e05b5f91883b0d5b086833` |
| `services/research.py` | `1f95a049fd5bd3f719aaa94be19f62bc3e7bf927fb8e5ecb01088c2cab52dcb6` |

Unchanged installed/source `core/token_factory.py` also matches:
`1f231fe6a212097df4be2999dc86cfca34cc2f8fba6192046bea7eb4a36be8d7`.
The real state file was verified as completed, mode 0600, with only version,
status, target_id, cid, and report fields.

The successful CLI run used the browser-backed implementation before two final
small changes: narrowing printed plan text to its confirmation widget and
checking the conversation id before confirmation. The report/poll/download
logic was unchanged. Those final changes passed focused tests and the final
full suite; the final source was reinstalled and hash-compared afterward.

## Remaining acceptance boundary

- CLI full research: **passed live**.
- Fresh-process MCP status/report/download against that CLI run: **passed live**.
- MCP start with the final browser-backed service: **not live-verified**. Its
  dispatch and create/confirm ordering pass mocked tests; the earlier installed
  HTTP-backed attempt failed. Explicit-model research in the final UI path is
  also not live-verified.
- Exact cause of the originally reported PromptEscaped and server termination:
  **unresolved**, neither reproduced by these captures.
- No claim that the requested complete MCP-start sequence passed. Finishing
  that acceptance requires one further controlled live MCP research run under
  the final implementation, beyond this task's reserved attempts.
- Browser selectors depend on the current English Gemini UI. Interrupted runs,
  closed-tab restoration, and other UI/model variants have offline coverage
  only. A planning/starting interruption is not automatically resent.
- Existing untracked `BRIEF.md` and `BRIEF-DR.md` were preserved. No login, merge,
  main-branch change, release, or unrelated cleanup was performed.
