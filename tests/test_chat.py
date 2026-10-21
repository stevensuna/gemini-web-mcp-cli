"""Tests for ChatService request forwarding."""

from unittest.mock import AsyncMock, MagicMock

from gemini_web_mcp_cli.core.models import StreamResponse
from gemini_web_mcp_cli.services.chat import ChatService


class TestChatServiceThinking:
    async def test_forwards_extended_thinking_toggle(self):
        client = MagicMock()
        client.send = AsyncMock(return_value=StreamResponse(text="ok"))
        service = ChatService(client)

        await service.send("hello", model="gemini-3.7-flash", extended_thinking=True)

        client.send.assert_awaited_once()
        assert client.send.await_args.kwargs["extended_thinking"] is True
