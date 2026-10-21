"""Tests for the processSession (WebChannel) transport, using real captures.

Captures live in docs/research/transport/ (recorded 2026-09-29, redacted).
"""

import base64
import json
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

import httpx
import pytest

from gemini_web_mcp_cli.core import webchannel as wc
from gemini_web_mcp_cli.core.constants import MODELS
from gemini_web_mcp_cli.core.exceptions import APIError
from gemini_web_mcp_cli.core.rpc import build_process_session_response

CAPTURES = Path(__file__).resolve().parents[1] / "docs" / "research" / "transport"


def _read(name: str) -> str:
    return (CAPTURES / name).read_text(encoding="utf-8")


def _exchange(name: str = "2026-09-29-chrome-exchange.json") -> list[dict]:
    return json.loads(_read(name))["requests"]


def _setup_post(requests: list[dict]) -> dict:
    return next(
        r for r in requests
        if "processSession" in r["url"] and "req0___data__" in (r.get("postData") or "")
        and wc.find_setup_message(wc.decode_forward_body(r["postData"])) is not None
    )


def _open_request(requests: list[dict]) -> dict:
    return next(r for r in requests if "X-HTTP-Session-Id" in r["url"])


def _frame(obj) -> str:
    text = json.dumps(obj, separators=(",", ":"), ensure_ascii=False)
    units = sum(2 if ord(c) > 0xFFFF else 1 for c in text)
    return f"{units}\n{text}"


class TestSplitFrames:
    def test_chrome_backchannel(self):
        entries, rest = wc.split_frames(_read("2026-09-29-chrome-backchannel.txt"))
        assert rest == ""
        assert entries[0] == (1, ["noop"])
        assert [a for a, _ in entries] == list(range(1, 12))
        assert wc.is_end_of_stream(entries[-1][1])

    def test_incomplete_frame_is_kept(self):
        text = _frame([[1, ["noop"]]]) + "30\n[[2,"
        entries, rest = wc.split_frames(text)
        assert entries == [(1, ["noop"])]
        assert rest == "30\n[[2,"

    def test_utf16_lengths(self):
        text = _frame([[5, ["😀 emoji"]]]) + _frame([[6, ["noop"]]])
        entries, rest = wc.split_frames(text)
        assert [a for a, _ in entries] == [5, 6]
        assert rest == ""


class TestResponseParsing:
    def test_chrome_answer(self):
        r = build_process_session_response(_read("2026-09-29-chrome-backchannel.txt"))
        assert r.text == "ok"
        assert r.metadata.cid == "c_3ebbf43957671b28"
        assert r.metadata.rid == "r_1621e1e8e2002ac2"
        assert r.server_model_hash == "56fdd199312815e2"
        assert r.is_complete
        assert len(r.candidates) == 1

    def test_python_replay_answer(self):
        r = build_process_session_response(_read("2026-09-29-python-replay-backchannel.txt"))
        assert r.text == "replay ok"

    def test_final_candidate_flag(self):
        entries, _ = wc.split_frames(_read("2026-09-29-chrome-backchannel.txt"))
        finals = [a for a, p in entries if wc.is_final_candidate(p)]
        assert finals == [7]

    def test_status_error(self):
        payload = {"__sm__": {"status": [[[3, "Invalid value (), Unexpected list.", []]]]}}
        assert wc.status_error(payload) == "status 3: Invalid value (), Unexpected list."
        assert wc.status_error(["noop"]) is None
        assert wc.status_error({"__sm__": {"status": [[[0, "", []]]]}}) is None


class TestForwardMessages:
    def test_decode_setup(self):
        setup = wc.find_setup_message(wc.decode_forward_body(_setup_post(_exchange())["postData"]))
        assert setup[0][0][1] == "56fdd199312815e2"
        inner = wc.setup_inner(setup)
        assert inner[0] == ["", 0, None, None, None, None, 0]
        assert inner[1] == ["en"]
        assert isinstance(inner[3], str) and inner[3].startswith("!")

    def test_extract_botguard(self):
        token, hash_val = wc.extract_botguard(_setup_post(_exchange())["postData"])
        assert token.startswith("!")
        assert hash_val == "6d59d7dd1a05bbe7ef958b3e9a4aca98"

    def test_extract_botguard_via_client(self):
        from gemini_web_mcp_cli.core.client import GeminiClient

        token, _ = GeminiClient._extract_botguard(_setup_post(_exchange())["postData"])
        assert token.startswith("!")

    def test_attachment_capture_uses_inner_0_3(self):
        requests = _exchange("2026-09-29-chrome-exchange-attachment.json")
        inner = wc.setup_inner(wc.find_setup_message(
            wc.decode_forward_body(_setup_post(requests)["postData"])
        ))
        (entry,) = inner[0][3]
        assert entry[0][1:] == [3, None, "text/plain"]
        assert entry[1] == "note.txt"

    def test_encode_roundtrip(self):
        msgs = [wc.prompt_message("héllo & = ?"), wc.HALF_CLOSE_MESSAGE]
        body = wc.encode_forward_body(msgs, ofs=1)
        fields = dict(parse_qsl(body))
        assert fields["count"] == "2" and fields["ofs"] == "1"
        assert wc.decode_forward_body(body) == msgs

    def test_prompt_message_shape(self):
        assert wc.prompt_message("hi") == [None, [1, None, None, None, None, None, None, None,
                                                  ["hi"]]]

    def test_set_conversation(self):
        inner = [None] * 99
        wc.set_conversation(inner, "fc89cc69651a6a98")
        assert inner[71] == ["c_fc89cc69651a6a98", None, None, None, None, None, None, ""]
        chrome_value = ["c_abc", None, None, None, None, None, None, "x"]
        inner[71] = list(chrome_value)
        wc.set_conversation(inner, "c_abc")
        assert inner[71] == chrome_value  # Chrome's own value is kept


