"""Tests for live-path probes (issue #5), attachment check (#6), browser path (#7)."""

from __future__ import annotations

import os

import pytest

from gemini_web_mcp_cli.core import probe
from gemini_web_mcp_cli.core.token_factory import CapturedRequest


def _body_with_botguard(token: str | None) -> str:
    import json
    from urllib.parse import quote

    inner = [None] * 5
    inner[3] = token
    f_req = json.dumps([None, json.dumps(inner)])
    return f"f.req={quote(f_req)}&at=x"


class _FakeFactory:
    captured: CapturedRequest | None = None
    error: Exception | None = None
    shut_down = False

    def __init__(self, chrome_profile_path=None, profile_name="default"):
        pass

    def capture(self, prompt, model, **kwargs):
        assert prompt == probe.PROBE_PROMPT
        if _FakeFactory.error:
            raise _FakeFactory.error
        return _FakeFactory.captured

    def shutdown(self):
        _FakeFactory.shut_down = True


@pytest.fixture
def fake_factory(monkeypatch):
    from gemini_web_mcp_cli.core import token_factory

    _FakeFactory.captured = None
    _FakeFactory.error = None
    _FakeFactory.shut_down = False
    monkeypatch.setattr(token_factory, "TokenFactory", _FakeFactory)
    return _FakeFactory


class TestTokenCaptureProbe:
    def test_ok_when_botguard_token_and_access_token_present(self, fake_factory):
        fake_factory.captured = CapturedRequest(
            url="u", body=_body_with_botguard("!bgtoken"), headers={}, cookies={},
            access_token="snlm0e",
        )
        result = probe.probe_token_capture("p", "/chrome/p")
        assert result.ok, result.detail
        assert fake_factory.shut_down

    def test_summary_names_transport(self, fake_factory):
        fake_factory.captured = CapturedRequest(
            url="u", body=_body_with_botguard("!bgtoken"), headers={}, cookies={},
            access_token="snlm0e",
        )
        result = probe.probe_token_capture("p", "/chrome/p")
        assert result.summary() == "ok"  # keepalive JSON "capture" stays "ok"
        assert result.transport == "streamgenerate"

    def test_ok_for_process_session_capture(self, fake_factory):
        from gemini_web_mcp_cli.core import webchannel as wc

        inner = [["", 0], ["en"], None, "!bg", "hash"]
        setup = [[[1, "56fdd199312815e2", "en", "U"], 0, None, None, None, None, None,
                  [None, None, None, None, [inner, None, None, 1]]]]
        fake_factory.captured = CapturedRequest(
            url="https://geminiweb-pa.clients6.google.com/v1/processSession?X-HTTP-Session-Id=g",
            body=wc.encode_forward_body([setup], 0), headers={}, cookies={},
            access_token="snlm0e", transport=wc.TRANSPORT_PROCESS_SESSION,
        )
        result = probe.probe_token_capture("p", "/chrome/p")
        assert result.ok, result.detail
        assert result.transport == "processSession"

    def test_fails_without_botguard_token(self, fake_factory):
        fake_factory.captured = CapturedRequest(
            url="u", body=_body_with_botguard(None), headers={}, cookies={},
            access_token="snlm0e",
        )
        result = probe.probe_token_capture("p", "/chrome/p")
        assert not result.ok
        assert "BotGuard" in result.detail

    def test_reports_failing_stage(self, fake_factory):
        from gemini_web_mcp_cli.core.exceptions import TokenFactoryError

        fake_factory.error = TokenFactoryError("Failed to capture BotGuard token after retry.")
        result = probe.probe_token_capture("p", "/chrome/p")
        assert not result.ok
        assert result.summary().startswith("failed: TokenFactoryError")
        assert fake_factory.shut_down

    def test_no_chrome_profile(self):
        result = probe.probe_token_capture("p", None)
        assert not result.ok and "login" in result.detail

    def test_busy_profile_is_reported_as_busy(self, fake_factory):
        import threading

        from gemini_web_mcp_cli.core.locks import profile_lock

        held, release = threading.Event(), threading.Event()

        def holder():
            with profile_lock("p"):
                held.set()
                release.wait(5)

        t = threading.Thread(target=holder)
        t.start()
        held.wait(5)
        try:
            result = probe.probe_token_capture("p", "/chrome/p", lock_timeout=0.2)
        finally:
            release.set()
            t.join()
        assert not result.ok and result.detail == "busy"


