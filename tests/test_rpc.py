"""Tests for the RPC transport layer."""

import json
from urllib.parse import parse_qs, unquote

import orjson

from gemini_web_mcp_cli.core.constants import GEMINI_HEADERS, Model
from gemini_web_mcp_cli.core.models import ConversationMetadata, RPCPayload
from gemini_web_mcp_cli.core.rpc import (
    build_batchexecute_body,
    build_batchexecute_url,
    build_headers,
    build_stream_response,
    build_streamgenerate_body,
    build_streamgenerate_url,
)


class TestRPCPayload:
    def test_serialize(self):
        p = RPCPayload(rpc_id="MaZiqc", payload="[]")
        result = p.serialize()
        assert result == ["MaZiqc", "[]", None, "generic"]

    def test_serialize_custom_identifier(self):
        p = RPCPayload(rpc_id="test", payload='["arg"]', identifier="custom")
        result = p.serialize()
        assert result == ["test", '["arg"]', None, "custom"]


class TestConversationMetadata:
    def test_default_to_list(self):
        meta = ConversationMetadata()
        result = meta.to_list()
        assert len(result) == 10
        assert result[0] == ""
        assert result[1] == ""
        assert result[2] == ""

    def test_from_list(self):
        data = ["c_abc", "r_def", "rc_ghi", None, None, None, None, None, None, None]
        meta = ConversationMetadata.from_list(data)
        assert meta.cid == "c_abc"
        assert meta.rid == "r_def"
        assert meta.rcid == "rc_ghi"

    def test_from_list_short(self):
        meta = ConversationMetadata.from_list(["c_x", "r_y"])
        assert meta.cid == "c_x"
        assert meta.rid == "r_y"
        assert meta.rcid == ""

    def test_from_list_none(self):
        meta = ConversationMetadata.from_list(None)
        assert meta.cid == ""

    def test_roundtrip(self):
        original = ["c_1", "r_2", "rc_3", None, None, None, None, None, None, None]
        meta = ConversationMetadata.from_list(original)
        result = meta.to_list()
        assert result[0] == "c_1"
        assert result[1] == "r_2"
        assert result[2] == "rc_3"
        assert len(result) == 10


class TestBuildBatchexecuteUrl:
    def test_basic_url(self):
        url = build_batchexecute_url(
            rpc_ids=["MaZiqc"],
            reqid=12345,
            build_label="bl_test",
            session_id="sid_test",
        )
        assert "batchexecute" in url
        assert "rpcids=MaZiqc" in url
        assert "_reqid=12345" in url
        assert "bl=bl_test" in url
        assert "f.sid=sid_test" in url
        assert "rt=c" in url

    def test_multiple_rpc_ids(self):
        url = build_batchexecute_url(
            rpc_ids=["MaZiqc", "GzXR5e"],
            reqid=99999,
        )
        assert "MaZiqc" in url
        assert "GzXR5e" in url

    def test_no_optional_params(self):
        url = build_batchexecute_url(rpc_ids=["test"], reqid=1)
        assert "bl=" not in url
        assert "f.sid=" not in url


class TestBuildBatchexecuteBody:
    def test_body_format(self):
        payloads = [RPCPayload(rpc_id="MaZiqc")]
        body = build_batchexecute_body(payloads, access_token="token123")
        assert "f.req=" in body
        assert "at=" in body
        assert "token123" in body

    def test_body_contains_rpc_id(self):
        payloads = [RPCPayload(rpc_id="MaZiqc", payload="[]")]
        body = build_batchexecute_body(payloads, access_token="t")
        decoded = unquote(body)
        assert "MaZiqc" in decoded

    def test_body_parseable(self):
        payloads = [RPCPayload(rpc_id="test", payload='["arg1"]')]
        body = build_batchexecute_body(payloads, access_token="tok")
        # Body ends with &
        assert body.endswith("&")
        # Can parse the f.req field
        parts = parse_qs(body.rstrip("&"))
        f_req = parts["f.req"][0]
        parsed = json.loads(f_req)
        assert isinstance(parsed, list)
        assert parsed[0][0][0] == "test"


