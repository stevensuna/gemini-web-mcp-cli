"""Tests for high-level model resolution."""

import pytest

from gemini_web_mcp_cli.core.client import GeminiClient
from gemini_web_mcp_cli.core.constants import MODELS
from gemini_web_mcp_cli.core.exceptions import TokenFactoryError, UsageLimitExceeded


class TestModelResolution:
    def setup_method(self):
        self.client = GeminiClient.__new__(GeminiClient)

    def test_explicit_extended_thinking_wraps_flash_model(self):
        model = self.client._resolve_model("gemini-3.7-flash", extended_thinking=True)

        assert model.name == "fast"
        assert model.extended_thinking is True
        assert model.header["x-goog-ext-525001261-jspb"].endswith("null,null,1,2]")

    def test_legacy_thinking_alias_stays_extended_by_default(self):
        model = self.client._resolve_model("thinking")

        assert model == MODELS["thinking"]
        assert model.extended_thinking is True

    def test_thinking_level_medium_keeps_the_selected_model(self):
        model = self.client._resolve_model("gemini-4-argon", thinking_level="medium")

        assert model.name == "argon"
        assert model.header_tail == "8,4"
        assert model.thinking_level == "medium"

    def test_explicit_disable_turns_legacy_thinking_back_to_flash(self):
        model = self.client._resolve_model("thinking", extended_thinking=False)

        assert model == MODELS["fast"]
        assert model.extended_thinking is False


class _StubTransport:
    """Transport stub that records whether stream_generate was reached."""

    def __init__(self):
        self.called = False

    async def stream_generate(self, **kwargs):
        self.called = True
        return "fallback-response"


class TestSendFallback:
    """Tests for the Token Factory -> direct HTTP fallback policy in send()."""

    def _client(self, monkeypatch, error):
        client = GeminiClient.__new__(GeminiClient)
        transport = _StubTransport()
        client._transport = transport

        async def fake_send_via_token_factory(**kwargs):
            raise error

        monkeypatch.setattr(client, "_send_via_token_factory", fake_send_via_token_factory)
        return client, transport

    async def test_token_factory_error_falls_back_to_http(self, monkeypatch):
        client, transport = self._client(monkeypatch, TokenFactoryError("no chrome"))
        result = await client.send("hi")
        assert transport.called is True
        assert result == "fallback-response"

    async def test_usage_limit_does_not_fall_back(self, monkeypatch):
        """A disabled tool (usage limit) must surface, not retry over HTTP."""
        client, transport = self._client(monkeypatch, UsageLimitExceeded("tool disabled"))
        with pytest.raises(UsageLimitExceeded, match="disabled"):
            await client.send("hi", tool_id=11)
        assert transport.called is False


class TestBrowserCookieRpcBatching:
    """execute_rpc_with_browser_cookies delegates to the batched variant."""

    async def test_single_rpc_wraps_payload_list(self, monkeypatch):
        from gemini_web_mcp_cli.core.models import RPCPayload

        client = GeminiClient.__new__(GeminiClient)
        captured = {}

        async def fake_batch(payloads, source_path="/app"):
            captured["payloads"] = payloads
            captured["source_path"] = source_path
            return ["result"]

        monkeypatch.setattr(client, "execute_rpcs_with_browser_cookies", fake_batch)

        result = await client.execute_rpc_with_browser_cookies(
            "qpEbW", payload="[[[1,5]]]", source_path="/app/x"
        )

        assert result == ["result"]
        payloads = captured["payloads"]
        assert len(payloads) == 1
        assert isinstance(payloads[0], RPCPayload)
        assert payloads[0].rpc_id == "qpEbW"
        assert payloads[0].payload == "[[[1,5]]]"
        assert captured["source_path"] == "/app/x"


class TestNoSilentFallbackForAttachments:
    """Issue #6: attachments/tools must not be resent without Chrome's token."""

    def _client(self, monkeypatch):
        client = GeminiClient.__new__(GeminiClient)
        transport = _StubTransport()
        client._transport = transport

        async def fail(**kwargs):
            raise TokenFactoryError("capture failed")

        monkeypatch.setattr(client, "_send_via_token_factory", fail)
        return client, transport

    async def test_file_data_raises_instead_of_http_fallback(self, monkeypatch):
        client, transport = self._client(monkeypatch)
        with pytest.raises(TokenFactoryError, match="attachments"):
            await client.send("describe", file_data=[["file"]])
        assert transport.called is False

    async def test_tool_raises_instead_of_http_fallback(self, monkeypatch):
        client, transport = self._client(monkeypatch)
        with pytest.raises(TokenFactoryError, match="capture failed"):
            await client.send("a cat", tool_id=14)
        assert transport.called is False


class TestGenericErrorReply:
    """Gemini's generic failure text must not be returned as an answer."""

    def test_error_reply_raises(self):
        import pytest

        from gemini_web_mcp_cli.core.client import _check_reply
        from gemini_web_mcp_cli.core.exceptions import GeminiReplyError
        from gemini_web_mcp_cli.core.models import StreamResponse

        text = "I seem to be encountering an error. Can I try something else for you?"
        with pytest.raises(GeminiReplyError) as exc:
            _check_reply(StreamResponse(text=text))
        assert exc.value.reply == text

    def test_normal_and_long_replies_pass(self):
        from gemini_web_mcp_cli.core.client import _check_reply
        from gemini_web_mcp_cli.core.models import StreamResponse

        for text in ("ok", "", "Here is why 'Something went wrong' appears: " + "x" * 50,
                     "Something went wrong in your code. " + "Explanation. " * 30):
            r = StreamResponse(text=text)
            assert _check_reply(r) is r


class TestStreamGenerateRelayPrompt:
    """Issue #2: the relayed StreamGenerate body carries the full prompt."""

    async def test_multiline_prompt_patched_into_body(self, monkeypatch):
        import json
        from urllib.parse import parse_qs, urlencode

        import httpx

        from gemini_web_mcp_cli.core.client import GeminiClient
        from gemini_web_mcp_cli.core.constants import MODELS
        from gemini_web_mcp_cli.core.token_factory import CapturedRequest

        inner = [["Line one.", 0, None, None, None, None, 0], ["en"], None, "!bg", "h"]
        body = urlencode({"f.req": json.dumps([None, json.dumps(inner)]), "at": "AT"})
        captured = CapturedRequest(
            url="https://gemini.google.com/StreamGenerate", body=body, headers={},
            cookies={}, access_token="AT",
        )

        class _Factory:
            def capture(self, **kw):
                return captured

            def get_raw_cookies(self):
                return []

        sent = {}

        def handler(request):
            sent["body"] = request.content.decode()
            return httpx.Response(200, text=")]}'\n")

        client = GeminiClient.__new__(GeminiClient)
        client.timeout = 30
        client._browser_http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        monkeypatch.setattr(client, "_ensure_token_factory", lambda: _Factory(), raising=False)
        from gemini_web_mcp_cli.core import client as client_mod
        from gemini_web_mcp_cli.core.models import StreamResponse

        monkeypatch.setattr(client_mod, "build_stream_response",
                            lambda text: StreamResponse(text="ok"))
        client.profile_manager = None
        client.auth_manager = type("A", (), {"resolved_profile_name": "p"})()

        prompt = "Line one.\n\nLine two.\nLine three."
        await client._send_via_token_factory(prompt=prompt, model=MODELS["fast"])
        sent_inner = json.loads(json.loads(parse_qs(sent["body"])["f.req"][0])[1])
        assert sent_inner[0][0] == prompt
        assert sent_inner[3] == "!bg"
        await client._browser_http_client.aclose()
