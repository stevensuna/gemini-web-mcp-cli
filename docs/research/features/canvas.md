# Canvas

## Status: NOT CAPTURED -- Manual RPC capture required

## Overview

Canvas is Gemini's collaborative document editing feature. It allows creating
and editing documents directly within the Gemini interface.

## What We Know

- Canvas is accessible from the Gemini web UI
- It provides a document editing experience alongside the chat
- gemini-webapi does NOT implement this
- Canvas content can be exported

## Capture Plan

1. Open Chrome DevTools > Network tab
2. Filter to Fetch/XHR
3. Perform Canvas operations in Gemini:
   a. Create a new Canvas document
   b. Edit the Canvas content
   c. Export / download the Canvas
4. For each operation, capture:
   - RPC ID and payload
   - Response structure
5. Export HAR file to `captures/har/canvas.har`
6. Extract cURL commands to `captures/curl/canvas.sh`

## Questions to Answer During Capture

- How is a Canvas document created? Separate RPC or through chat?
- What's the data model for Canvas content (markdown, HTML, rich text)?
- How are edits sent (full content replace or operational transforms)?
- Can Canvas content be exported? What formats?
- Is there a separate Canvas ID / document ID?
- How does Canvas interact with the chat (context sharing)?
