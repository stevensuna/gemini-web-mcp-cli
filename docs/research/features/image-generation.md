# Image Generation

> **Update (2026-09):** The Images composer exposes an aspect-ratio control
> (`inner[55]`: 9:16=59, 3:4=60, 1:1=61, 4:3=62, 16:9=63; label at
> `inner[0][9][6][1]`). gemcli drives it via `gemcli image -A` / MCP `aspect`.


## Overview

Image generation in Gemini uses the Imagen model (internally called "Nano Banana" /
ImageFX). Images are generated through the standard chat/StreamGenerate endpoint --
you simply send a prompt asking for an image.

## How It Works

1. Send a chat message requesting an image (e.g., "Generate an image of a red panda")
2. The response includes generated images in the candidate data
3. Images are accessible via URLs that require authentication (cookies)

## Response Structure

Generated images appear at `candidate_data[12][7][0]`:

```python
# Generated images list
generated_images = candidate_data[12][7][0]

# Per generated image:
image_url = image_data[0][3][3]      # Image URL
image_number = image_data[3][6]       # Image number (1, 2, 3, 4)
image_alt = image_data[3][5][0]       # Alt text / description
```

Web images (from search/context) at `candidate_data[12][1]`:

```python
# Web images list
web_images = candidate_data[12][1]

# Per web image:
image_url = image_data[0][0][0]       # Image URL
image_title = image_data[7][0]        # Title
image_alt = image_data[0][4]          # Alt text
```

## Image Download

### Generated Images

- URLs require authentication (pass cookies with the request)
- Append `=s2048` to URL for full-size image
- Default filename format: `{timestamp}_{url_last_10_chars}.png`

### Web Images

- Usually publicly accessible URLs
- Filename from URL path

## Image Editing

Image editing works through the chat interface:
1. Upload the original image (via file upload endpoint)
2. Send a chat message with the file attachment and editing instructions
3. Response contains modified generated images

## File Upload for Image Context

See [file-upload.md](file-upload.md) for the upload protocol. The file identifier
from the upload response is included in the chat request at `inner_req_list[0][3]`.

## Bard Activity Prerequisite

Before the first file upload in a session, call the `ESY5D` (BARD_ACTIVITY) RPC
to enable upload capability:

```python
# via batchexecute
rpc_id = "ESY5D"
payload = "[1]"
```

## Known Limitations

- Image generation response structure can vary by account type and region
- Some edge cases in parsing (reported as issues in gemini-webapi)
- Generated image URLs may be temporary (time-limited)