class TestModelHeader:
    def _bin_header(self, url: str) -> str:
        headers = dict(parse_qsl(urlsplit(url).query))["$httpHeaders"]
        for line in headers.split("\r\n"):
            name, _, value = line.partition(":")
            if name.lower() == wc.MODEL_BIN_HEADER:
                return value
        raise AssertionError("no model header")

    def _fields(self, value: str) -> dict[int, bytes]:
        raw = base64.b64decode(value + "=" * (-len(value) % 4))
        return {f: v for f, _, v in wc._pb_fields(raw)}

    def test_captured_header_is_fast(self):
        fields = self._fields(self._bin_header(_open_request(_exchange())["url"]))
        assert fields[5][1:] == b"56fdd199312815e2"
        assert fields[15] == b"\x01" and fields[16] == b"\x01"

    def test_rewrite_to_pro(self):
        original = self._bin_header(_open_request(_exchange())["url"])
        pro = MODELS["pro"]
        rewritten = wc.rewrite_model_header(original, pro.hash, 3, 1)
        before, after = self._fields(original), self._fields(rewritten)
        assert after[5][1:] == pro.hash.encode()
        assert after[15] == b"\x03" and after[16] == b"\x01"
        assert {k: v for k, v in before.items() if k not in (5, 15, 16)} == \
               {k: v for k, v in after.items() if k not in (5, 15, 16)}

    def test_apply_model_updates_url_and_setup(self):
        requests = _exchange()
        url = _open_request(requests)["url"]
        setup = wc.find_setup_message(wc.decode_forward_body(_setup_post(requests)["postData"]))
        new_url = wc.apply_model(url, setup, MODELS["pro"].with_extended_thinking())
        fields = self._fields(self._bin_header(new_url))
        assert fields[5][1:] == b"e6fa609c3fa255c0"
        assert fields[15] == b"\x03" and fields[16] == b"\x02"
        assert setup[0][0][1] == "e6fa609c3fa255c0"
        # other query parameters survive
        old_q = dict(parse_qsl(urlsplit(url).query))
        new_q = dict(parse_qsl(urlsplit(new_url).query))
        assert {k: v for k, v in old_q.items() if k != "$httpHeaders"} == \
               {k: v for k, v in new_q.items() if k != "$httpHeaders"}

    def test_unspecified_model_leaves_url(self):
        url = _open_request(_exchange())["url"]
        assert wc.apply_model(url, [[[1, "x"]]], MODELS["unspecified"]) == url


class _FakeServer:
    """Minimal processSession server for replay() tests."""

    def __init__(self, backchannel: str, after_half_close: str = ""):
        self.backchannel = backchannel
        self.after_half_close = after_half_close
        self.posts: list[tuple[dict, str]] = []
        self.gets = 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        q = dict(parse_qsl(request.url.query.decode()))
        if request.method == "GET":
            self.gets += 1
            if self.gets == 1:
                return httpx.Response(200, text=self.backchannel)
            half_closed = any("___data__" in b and wc.decode_forward_body(b) ==
                              [wc.HALF_CLOSE_MESSAGE] for _, b in self.posts)
            return httpx.Response(200, text=self.after_half_close if half_closed else "")
        body = request.content.decode()
        self.posts.append((q, body))
        if "X-HTTP-Session-Id" in q:
            return httpx.Response(
                200, text=_frame([[0, ["c", "SID123", "", 8, 15, 30000]]]) + "\n",
                headers={"x-http-session-id": "GSID"},
            )
        return httpx.Response(200, text="8\n[1,1,7]\n")


def _open_url() -> str:
    return _open_request(_exchange())["url"]