class TestBuildStreamgenerateUrl:
    def test_basic_url(self):
        url = build_streamgenerate_url(
            reqid=54321,
            build_label="bl_test",
            session_id="sid_test",
        )
        assert "StreamGenerate" in url
        assert "_reqid=54321" in url
        assert "bl=bl_test" in url

    def test_no_optional_params(self):
        url = build_streamgenerate_url(reqid=1)
        assert "StreamGenerate" in url
        assert "bl=" not in url


class TestBuildStreamgenerateBody:
    def test_body_format(self):
        body = build_streamgenerate_body(
            prompt="Hello world",
            access_token="token123",
        )
        assert "f.req=" in body
        assert "at=" in body

    def test_body_contains_prompt(self):
        body = build_streamgenerate_body(
            prompt="test_prompt",
            access_token="tok",
        )
        decoded = unquote(body)
        assert "test_prompt" in decoded

    def test_body_with_metadata(self):
        meta = ConversationMetadata(cid="c_123", rid="r_456", rcid="rc_789")
        body = build_streamgenerate_body(
            prompt="follow up",
            access_token="tok",
            metadata=meta,
        )
        decoded = unquote(body)
        assert "c_123" in decoded
        assert "r_456" in decoded

    def test_body_with_gem_id(self):
        body = build_streamgenerate_body(
            prompt="hello",
            access_token="tok",
            gem_id="gem_abc",
        )
        decoded = unquote(body)
        assert "gem_abc" in decoded

    def test_inner_req_list_structure(self):
        body = build_streamgenerate_body(
            prompt="test",
            access_token="tok",
        )
        parts = parse_qs(body.rstrip("&"))
        f_req = parts["f.req"][0]
        outer = json.loads(f_req)
        assert outer[0] is None  # First element is null
        inner = json.loads(outer[1])
        assert len(inner) == 70
        assert inner[0][0] == "test"  # prompt
        assert inner[7] == 1  # snapshot streaming

    def test_video_orientation_landscape_fields(self):
        """Landscape writes inner[55]=[[16]] and flag 1 in inner[0][9]."""
        body = build_streamgenerate_body(
            prompt="a video",
            access_token="tok",
            tool_id=11,
            video_orientation="landscape",
        )
        inner = json.loads(json.loads(parse_qs(body.rstrip("&"))["f.req"][0])[1])
        assert inner[49] == 11
        assert inner[54] == []
        assert inner[55] == [[16]]
        assert inner[0][9] == [
            None, None, None, None, None, None, [[None, None, None, 1]]
        ]

    def test_video_orientation_portrait_fields(self):
        """Portrait writes inner[55]=[[17]] and flag 2 in inner[0][9]."""
        body = build_streamgenerate_body(
            prompt="a video",
            access_token="tok",
            tool_id=11,
            video_orientation="portrait",
        )
        inner = json.loads(json.loads(parse_qs(body.rstrip("&"))["f.req"][0])[1])
        assert inner[55] == [[17]]
        assert inner[0][9][-1] == [[None, None, None, 2]]

    def test_video_orientation_aliases(self):
        """9:16 / 16:9 aliases normalize to the same field values."""
        body = build_streamgenerate_body(
            prompt="a video", access_token="tok", video_orientation="9:16"
        )
        inner = json.loads(json.loads(parse_qs(body.rstrip("&"))["f.req"][0])[1])
        assert inner[55] == [[17]]

    def test_image_aspect_fields(self):
        """Image aspect writes inner[55] id and label in inner[0][9]."""
        body = build_streamgenerate_body(
            prompt="a poster",
            access_token="tok",
            tool_id=14,
            image_aspect="16:9",
        )
        inner = json.loads(json.loads(parse_qs(body.rstrip("&"))["f.req"][0])[1])
        assert inner[49] == 14
        assert inner[54] == []
        assert inner[55] == [[63]]
        assert inner[0][9] == [
            None, None, None, None, None, None, [None, [None, "16:9"]]
        ]

    def test_image_aspect_aliases(self):
        body = build_streamgenerate_body(
            prompt="a poster", access_token="tok", image_aspect="square"
        )
        inner = json.loads(json.loads(parse_qs(body.rstrip("&"))["f.req"][0])[1])
        assert inner[55] == [[61]]

    def test_no_orientation_leaves_video_fields_unset(self):
        """Without orientation the Omni video fields stay absent."""
        body = build_streamgenerate_body(
            prompt="a video", access_token="tok", tool_id=11
        )
        inner = json.loads(json.loads(parse_qs(body.rstrip("&"))["f.req"][0])[1])
        assert inner[54] is None
        assert inner[55] is None
        assert len(inner[0]) == 7


