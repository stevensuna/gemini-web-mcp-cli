# Usage Limits (qpEbW RPC)

> **Update (2026-09):** The response fields are a **usage percentage**
> (`Used`) and a **credit pool** (`limit`/`remaining`; pool size depends on
> the plan, e.g. 2400 or 48384 credits). Each row carries its own reset
> timestamp; the window length is not fixed or documented — read it from
> the response rather than assuming 5h or 24h. The RPC now requires an explicit feature list and
> processes one `[1, feature_id]` pair per call. See `services/limits.py`.
> The old per-feature daily counts below are historical.


## Status: CAPTURED

## Overview

The `qpEbW` RPC returns per-feature usage limits for the authenticated user's
Gemini plan. It reports current usage, daily limit, remaining quota, and a
per-feature rolling reset timestamp.

## RPC Details

### Request
- **Endpoint**: batchexecute
- **RPC ID**: `qpEbW` (constant: `RPC.USAGE_INFO`)
- **Payload**: `[]`
- **Auth**: Requires full browser cookies (Token Factory). Returns error code
  `[7]` with basic 2-cookie auth.

### Response Structure

```
data = [[entries_array], ""]

entry = [
    [2, feature_id, 2],         # Feature identifier triplet
    1,                           # Active flag (always 1)
    used_count,                  # Current usage in this period
    [reset_seconds, reset_nanos],# When the limit resets (Unix timestamp)
    limit,                       # Total daily limit
    remaining,                   # Remaining quota (limit - used)
]
```

### Feature ID Mapping

Mapped by cross-referencing observed limits with the official Google AI
subscription limits at support.google.com/gemini/answer/16275805.

| Feature ID | Name | Pro Limit | Ultra Limit |
|------------|------|-----------|-------------|
| 3 | Deep Think 3.1 | 5 | ? |
| 4 | Dynamic View | 25 | ? |
| 5 | Video (Veo 3.1) | 3 | 5 |
| 7 | Images (Nano Banana) | 1000 | 1000 |
| 8 | Deep Research | 20 | 120 |
| 9 | Pro 3.1 Prompts | 100 | 500 |
| 11 | Audio Overviews | 20 | 20 |
| 12 | (disabled) | 0 | ? |
| 13 | Dynamic View (extended) | 250 | 250 |
| 14 | Slides | 20 | Unlimited? |
| 15 | Thinking Prompts | 80 | 1500 |
| 16 | Agent Requests | 200 | ? |
| 17 | Music (Lyria 3) | 50 | 100 |
| 18 | Unknown | 5 | ? |
| 19 | Images (Nano Banana Pro) | 20 | 1000 |

### Key Observations

1. **Rolling windows**: Each feature has its own independent reset time, not a
   global midnight reset. The window length is not confirmed (it was
   assumed to be 24h here and ~5h elsewhere); trust the returned timestamp.

2. **Per-plan limits**: The limits change based on the user's Google AI plan
   (Plus, Pro, Ultra). The same RPC returns the user's actual limits.

3. **Disabled features**: Feature ID 12 has `limit=0`, indicating it's not
   available on this plan.

## Captured: Feb 22, 2026

Live capture from a Google AI Pro account. All 15 feature entries returned
with `used=0` (fresh window).
