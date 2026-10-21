# Authentication Flow

## Overview

Gemini web interface uses cookie-based authentication with two primary cookies
extracted from the browser. An access token and session parameters are then
extracted from the Gemini app page HTML.

## Required Cookies

| Cookie | Domain | Purpose | Lifetime |
|--------|--------|---------|----------|
| `__Secure-1PSID` | `.google.com` | Primary session identifier | Long-lived |
| `__Secure-1PSIDTS` | `.google.com` | Short-lived timestamp token | ~9-15 minutes |
| `NID` | `.google.com` | Optional, from browser | Long-lived |

## Authentication Flow

### Step 1: Pre-fetch Google Cookies

```
GET https://www.google.com
```

Collects any extra cookies that Google sets. These are merged with the primary
cookies for subsequent requests.

### Step 2: Extract Tokens from Gemini App Page

```
GET https://gemini.google.com/app
Headers: Standard Gemini headers (see known-rpcs.md)
Cookies: __Secure-1PSID, __Secure-1PSIDTS (+ any extras)
```

Parse three tokens from the HTML/JS response using regex:

| Token | Regex | Use |
|-------|-------|-----|
| `SNlM0e` | `r'"SNlM0e":\s*"(.*?)"'` | Access token, sent as `at` parameter in all POST requests |
| `cfb2h` | `r'"cfb2h":\s*"(.*?)"'` | Build label, sent as `bl` query parameter |
| `FdrFJe` | `r'"FdrFJe":\s*"(.*?)"'` | Session ID, sent as `f.sid` query parameter |

### Step 3: Cookie Refresh (Background)

Every ~540 seconds (9 minutes), refresh `__Secure-1PSIDTS`:

```
POST https://accounts.google.com/RotateCookies
Headers: Content-Type: application/json
Cookies: __Secure-1PSID, __Secure-1PSIDTS
Body: [000,"-0000000000000000000"]
```

Response sets a new `__Secure-1PSIDTS` cookie.

**Rate limiting**: Cache the refreshed value to disk. If the cache file was
modified within the last 60 seconds, use the cached value instead of making
another HTTP request (prevents 429 Too Many Requests).

**Cache file**: `.cached_1psidts_{__Secure-1PSID_value}.txt`

## Error Handling

| Scenario | Error | Recovery |
|----------|-------|----------|
| No valid cookies | `AuthError` | Prompt user to re-authenticate |
| All init attempts fail | `AuthError` | Re-extract cookies from browser |
| RotateCookies returns 401 | `AuthError` | Full re-authentication required |
| Token extraction fails | `AuthError` | Cookies may be expired |

## 3-Layer Recovery Strategy (for our implementation)

Matching the NotebookLM MCP pattern:

1. **CSRF refresh**: Re-fetch `https://gemini.google.com/app` to get fresh SNlM0e/cfb2h/FdrFJe
2. **Disk reload**: Reload auth.json from disk (may have been refreshed by another process)
3. **Headless re-auth**: Launch Chrome via CDP, navigate to Gemini, extract fresh cookies

## Cookie Sources (Priority Order)

1. Manually provided cookies (user input or auth.json)
2. Cached `__Secure-1PSIDTS` from disk + base `__Secure-1PSID`
3. Browser cookies via CDP (Chrome DevTools Protocol)

## Token Usage in Requests

All POST requests include:

**Query parameters:**
- `_reqid` = random 5-digit integer (incremented by 100000 between requests)
- `rt` = `c` (fixed)
- `bl` = cfb2h build label (if available)
- `f.sid` = FdrFJe session ID (if available)

**Body (form-encoded):**
- `at` = SNlM0e access token

After each request, update local cookies from response cookies
(`self.cookies.update(response.cookies)`).