class TestBuildHeaders:
    def test_default_headers(self):
        headers = build_headers()
        assert headers["Content-Type"] == GEMINI_HEADERS["Content-Type"]
        assert headers["X-Same-Domain"] == "1"

    def test_with_model(self):
        model = Model("test-model", "abc123hash")
        headers = build_headers(model)
        assert "x-goog-ext-525001261-jspb" in headers
        assert "abc123hash" in headers["x-goog-ext-525001261-jspb"]

    def test_extended_thinking_model_header(self):
        headers = build_headers(Model("fast", "hash", header_tail="1,2"))
        assert headers["x-goog-ext-525001261-jspb"].endswith("null,null,1,2]")

    def test_with_unspecified_model(self):
        model = Model("unspecified", None)
        headers = build_headers(model)
        assert "x-goog-ext-525001261-jspb" not in headers

    def test_does_not_mutate_gemini_headers(self):
        original_keys = set(GEMINI_HEADERS.keys())
        build_headers(Model("test", "hash"))
        assert set(GEMINI_HEADERS.keys()) == original_keys


class TestBuildStreamResponse:
    """Tests for the extracted build_stream_response() function."""

    def _make_response_text(self, inner: list) -> str:
        """Build a synthetic StreamGenerate response text."""
        inner_json = orjson.dumps(inner).decode()
        escaped = orjson.dumps(inner_json).decode()
        frame = f'[["wrb.fr",null,{escaped}]]'
        length = len(frame)
        prefix = ")]}'\n\n"
        return f"{prefix}{length}\n{frame}\n"

    def test_basic_text_response(self):
        """build_stream_response returns StreamResponse with text."""
        inner = [None] * 26
        inner[1] = ["c_test", "r_test"]
        inner[4] = [["rc_test", ["Hello world"]]]
        text = self._make_response_text(inner)

        result = build_stream_response(text)
        assert result.text == "Hello world"
        assert result.metadata.cid == "c_test"
        assert result.metadata.rid == "r_test"

    def test_candidates_populated(self):
        """build_stream_response populates candidates list."""
        inner = [None] * 26
        inner[1] = ["c_abc", "r_def"]
        inner[4] = [["rc_ghi", ["Some response"]]]
        text = self._make_response_text(inner)

        result = build_stream_response(text)
        assert len(result.candidates) == 1
        assert result.candidates[0].rcid == "rc_ghi"
        assert result.candidates[0].text == "Some response"

    def test_server_model_hash(self):
        """build_stream_response extracts server model hash."""
        inner = [None] * 45
        inner[1] = ["c_test", "r_test"]
        inner[4] = [["rc_test", ["Hi"]]]
        inner[40] = "e6fa609c3fa255c0"  # Pro hash
        inner[43] = "Pro"
        text = self._make_response_text(inner)

        result = build_stream_response(text)
        assert result.server_model_hash == "e6fa609c3fa255c0"
        assert result.server_model_label == "Pro"

    def test_empty_response(self):
        """build_stream_response handles response with no wrb.fr frames."""
        text = ")]}'\n\n25\n" + '[["e",4,null,null,154]]\n'
        result = build_stream_response(text)
        assert result.text is None
        assert result.candidates == []

    def test_returns_stream_response_type(self):
        """build_stream_response returns a StreamResponse instance."""
        inner = [None] * 26
        inner[1] = ["c_1", "r_2"]
        text = self._make_response_text(inner)

        from gemini_web_mcp_cli.core.models import StreamResponse
        result = build_stream_response(text)
        assert isinstance(result, StreamResponse)
