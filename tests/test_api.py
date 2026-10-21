"""Tests for the Anthropic-compatible API model controls."""

from unittest.mock import AsyncMock, MagicMock, patch

from gemini_web_mcp_cli.api.server import (
    MessagesRequest,
    create_message,
    resolve_model,
)
from gemini_web_mcp_cli.core.models import StreamResponse


def test_resolve_model_supports_gemini_37_flash():
    assert resolve_model("gemini-3.7-flash") == "fast"
    assert resolve_model("gemini-3.8-flash") == "fast"
    assert resolve_model("gemini-3.7-flash-extended") == "thinking"
    assert resolve_model("gemini-3.7-flash-thinking") == "thinking"
    assert resolve_model("gemini-4-argon") == "argon"


async def test_anthropic_thinking_field_enables_extended_thinking():
    request = MessagesRequest(
        model="gemini-3.7-flash",
        max_tokens=100,
        messages=[{"role": "user", "content": "hello"}],
        thinking={"type": "enabled", "budget_tokens": 1000},
    )
    client = MagicMock()
    client.send = AsyncMock(return_value=StreamResponse(text="ok"))

    with patch(
        "gemini_web_mcp_cli.api.server._get_client",
        new=AsyncMock(return_value=client),
    ):
        await create_message(request, MagicMock())

    assert client.send.await_args.kwargs["model"] == "fast"
    assert client.send.await_args.kwargs["extended_thinking"] is True
