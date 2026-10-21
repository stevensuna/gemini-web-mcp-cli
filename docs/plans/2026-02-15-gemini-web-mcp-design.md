# gemini-web-mcp-cli Design Plan

## Project Summary

**Package**: `gemini-web-mcp-cli` (PyPI)
**CLI command**: `gemcli`
**Repo visibility**: Private during development. Public release planned for later.
**Approach**: Clean-room rebuild using `gemini-webapi` (HanaokaYuzu/Gemini-API) as reference for known RPC IDs and protocol details. No code copied -- architecture follows established patterns from `notebooklm-mcp-cli` and `perplexity-web-mcp`.

**Acknowledgments (for public release):** When this repo goes public, credit [HanaokaYuzu/Gemini-API](https://github.com/HanaokaYuzu/Gemini-API) in the README as the inspiration and reference for reverse-engineering the Gemini web interface RPC protocol.

## Architecture

Layered architecture with a shared core consumed by all interfaces:

```
                    ┌─────────────────────────────────────────┐
                    │           Interface Layer                │
                    │  CLI (gemcli) │ MCP Server │ API (Ph.2)  │
                    └───────────────┬─────────────────────────┘
                                    │
                    ┌───────────────▼─────────────────────────┐
                    │         Service Layer (1 per feature)    │
                    │  Chat │ Image │ Video │ Research │ Gems  │
                    │  Canvas │ CodeExec │ FileUpload          │
                    └───────────────┬─────────────────────────┘
                                    │
                    ┌───────────────▼─────────────────────────┐
                    │           Core Layer                     │
                    │  GeminiClient │ RPCTransport │ Parser    │
                    │  AuthManager │ ProfileManager            │
                    └───────────────┬─────────────────────────┘
                                    │
                    ┌───────────────▼─────────────────────────┐
                    │       Shared Ecosystem                   │
                    │  Chrome Profile Manager                  │
                    │  Cross-product: notebooklm-mcp-cli       │
                    └─────────────────────────────────────────┘
```

**Key principles:**

- Single source of truth: All RPC calls live in the core layer
- Service-per-feature: Each Gemini capability is its own module
- Shared profile manager: Detects and reuses NotebookLM MCP Chrome profiles
- All generated resources (images, videos, reports) are downloadable to local files

## Project Structure

```
gemini-web-mcp-cli/
  pyproject.toml
  README.md
  CLAUDE.md                        # AI agent reference
  src/gemini_web_mcp_cli/
    __init__.py
    core/
      __init__.py
      client.py                    # GeminiClient - session management
      rpc.py                       # RPCTransport - batchexecute + streaming
      parser.py                    # ResponseParser - frame decoding, field extraction
      auth.py                      # AuthManager - CDP, cookies, token refresh
      profiles.py                  # Chrome Profile Manager (cross-product)
      constants.py                 # RPC IDs, endpoints, model hashes, error codes
      exceptions.py                # Custom exceptions
      models.py                    # Pydantic models for requests/responses
    services/                      # ALL business logic -- single source of truth
      __init__.py
      chat.py                      # ChatService - send, stream, model selection
      image.py                     # ImageService - generate, edit, download
      video.py                     # VideoService - generate, status, download
      research.py                  # ResearchService - start, poll, report, download
      gems.py                      # GemsService - CRUD
      canvas.py                    # CanvasService - create, update, export
      code_exec.py                 # CodeExecService - execute, download output
      file_upload.py               # FileUploadService - upload files for context
    cli.py                         # Thin CLI entry point - calls services directly
    mcp.py                         # Thin MCP server - calls services directly
    api.py                         # Phase 2: OpenAI + Anthropic API - calls services
  docs/
    research/                      # Research phase artifacts
    plans/
  tests/
```

**How changes flow:** When you need to update a feature (e.g., Gemini changes an RPC
or you add a new action), you edit the ONE service file. The `cli.py` and `mcp.py`
files are thin wrappers that just expose service methods as CLI commands and MCP tools.
They rarely need to change.

## Phase 0: Research (Before Any Production Code)

### Step 1: Extract from gemini-webapi (no browser needed)

- Catalog all 8 known RPC IDs, payloads, and response structures
- Document auth flow: cookies, SNlM0e token, cfb2h build label, FdrFJe session ID
- Document streaming protocol: length-prefixed frames, UTF-16 code unit counting
- Document model headers and model hashes
- Document error codes (1013, 1037, 1050, 1052, 1060)
- Document the batchexecute endpoint format
- Document the StreamGenerate endpoint for chat

### Step 2: Manual RPC capture for missing features

For each: Deep Research, Video Generation (Veo), Canvas, Code Execution:

- Open Chrome DevTools, filter Network to batchexecute and fetch/XHR
- Perform action in Gemini web UI
- Export HAR file to docs/research/captures/har/
- Extract RPC ID, request payload, response structure
- Document in docs/research/features/<feature>.md

### Step 3: Validate captures

- Replay each captured RPC with curl outside the browser
- Confirm auth tokens, payloads, and responses work

## Phase 1: Core + CLI + MCP

### Core Layer

- **RPCTransport**: httpx.AsyncClient, batchexecute protocol, streaming, retry with exponential backoff
- **ResponseParser**: Strip )]}' prefix, decode nested JSON, named field accessors, Pydantic models
- **AuthManager**: CDP via Chrome DevTools Protocol (headless Chrome), cross-product profile detection, background cookie refresh every ~9 minutes, 3-layer recovery
- **Chrome Profile Manager**: Multi-profile support with easy switching:
  - Storage: ~/.gemini-web-mcp-cli/profiles/<name>/auth.json
  - Default profile: "default"
  - First-run: detect NotebookLM MCP profiles, offer to reuse/link
  - Profile operations: create, list, switch, delete, import
  - Active profile persisted in ~/.gemini-web-mcp-cli/config.json
  - Environment variable override: GEMCLI_PROFILE=work