class TestAttachmentNotRead:
    @pytest.mark.parametrize("text", [
        "I'm sorry, but I can't open the attached file. However, here's a breakdown...",
        "I am unable to view the video you uploaded.",
        "I cannot access the attachment. Based on the filename...",
        "It looks like no file was attached to your message.",
        "I couldn't play the video, but typically such clips...",
        "I don't see any file attached.",
    ])
    def test_detects_unread_attachment(self, text):
        from gemini_web_mcp_cli.services.chat import attachment_not_read

        assert attachment_not_read(text)

    @pytest.mark.parametrize("text", [
        "The video shows a cat jumping onto a table, then knocking over a glass.",
        "Here is the summary of the PDF: revenue grew 12% year over year.",
        "",
        # Mentioned only far into a long, real answer
        "x" * 700 + " I can't open the file you mentioned in the video.",
    ])
    def test_normal_answers_pass(self, text):
        from gemini_web_mcp_cli.services.chat import attachment_not_read

        assert not attachment_not_read(text)

    async def test_chat_service_raises_with_reply(self, monkeypatch, tmp_path):
        from gemini_web_mcp_cli.core.exceptions import AttachmentNotRead
        from gemini_web_mcp_cli.services import chat, file

        clip = tmp_path / "clip.mp4"
        clip.write_bytes(b"x")

        async def fake_upload(self, path):
            return "/contrib_service/ttl_1d/abc"

        monkeypatch.setattr(file.FileService, "upload", fake_upload)

        class _Resp:
            text = "I can't open the attached video. Generally, such videos show..."
            metadata = None

        class _Client:
            async def send(self, **kwargs):
                assert kwargs["file_data"]
                return _Resp()

        svc = chat.ChatService(_Client())
        with pytest.raises(AttachmentNotRead) as exc:
            await svc.send("describe", files=[str(clip)])
        assert "clip.mp4" in str(exc.value)
        assert exc.value.reply.startswith("I can't open")

        monkeypatch.setenv("GEMCLI_ATTACHMENT_CHECK", "0")
        assert (await svc.send("describe", files=[str(clip)])).text.startswith("I can't")

    async def test_no_check_without_files(self):
        from gemini_web_mcp_cli.services import chat

        class _Resp:
            text = "I can't open the file, you didn't attach one."
            metadata = None

        class _Client:
            async def send(self, **kwargs):
                return _Resp()

        assert (await chat.ChatService(_Client()).send("hi")).text


class TestBrowserPath:
    def _reset(self, monkeypatch):
        from gemini_web_mcp_cli.core import cdp

        monkeypatch.setattr(cdp, "_detected_browser", None)
        monkeypatch.setattr(cdp, "_detected_preference", None)
        return cdp

    def test_env_path_is_used_and_keeps_case(self, monkeypatch, tmp_path):
        cdp = self._reset(monkeypatch)
        binary = tmp_path / "Chrome For Testing"
        binary.write_text("#!/bin/sh\n")
        os.chmod(binary, 0o755)
        monkeypatch.setenv("GEMCLI_BROWSER", str(binary))

        result = cdp._find_browser_binary()

        assert result.path == str(binary)
        assert result.name == "Chrome For Testing"

    def test_missing_path_falls_back_to_auto(self, monkeypatch, tmp_path):
        cdp = self._reset(monkeypatch)
        monkeypatch.setenv("GEMCLI_BROWSER", str(tmp_path / "nope"))
        monkeypatch.setattr(cdp, "_search_candidates", lambda c, names: None)
        assert cdp._find_browser_binary() is None

    def test_names_still_lowercased(self, monkeypatch):
        cdp = self._reset(monkeypatch)
        monkeypatch.setenv("GEMCLI_BROWSER", "Brave")
        assert cdp._get_preferred_browser() == "brave"
