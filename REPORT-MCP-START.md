# MCP research start — round 3

## Result

**PASS — the complete installed MCP start → fresh-process status → fresh-process
report → fresh-process download sequence passed live.** The first attempt
succeeded without a model argument, replacing the existing completed state.
Report and download contain identical **14,682 UTF-8 bytes**. Expected premature
report/invalid-start errors returned `isError=true` and kept their servers alive.
Only one generation run was used. No production source change was necessary.

Branch: `fix/mcp-research-start`, created from `fix/deep-research` at `ea3bda2`.
No merge, upstream release, or login. Existing untracked `BRIEF.md`,
`BRIEF-DR.md`, and `BRIEF-MCP-START.md` are preserved.

## Implementation and regression coverage

The primary attempt used the final browser-backed implementation from round 2,
through the installed MCP stdio executable, with **no model argument**. The
installed `mcp.py`, `services/research.py`, and `core/token_factory.py` hashes
matched source before the attempt. No production-code failure was reproduced
and no speculative production patch was made.

The completed round-2 state (`c_406fe32ff799792d`, mode 0600) was present before
start. `_create_plan()` already replaces completed state with a new planning
state and a dedicated tab; it rejects planning/starting/running state. The new
run received `c_608d29b2ec128c6f`. The previous completed run did not block it.

Added regression coverage:

- Omitted MCP model reaches `create_plan(..., model=None)` and confirms once.
- A completed run is replaced without carrying its cid, target, or cached report
  into the new plan; the new dedicated target is used for confirmation.
- Planning/starting/running state is preserved and rejects a new plan before
  opening a page or sending a prompt.
- Confirmation, status, report, and download service exceptions become ToolError.
  Existing real-stdio synthetic initialization-failure coverage remains intact.

## Live evidence

Each invocation of the evidence client opens a new `stdio_client` and launches
`~/.local/bin/gemini-web-mcp`, initializes it, calls research, then sends ping
and lists tools **in that same session**. Distinct client PIDs and timestamps
are in the raw JSON files. Each invocation exits and closes its server before
subsequent invocations. No service method was called directly for acceptance.

Client: `docs/research/mcp-start/client.py` (run from the repository root using
`.venv/bin/python .../client.py <action> <evidence-tag>`). It performs exactly one
research tool call per invocation, without generation retries.

Primary input:

```json
{"action":"start","query":"In what year was the Metre Convention signed? Produce a brief factual report."}
```

Start, client PID 30193, 16:35:35 → 16:35:55 +07:00:

```text
isError=false
status=running
conversation_id=c_608d29b2ec128c6f
text=" Metre Convention Factual Report ... Research Websites ... Analyze Results ... Create Report ... Start research ..."
server_alive_after_result=true
```

The displayed plan is abbreviated; `primary.json` preserves the full MCP result.
A separate process (PID 30331), 16:36:16 → 16:36:17:

```json
{"status":"running","cid":"c_608d29b2ec128c6f"}
```

`isError=false`; subsequent ping/list-tools succeeded. `status-running.json`
preserves the result. Independent read-only CDP snapshots show the same cid,
a disabled real Start research control after confirmation, and then active
research summaries and source links in `deep-research-immersive-panel`.
See `dom-running.json` and `dom-progress.json`. These observations establish
actual research execution beyond the start response's status label.

Report, another fresh process (PID 32495), 16:43:19 → 16:43:20:

```text
isError=false
status=completed
text="The Metre Convention of 1875: Origins, Institutional Architecture, and Global Metrological Evolution\nExecutive Summary and Founding Event\n..."
server_alive_after_result=true
```

Full raw MCP response: `docs/research/mcp-start/report.json`. Full text:
`docs/research/mcp-start/report.txt`. An excerpt from the retrieved report:

> The Metre Convention (Convention du Mètre, also known in English as the Treaty
> of the Metre) was signed on May 20, 1875, and formally entered into force on
> January 1, 1876.

Download, a fourth independent process (PID 32499), 16:43:21:

```text
isError=false
{"path":"/tmp/round3-dr-download.txt"}
server_alive_after_result=true
```

