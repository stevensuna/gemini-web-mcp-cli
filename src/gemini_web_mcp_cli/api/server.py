"""Anthropic Messages API-compatible server backed by Gemini.

Allows Claude Code and other Anthropic SDK clients to use Gemini models
as a backend through a local API server.

Supported endpoints:
- POST /v1/messages      Anthropic Messages API (streaming + non-streaming)
- GET  /v1/models        List available Gemini models
- POST /v1/messages/count_tokens  Token counting (stub)
- GET  /health           Health check

Usage with Claude Code:
    export ANTHROPIC_BASE_URL=http://localhost:8082
    export ANTHROPIC_API_KEY=gemini
    claude --model gemini-auto
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import uuid
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("gemini-api")

ANTHROPIC_API_VERSION = "2023-06-01"


# =============================================================================
# Model Mapping
# =============================================================================

MODEL_MAP: dict[str, str] = {
    # Gemini native names
    "gemini-auto": "fast",
    "auto": "fast",
    "gemini-flash": "fast",
    "gemini-3.8-flash": "fast",
    "gemini-3.8-flash-thinking": "thinking",
    "gemini-3.8-flash-extended": "thinking",
    "gemini-3.7-flash": "fast",
    "gemini-3.7-flash-thinking": "thinking",
    "gemini-3.6-flash": "fast",
    "gemini-3.5-flash": "fast",
    "gemini-3.0-flash": "fast",
    "gemini-3-flash": "fast",
    "flash": "fast",
    "gemini-flash-lite": "lite",
    "gemini-3.5-flash-lite": "lite",
    "gemini-3.1-flash-lite": "lite",
    "flash-lite": "lite",
    "lite": "lite",
    "gemini-pro": "pro",
    "gemini-3.5-pro": "pro",
    "gemini-3.1-pro": "pro",
    "gemini-3-pro": "pro",
    "gemini-3.1-omni": "pro",
    "gemini-omni": "pro",
    "omni": "pro",
    "pro": "pro",
    "gemini-thinking": "thinking",
    "gemini-3.6-thinking": "thinking",
    "gemini-3.5-thinking": "thinking",
    "gemini-3.7-flash-extended": "thinking",
    "gemini-3.5-flash-thinking": "thinking",
    "gemini-3.0-flash-thinking": "thinking",
    "gemini-3-flash-thinking": "thinking",
    "thinking": "thinking",
    "gemini-4-argon": "argon",
    "gemini-4": "argon",
    "argon": "argon",
    # Claude Code default model names -> graceful fallback to Flash
    "claude-sonnet-4-6": "fast",
    "claude-4-6-sonnet": "fast",
    "claude-sonnet-4-5": "fast",
    "claude-opus-4-6": "pro",
    "claude-opus-4-5": "pro",
    "claude-3-5-sonnet": "fast",
    "claude-3-opus": "pro",
    "claude-haiku": "fast",
    "claude": "fast",
    "sonnet": "fast",
    "opus": "pro",
}

AVAILABLE_MODELS = [
    {"id": "gemini-auto", "description": "Auto - Uses Gemini 3.8 Flash (fast, default)"},
    {"id": "gemini-3.8-flash", "description": "Gemini 3.8 Flash - Fast responses"},
    {"id": "gemini-3.7-flash", "description": "Gemini 3.8 Flash - Fast responses (3.7 alias)"},
    {"id": "gemini-4-argon", "description": "Gemini 4 Argon - Complex tasks"},
    {"id": "gemini-flash", "description": "Gemini 3.8 Flash - Fast responses (alias)"},
    {"id": "gemini-flash-lite", "description": "Gemini 3.5 Flash-Lite - Fastest, lowest cost"},
    {"id": "gemini-pro", "description": "Gemini 3.1 Pro (Omni) - Advanced reasoning"},
    {"id": "gemini-omni", "description": "Gemini 3.1 Pro (Omni) - Advanced reasoning"},
    {
        "id": "gemini-3.7-flash-extended",
        "description": "Gemini 3.8 Flash with Thinking level High",
    },
    {
        "id": "gemini-thinking",
        "description": "Gemini 3.8 Flash High thinking - Step-by-step reasoning (alias)",
    },
]


def resolve_model(name: str) -> str:
    """Map any model name to a Gemini model key."""
    key = name.lower().strip()
    if key in MODEL_MAP:
        return MODEL_MAP[key]
    logger.warning(f"Unknown model '{name}', falling back to flash")
    return "fast"


# =============================================================================
# Pydantic Models (Anthropic Messages API format)
# =============================================================================

class MessageParam(BaseModel):
    role: str
    content: str | list[dict[str, Any]]

    model_config = ConfigDict(extra="allow")

    def get_text(self) -> str:
        if isinstance(self.content, str):
            return self.content
        texts = []
        for block in self.content:
            if isinstance(block, dict) and block.get("type") == "text":
                texts.append(block.get("text", ""))
        return "\n".join(texts)


class MessagesRequest(BaseModel):
    model: str = Field(..., description="Model to use")
    max_tokens: int = Field(..., description="Maximum tokens to generate")
    messages: list[MessageParam] = Field(..., description="Conversation messages")
    system: str | list[dict[str, Any]] | None = Field(None)
    stream: bool = Field(False)
    temperature: float | None = Field(None)
    top_p: float | None = Field(None)
    stop_sequences: list[str] | None = Field(None)
    metadata: dict[str, Any] | None = Field(None)
    thinking: dict[str, Any] | None = Field(None, description="Extended thinking config")

    model_config = ConfigDict(extra="allow")


# =============================================================================
# Gemini Client Singleton
# =============================================================================

_client = None
_client_lock = asyncio.Lock()


async def _get_client():
    global _client
    async with _client_lock:
        if _client is None:
            from gemini_web_mcp_cli.core.client import GeminiClient
            from gemini_web_mcp_cli.core.profiles import ProfileManager

            pm = ProfileManager()
            profile_name = pm.get_active_profile()
            _client = GeminiClient(profile_name=profile_name)
            await _client.init()
        return _client


# =============================================================================
# FastAPI App
# =============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Gemini API server starting...")
    yield
    global _client
    if _client:
        await _client.close()
        _client = None
    logger.info("Gemini API server stopped.")


app = FastAPI(title="Gemini API Server", lifespan=lifespan)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/v1/models")
async def list_models():
    return {
        "data": [
            {
                "id": m["id"],
                "object": "model",
                "created": 1709000000,
                "owned_by": "google",
                "description": m["description"],
            }
            for m in AVAILABLE_MODELS
        ]
    }


@app.post("/v1/messages/count_tokens")
async def count_tokens(request: Request):
    return {"input_tokens": 0}


@app.post("/v1/messages")
async def create_message(req: MessagesRequest, request: Request):
    """Anthropic Messages API endpoint."""
    gemini_model = resolve_model(req.model)

    # Build prompt from messages
    system_text = ""
    if req.system:
        if isinstance(req.system, str):
            system_text = req.system
        elif isinstance(req.system, list):
            parts = []
            for block in req.system:
                if isinstance(block, dict) and block.get("type") == "text":
                    parts.append(block.get("text", ""))
            system_text = "\n".join(parts)

    # Collect conversation turns, stripping Claude Code internal placeholders
    turns = []
    for msg in req.messages:
        text = msg.get_text()
        if not text:
            continue
        # Claude Code sends this placeholder when truncating history / switching models
        if "[PAST CONVERSATION HISTORY]" in text:
            text = text.replace("[PAST CONVERSATION HISTORY]", "").strip()
            if not text:
                continue
        turns.append({"role": msg.role, "text": text})

    if not turns:
        raise HTTPException(status_code=400, detail="No message content found")

    # Strip Claude/Anthropic identity from system text so Gemini doesn't reject
    if system_text:
        system_text = re.sub(r'(?i)\bClaude\b', 'Gemini', system_text)
        system_text = re.sub(r'(?i)\banthropic\b', 'Google', system_text)

    # Build prompt: single turn or multi-turn transcript
    if len(turns) == 1:
        prompt = turns[0]["text"]
    else:
        transcript = []
        for t in turns[:-1]:
            role_name = "User" if t["role"] == "user" else "Assistant"
            transcript.append(f"{role_name}:\n{t['text']}")
        transcript.append(f"User:\n{turns[-1]['text']}")

        prompt = (
            "Here is our conversation history so far:\n\n"
            + "\n\n---\n\n".join(transcript[:-1])
            + "\n\n---\n\n"
            + "Please respond to my latest message:\n\n"
            + transcript[-1]
        )

    # Prepend system prompt as a separate block (not merged into transcript)
    if system_text:
        prompt = f"{system_text}\n\n{prompt}"

    # Tell Gemini which model it's running as
    model_names = {
        "fast": "Gemini 3.8 Flash",
        "lite": "Gemini 3.5 Flash-Lite",
        "pro": "Gemini 3.1 Pro (Omni)",
        "thinking": "Gemini 3.8 Flash High thinking",
        "argon": "Gemini 4 Argon",
    }
    model_display = model_names.get(gemini_model, gemini_model)
    prompt = f"You are currently running as {model_display}.\n\n{prompt}"

    # Call Gemini
    try:
        client = await _get_client()
        extended_thinking = None
        if req.thinking is not None:
            extended_thinking = req.thinking.get("type") != "disabled"
        response = await client.send(
            prompt=prompt,
            model=gemini_model,
            extended_thinking=extended_thinking,
        )
    except Exception as e:
        logger.error(f"Gemini error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

    response_text = response.text or ""
    msg_id = f"msg_{uuid.uuid4().hex[:24]}"

    if req.stream:
        return StreamingResponse(
            _stream_response(msg_id, req.model, response_text),
            media_type="text/event-stream",
        )

    # Non-streaming response
    return {
        "id": msg_id,
        "type": "message",
        "role": "assistant",
        "model": req.model,
        "content": [{"type": "text", "text": response_text}],
        "stop_reason": "end_turn",
        "stop_sequence": None,
        "usage": {
            "input_tokens": len(prompt) // 4,
            "output_tokens": len(response_text) // 4,
        },
    }


async def _stream_response(
    msg_id: str, model: str, text: str
) -> AsyncGenerator[str, None]:
    """Generate Anthropic-compatible SSE events."""
    # message_start
    yield _sse({
        "type": "message_start",
        "message": {
            "id": msg_id,
            "type": "message",
            "role": "assistant",
            "model": model,
            "content": [],
            "stop_reason": None,
            "stop_sequence": None,
            "usage": {"input_tokens": 0, "output_tokens": 0},
        },
    })

    # content_block_start
    yield _sse({
        "type": "content_block_start",
        "index": 0,
        "content_block": {"type": "text", "text": ""},
    })

    # Stream text in chunks
    chunk_size = 20
    for i in range(0, len(text), chunk_size):
        chunk = text[i:i + chunk_size]
        yield _sse({
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "text_delta", "text": chunk},
        })
        await asyncio.sleep(0.01)

    # content_block_stop
    yield _sse({"type": "content_block_stop", "index": 0})

    # message_delta
    yield _sse({
        "type": "message_delta",
        "delta": {"stop_reason": "end_turn", "stop_sequence": None},
        "usage": {"output_tokens": len(text) // 4},
    })

    # message_stop
    yield _sse({"type": "message_stop"})


def _sse(data: dict) -> str:
    return f"event: {data['type']}\ndata: {json.dumps(data)}\n\n"


# =============================================================================
# Entry point
# =============================================================================

def main():
    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "8082"))
    logger.info(f"Starting Gemini API server on {host}:{port}")
    uvicorn.run(app, host=host, port=port, log_level="warning")


if __name__ == "__main__":
    main()
