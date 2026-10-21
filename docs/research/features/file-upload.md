# File Upload Protocol

## Status: CAPTURED (Feb 20, 2026)

## Overview

Files (images, PDFs, documents, audio) are uploaded to Google's push service
via a 2-step resumable upload protocol and return an identifier that can be
referenced in chat messages.

## Endpoint

```
POST https://push.clients6.google.com/upload/
```

**Note:** The endpoint changed from the previously documented
`content-push.googleapis.com/upload` to `push.clients6.google.com/upload/`.
Discovered via live Chrome DevTools MCP capture on Feb 20, 2026.

## Upload Protocol (2-Step Resumable)

### Step 1: Start Upload Session

| Aspect | Details |
|--------|---------|
| Method | POST |
| URL | `https://push.clients6.google.com/upload/` |
| Content-Type | `application/x-www-form-urlencoded;charset=UTF-8` |
| Header | `push-id: feeds/mcudyrk2a4khkz` |
| Header | `x-goog-upload-command: start` |
| Header | `x-goog-upload-protocol: resumable` |
| Header | `x-goog-upload-header-content-length: <file_size>` |
| Body | `File name: <filename>` |

**Response:** Status 200, empty body. The upload URL is in the response header:
```
x-goog-upload-url: https://push.clients6.google.com/upload/?upload_id=<id>&upload_protocol=resumable
```

### Step 2: Upload File Data (Finalize)

| Aspect | Details |
|--------|---------|
| Method | POST |
| URL | The `x-goog-upload-url` from Step 1 |
| Content-Type | `application/x-www-form-urlencoded;charset=utf-8` |
| Header | `push-id: feeds/mcudyrk2a4khkz` |
| Header | `x-goog-upload-command: upload, finalize` |
| Header | `x-goog-upload-offset: 0` |
| Body | Raw file bytes |

**Response:** Status 200, plain text body containing the file identifier:
```
/contrib_service/ttl_1d/t5rp2pfn7ttoxuwnsv6xqfgm4b2azt1771550322_AWZTtlG6y3Zpkq...
```

## Usage in Chat

The file identifier is included in the StreamGenerate request payload at
`inner_req_list[0][3]`:

```python
# inner_req_list[0] = [prompt, 0, None, file_data, None, None, 0]
# where file_data is a list of file entries:
file_data = [
    [
        [file_identifier, 16, None, "text/markdown"],  # [id, 16, null, mime_type]
        "README.md",                                     # filename
        None, None, None, None, None, None,             # 6x null
        [0]                                              # trailing
    ]
]
```

**Key differences from old documentation:**
- Field at index 1 is `16` (not `1`)
- Field at index 3 is the MIME type string (not absent)
- Entry has 9 elements (not 3): `[file_info, name, null*6, [0]]`

## Bard Activity Prerequisite

Before the first file upload in a session, enable Bard activity:

```python
# batchexecute with ESY5D RPC
rpc_id = "ESY5D"
payload = "[1]"
```

The browser sends this RPC multiple times during the upload flow.

## BotGuard Requirement

File uploads require BotGuard tokens. The `StreamGenerate` request that
includes file attachments must include a valid BotGuard token at `inner[3]`
and challenge hash at `inner[4]`. This means file attachments route through
the Token Factory path, even on the Flash model.

## Supported File Types

Based on live testing and MIME type detection:
- Images (PNG, JPEG, GIF, WebP)
- PDFs
- Documents (text files, markdown)
- Audio files
- Video files (MP4, AVI, MOV, WebM, etc.)

## Upload Limits (Gemini Apps, July 2026)

Service-side limits enforced by gemini.google.com:
- Up to **10 files per prompt** (any mix of types)
- Each **video** ≤ **2 GB**; all other file types ≤ **100 MB**
- Total **video** length ≤ **5 min** (free) / **1 hour** (Google AI Pro/Ultra)
- Total **audio** length ≤ **10 min** (free) / **3 hours** (Pro/Ultra)
- Code folder / GitHub repo: 5,000 files, 100 MB; ZIP: 10 files, 100 MB (no A/V)
- Very large files can exceed the context window → truncated/missed-detail answers

Source: https://support.google.com/gemini/answer/14903178

## File Identifier Lifetime

The identifier path includes `ttl_1d`, suggesting files expire after 1 day.
Files should be uploaded close to when they'll be used in chat.

## Authentication

Both upload steps require the full Google cookie set. The `Origin` and
`Referer` headers must be set to `https://gemini.google.com`.

## Capture Details

Captured via Chrome DevTools MCP on Feb 20, 2026:
- Network requests 119-123: CORS preflight, start, finalize
- Network request 131: StreamGenerate with file attachment
- Raw captures saved to `experiments/upload_req_*.txt` and `experiments/upload_res_*.txt`
