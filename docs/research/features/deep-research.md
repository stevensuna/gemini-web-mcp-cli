# Deep Research

## Status: NOT CAPTURED -- Manual RPC capture required

## Overview

Deep Research is a Gemini feature that performs extended, multi-step research on a
topic. It takes several minutes to complete and produces a comprehensive report.

## What We Know

- Deep Research is triggered from the Gemini web UI
- It likely uses a long-running async pattern (start -> poll -> get results)
- gemini-webapi does NOT implement this (open issue #80)
- The research process takes ~5 minutes
- Results include a structured report with citations

## Capture Plan

1. Open Chrome DevTools > Network tab
2. Filter to Fetch/XHR
3. Start a Deep Research query in Gemini (e.g., "Deep research: latest advances in quantum computing")
4. Watch for:
   - Initial RPC call that starts the research (capture RPC ID + payload)
   - Polling requests that check progress (capture RPC ID + payload)
   - Final response with the research report (capture response structure)
5. Export HAR file to `captures/har/deep-research.har`
6. Extract cURL commands to `captures/curl/deep-research.sh`

## Expected Structure

Based on patterns from other Google products:

```python
# Start research
rpc_id = "TBD"
payload = json.dumps([query, options...])

# Poll status
rpc_id = "TBD"
payload = json.dumps([task_id])

# Get report (may be in final poll response)
```

## Questions to Answer During Capture

- Is Deep Research a single long-running request or start + poll?
- What's the RPC ID?
- How is progress reported?
- What does the final report structure look like?
- Can you specify research parameters (depth, focus areas)?
- Are citations structured or inline text?