### CLI (gemcli)

- Verb-first AND noun-first support
- Commands: login, chat, image, video, research, gems, canvas, code, file, profile
- All generation commands support -o / --output for downloading results
- Global --profile flag on all commands

### MCP Server (8 Consolidated Tools)

| Tool     | Actions                         |
|----------|-------------------------------- |
| chat     | send, stream                    |
| image    | generate, edit, download        |
| video    | generate, status, download      |
| research | start, status, report, download |
| gems     | list, create, update, delete    |
| canvas   | create, update, export          |
| code     | execute, download               |
| file     | upload                          |

Each tool has comprehensive docstrings describing all actions and parameters.

## Phase 2 (Future): API Compatibility

- OpenAI-compatible: /v1/chat/completions with streaming
- Anthropic-compatible: /v1/messages with streaming
- Optional install extras: pip install gemini-web-mcp-cli[api]

## Tech Stack

- Python 3.11+
- MCP SDK: FastMCP
- HTTP: httpx (async)
- CLI: Click or Typer
- Models: Pydantic v2
- Auth: Chrome DevTools Protocol via WebSocket
- Logging: loguru
- Testing: pytest + pytest-asyncio
- Packaging: pyproject.toml with optional extras

## Known RPC Reference (from gemini-webapi)

| RPC ID   | Purpose              |
|----------|----------------------|
| MaZiqc   | List chats           |
| hNvQHb   | Read chat            |
| GzXR5e   | Delete chat          |
| CNgdBe   | List gems            |
| oMH3Zd   | Create gem           |
| kHv0Vd   | Update gem           |
| UXcSJb   | Delete gem           |
| ESY5D    | Enable Bard activity |
| TBD      | Deep Research        |
| TBD      | Video generation     |
| TBD      | Canvas operations    |
| TBD      | Code execution       |

**Endpoints:**

- batchexecute: https://gemini.google.com/_/BardChatUi/data/batchexecute
- StreamGenerate: https://gemini.google.com/assistant.lamda.BardFrontendService/StreamGenerate
- File upload: https://content-push.googleapis.com/upload
- Cookie refresh: https://accounts.google.com/RotateCookies

**Model hashes:**

- 9d8ca3786ebdfbea = Gemini 3.0 Pro
- fbb127bbb056c959 = Gemini 3.0 Flash
- 5bf011840784117a = Gemini 3.0 Flash Thinking