The client asserted byte equality between the downloaded file and the UTF-8
encoding of the full report response. It also asserted that the report equals
the DOM report panel text and the completed durable state's report; state mode
remains 0600. Proof: `download.json`, `comparison.json`, `dom-completed.json`.
The completed DOM has report text and an enabled Export menu, distinguishing a
finished report from a plan, activity summary, or streaming report.

```text
bytes: 14682
SHA-256: c1a9c880bd058d282d692a6b8209de9417695b7a36cf17372b9a52ac29c6f3ac
```

## Failure containment

Readiness and validation negative checks ran against separate installed live MCP
server processes, with no generation:

| Time (+07:00) | Tool call | Actual outcome |
| --- | --- | --- |
| 16:36:33 → 16:36:34 | report before completion | `isError=true`; `Error executing tool research: Research report is not ready.` |
| 16:36:34 → 16:36:35 | start without query | `isError=true`; `Error executing tool research: query is required for start action` |
| 16:40:35 → 16:40:36 | report still not complete | `isError=true`; `Research report is not ready.`; server remained alive |

All these servers accepted ping and list-tools in the **same session after the
error**, recorded as `server_alive_after_result=true`. Raw proof:
`report-before-ready.json`, `report-before-ready-later.json`, `invalid-start.json`.
These are expected validation and readiness errors, not failures of the primary generation. No unexpected
start failure was encountered, so no failure-triggered DOM diagnosis or fix was
needed. Other injected service failures are covered offline, not claimed live.

## Checks and installation

- `.venv/bin/pytest tests/ -q`: **721 passed, 15 warnings in 8.47s**; no skips.
  Warnings are existing httpx per-request-cookie deprecations.
- `.venv/bin/ruff check src/ tests/`: passed.
- Source/test diff checks passed. The final staged all-artifact diff check
  **flagged trailing whitespace in the raw generated `report.txt`**. That file
  remains byte-for-byte identical to the live report and download; trimming it
  would invalidate the equality proof. The complete branch diff excluding only
  that raw report passes `git diff ea3bda2 --check -- .
  ':(exclude)docs/research/mcp-start/report.txt'`.
- The archived client initially failed lint on compact imports, one-line
  statements, and long lines. Import fixes and formatting resolved them;
  `ruff check src/ tests/ docs/research/mcp-start/client.py` passed.
- Initial full run: **721 passed in 8.42s**. Focused tests after readability
  cleanup: **37 passed in 0.55s**. The final full run above includes the extra
  assertion that the previous target id is discarded. Ruff and source/test diff checks
  passed again. Runtime source was unchanged throughout.
- `uv cache clean gemini-web-mcp-cli` then `uv tool install --force .`: succeeded
  from this checkout as 0.9.7. uv fell back from hardlinks to file copies across
  filesystems; installation succeeded.
- All **38 Python source files** under the installed package match checkout
  byte-for-byte after reinstall. Complete SHA-256 manifest:
  `docs/research/mcp-start/installed-hashes.json`.
- Primary start and first status/error checks used the matching round-2
  installation. Later read calls use the reinstalled identical runtime source.

## Generation budget

All times use Asia/Ho_Chi_Minh (UTC+07:00).

| # | Time | Surface | Purpose | Outcome |
| --- | --- | --- | --- | --- |
| 1 | 2026-10-21 16:35:35 → 16:35:55 | Fresh installed MCP stdio, default profile, model omitted | Primary acceptance; replace completed round-2 state | Real plan returned and confirmed, `isError=false`; dedicated conversation `c_608d29b2ec128c6f`, fresh-process status running; report completed at 16:43:20; download identical |

**One generation run used; no retest, explicit-model run, diagnostic send, or
retry loop.** Status/report/download and read-only DOM inspections add no
research generations. The unused second run was not needed to diagnose start.

## Remaining boundaries

All required acceptance steps passed. Live completion was observed at 16:43:08,
about 7m33s after the initial call, and retrieved at 16:43:20.

Explicit `model="flash"`, other model choices, non-English UI, interrupted-start
recovery, and closed-tab restoration were not exercised live in this round.
Existing round-2 CLI and chat results were not rerun. Retrieved report text is
model output; this task does not independently audit its factual accuracy.