class TestReplay:
    async def test_replay_returns_answer_and_closes(self):
        # Split the real stream where Chrome half-closed: the server's last two
        # frames (seq 8 and end-of-stream) only arrive after the half-close.
        text = _read("2026-09-29-chrome-backchannel.txt")
        entries, _ = wc.split_frames(text)
        before = "".join(_frame([[a, p]]) for a, p in entries[:-2])
        after = "".join(_frame([[a, p]]) for a, p in entries[-2:])
        server = _FakeServer(before, after_half_close=after)
        setup = wc.find_setup_message(wc.decode_forward_body(_setup_post(_exchange())["postData"]))
        async with httpx.AsyncClient(transport=httpx.MockTransport(server)) as client:
            transcript = await wc.replay(
                client, _open_url(), [setup, wc.prompt_message("hi")],
                cookies={}, headers={"user-agent": "UA"}, timeout=10,
            )
        assert build_process_session_response(transcript).text == "ok"
        kinds = [(q.get("TYPE"), wc.decode_forward_body(b) if "___data__" in b else b)
                 for q, b in server.posts]
        assert kinds[0] == (None, "count=0")  # channel open
        assert kinds[1][1] == [setup, wc.prompt_message("hi")]
        assert kinds[2][1] == [wc.HALF_CLOSE_MESSAGE]
        assert kinds[-1][0] == "terminate"
        assert server.gets == 2  # reopened once, after the half-close
        data_q = server.posts[1][0]
        assert data_q["SID"] == "SID123" and data_q["gsessionid"] == "GSID"

    async def test_server_error_raises(self):
        err = _frame([[1, ["noop"]]]) + _frame([[2, {"__sm__": {"status": [[[3, "bad", []]]]}}]]) \
            + _frame([[3, ["close"]]])
        server = _FakeServer(err)
        async with httpx.AsyncClient(transport=httpx.MockTransport(server)) as client:
            with pytest.raises(APIError, match="status 3: bad"):
                await wc.replay(client, _open_url(), [wc.prompt_message("hi")],
                                cookies={}, headers={}, timeout=10)
        assert server.posts[-1][0].get("TYPE") == "terminate"

    async def test_end_of_stream_without_half_close(self):
        """If the server ends the stream itself, no half-close is needed."""
        server = _FakeServer(_read("2026-09-29-chrome-backchannel.txt"))
        async with httpx.AsyncClient(transport=httpx.MockTransport(server)) as client:
            transcript = await wc.replay(client, _open_url(), [wc.prompt_message("hi")],
                                         cookies={}, headers={}, timeout=10)
        assert build_process_session_response(transcript).text == "ok"
        assert server.gets == 1

    async def test_close_without_answer_raises(self):
        server = _FakeServer(_frame([[1, ["noop"]]]) + _frame([[2, ["close"]]]))
        async with httpx.AsyncClient(transport=httpx.MockTransport(server)) as client:
            with pytest.raises(APIError, match="without an answer"):
                await wc.replay(client, _open_url(), [wc.prompt_message("hi")],
                                cookies={}, headers={}, timeout=10)

    async def test_open_rejected_raises_auth_error(self):
        from gemini_web_mcp_cli.core.exceptions import AuthError

        def handler(request):
            return httpx.Response(401, text="")

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(AuthError):
                await wc.replay(client, _open_url(), [], cookies={}, headers={}, timeout=5)


class TestClientReplay:
    async def test_patches_model_files_and_conversation(self, monkeypatch):
        from gemini_web_mcp_cli.core.client import GeminiClient
        from gemini_web_mcp_cli.core.models import ConversationMetadata
        from gemini_web_mcp_cli.core.token_factory import CapturedRequest

        requests = _exchange()
        captured = CapturedRequest(
            url=_open_url(), body=_setup_post(requests)["postData"], headers={},
            cookies={}, transport=wc.TRANSPORT_PROCESS_SESSION,
        )
        seen = {}

        async def fake_replay(client, open_url, messages, cookies, headers, timeout):
            seen.update(open_url=open_url, messages=messages)
            return _read("2026-09-29-chrome-backchannel.txt")

        monkeypatch.setattr(wc, "replay", fake_replay)
        client = GeminiClient.__new__(GeminiClient)
        client._browser_http_client = None
        client.timeout = 30
        file_data = [[["/contrib_service/x", 3, None, "text/plain"], "a.txt",
                      None, None, None, None, None, None, [0]]]
        result = await client._replay_process_session(
            captured, "real prompt", MODELS["pro"], file_data,
            ConversationMetadata(cid="c_abc", rid="r_1"),
        )
        assert result.text == "ok"
        setup, prompt = seen["messages"]
        inner = wc.setup_inner(setup)
        assert inner[0][3] == file_data
        assert inner[3].startswith("!")  # BotGuard token untouched
        assert inner[71][0] == "c_abc"
        assert setup[0][0][1] == MODELS["pro"].hash
        assert prompt == wc.prompt_message("real prompt")


