# Gemini Web MCP - Research Phase

## Overview

This directory contains the reverse-engineering research for the Gemini web interface
(gemini.google.com). The goal is to document every RPC call, endpoint, and protocol
detail needed to build the `gemini-web-mcp-cli` project.

## Reference Source

RPC knowledge extracted from [HanaokaYuzu/Gemini-API](https://github.com/HanaokaYuzu/Gemini-API)
(`gemini-webapi` on PyPI, ~2,143 stars). No code copied -- only protocol knowledge used
as reference for our clean-room rebuild.

## Research Status

### Known RPCs (from gemini-webapi)

| Feature | Status | Document |
|---------|--------|----------|
| Authentication | Documented | [auth/auth-flow.md](auth/auth-flow.md) |
| Cross-product profiles | Documented | [auth/cross-product-profiles.md](auth/cross-product-profiles.md) |
| Session lifecycle & keep-alive | Documented | [auth/session-lifecycle.md](auth/session-lifecycle.md) |
| Chat + Streaming | Documented | [features/chat.md](features/chat.md) |
| Image Generation | Documented | [features/image-generation.md](features/image-generation.md) |
| Video Generation (Veo) | Documented | [features/video-generation.md](features/video-generation.md) |
| Deep Research | Documented | [features/deep-research.md](features/deep-research.md) |
| Gems (CRUD) | Documented | [features/gems.md](features/gems.md) |
| File Upload | Documented | [features/file-upload.md](features/file-upload.md) |
| Extensions | Documented | [features/extensions.md](features/extensions.md) |
| Model Switching | Documented | [features/model-switching.md](features/model-switching.md) |

| Music Generation (Lyria 3) | CAPTURED | [features/music-generation.md](features/music-generation.md) |
| Music Style Presets (16 remix presets) | CAPTURED | [captures/music-presets-all-16.json](captures/music-presets-all-16.json) |

### Not Yet Captured

| Feature | Status | Document |
|---------|--------|----------|
| Canvas | NOT CAPTURED | [features/canvas.md](features/canvas.md) |
| Code Execution | NOT CAPTURED | [features/code-execution.md](features/code-execution.md) |

## Capture Methodology

See the **[RPC Capture Guide](RPC_CAPTURE_GUIDE.md)** for the full step-by-step process
for discovering and documenting new RPCs. The guide covers setup, extraction, decoding,
response mapping, verification, and a documentation template.

## Directory Structure

```
research/
  README.md                      # This file
  RPC_CAPTURE_GUIDE.md           # Standard methodology for capturing new RPCs
  known-rpcs.md                  # Master RPC reference table
  auth/
    auth-flow.md                 # Cookie auth, token extraction, refresh
    cross-product-profiles.md    # Profile sharing with NotebookLM MCP
    session-lifecycle.md         # Why sessions die; keep-alive design rules
  features/
    chat.md                      # Chat + streaming protocol
    image-generation.md          # Image gen (Imagen)
    video-generation.md          # Video gen (Veo 3.1)
    music-generation.md          # Music gen (Lyria 3) - CAPTURED
    deep-research.md             # Deep Research
    canvas.md                    # Canvas - TO CAPTURE
    code-execution.md            # Code execution - TO CAPTURE
    gems.md                      # Gems CRUD
    extensions.md                # Extensions (YouTube, Maps, etc.)
    file-upload.md               # File upload protocol
    model-switching.md           # Model switching via Token Factory
  captures/
    music-presets-all-16.json  # All 16 music style presets (IDs, system prompts)
    remix-8bit-request.txt     # Captured 8-bit preset StreamGenerate request
    remix-8bit-response.txt    # Captured 8-bit preset response
    bard-config.json           # Bard UI configuration reference
```