class TestResponseMetadataAndLabel:
    def test_rcid_and_versioned_label(self):
        r = build_process_session_response(_read("2026-09-29-chrome-backchannel.txt"))
        assert r.metadata.rcid == "rc_d4773a462a07d0a2"
        assert r.server_model_label == "3.8 Flash"

    def test_label_shapes(self):
        from gemini_web_mcp_cli.core.parser import _is_model_label

        for label in ("3.8 Flash", "3.1 Pro", "3.5 Flash-Lite", "4 Thinking", "Fast"):
            assert _is_model_label(label), label
        for label in ("Flash 3.8", "en", "3.8", "3.8 Flash!"):
            assert not _is_model_label(label), label


class TestBinarySetup:
    """Some accounts' pages encode the setup as binary protobuf (2026-09-29)."""

    @staticmethod
    def _diffs(json_value, converted, path="inner", top=True):
        """Structural differences, ignoring string contents and per-request ids."""
        out = []
        if isinstance(json_value, list) and isinstance(converted, list):
            for i in range(max(len(json_value), len(converted))):
                if top and i in (3, 4, 59):  # BotGuard token, challenge hash, session UUID
                    continue
                a = json_value[i] if i < len(json_value) else None
                b = converted[i] if i < len(converted) else None
                out += TestBinarySetup._diffs(a, b, f"{path}[{i}]", top=False)
        elif json_value != converted and not (
            isinstance(json_value, str) and isinstance(converted, str)
        ):
            out.append((path, json_value, converted))
        return out

    @pytest.mark.parametrize("tool", ["chat", "image", "music", "video"])
    def test_binary_setup_matches_json_schema(self, tool):
        setup = wc.decode_message(_read(f"2026-09-29-binary-setup-{tool}.b64").strip())
        inner = wc.setup_inner(setup)
        truth = json.loads(_read(f"2026-09-29-streamgenerate-inner-{tool}.json"))
        assert self._diffs(truth, inner) == []
        assert inner[3].startswith("!")  # BotGuard token decoded as text

    def test_image_aspect_ids_are_ints_not_text(self):
        """0x3d is both '=' and 61 (the 1:1 aspect id); the shape must pick int."""
        b64 = _read("2026-09-29-binary-setup-image.b64").strip()
        inner = wc.setup_inner(wc.decode_message(b64))
        assert inner[55] == [[61]]

    def test_decode_forward_body_accepts_binary(self):
        from urllib.parse import urlencode

        b64 = _read("2026-09-29-binary-setup-chat.b64").strip()
        body = urlencode({"count": 1, "ofs": 0, "req0___data__": b64})
        token, hash_val = wc.extract_botguard(body)
        assert token.startswith("!") and hash_val

    def test_use_json_encoding(self):
        url = _open_url().replace(
            "application%2Fjson%2Bprotobuf", "application%2Fx-protobuf"
        )
        assert "x-protobuf" in dict(parse_qsl(urlsplit(url).query))["$httpHeaders"]
        fixed = dict(parse_qsl(urlsplit(wc.use_json_encoding(url)).query))["$httpHeaders"]
        assert "X-WebChannel-Content-Type:application/json+protobuf" in fixed
        assert "x-protobuf" not in fixed

    def test_garbage_message_raises_value_error(self):
        with pytest.raises(ValueError):
            wc.decode_message("not json and not base64 ***")


class TestProtoJspb:
    def test_packed_vs_message_vs_text(self):
        from gemini_web_mcp_cli.core.protojspb import to_jspb

        # field1 = message{1: 5}; field2 = "hi"; field3 = packed [4, 16]; field4 = 7
        b = bytes([0x0A, 0x02, 0x08, 0x05, 0x12, 0x02]) + b"hi" + bytes([0x1A, 0x02, 0x04, 0x10,
                                                                          0x20, 0x07])
        assert to_jspb(b) == [[5], "hi", [4, 16], 7]

    def test_shape_forces_int_for_printable_bytes(self):
        from gemini_web_mcp_cli.core.protojspb import to_jspb

        b = bytes([0x0A, 0x01, 0x3D])  # field1 = b"=" (or packed [61])
        assert to_jspb(b) == ["="]
        assert to_jspb(b, [[0]]) == [[61]]

    def test_empty_values(self):
        from gemini_web_mcp_cli.core.protojspb import to_jspb

        b = bytes([0x0A, 0x00, 0x12, 0x00])
        assert to_jspb(b, ["", None]) == ["", []]

    def test_repeated_fields_become_lists(self):
        from gemini_web_mcp_cli.core.protojspb import to_jspb

        b = bytes([0x0A, 0x01]) + b"a" + bytes([0x0A, 0x01]) + b"b"
        assert to_jspb(b) == [["a", "b"]]
