"""Tests for the response parser."""

import orjson

from gemini_web_mcp_cli.core.parser import (
    extract_json_from_response,
    get_nested,
    parse_batchexecute_response,
    parse_frames,
    parse_stream_response,
    strip_jsonp_prefix,
)

# Real captured response data (aPya6c status poll)
REAL_BATCH_RESPONSE = (
    ")]}'\n"
    "\n"
    "118\n"
    '[["wrb.fr","aPya6c","[false,0,[]]",null,null,null,"generic"],'
    '["di",137],["af.httprm",136,"-1524930634004383351",16]]\n'
    "25\n"
    '[["e",4,null,null,154]]\n'
)


class TestStripJsonpPrefix:
    def test_strips_prefix(self):
        assert strip_jsonp_prefix(")]}'") == ""

    def test_strips_prefix_with_content(self):
        result = strip_jsonp_prefix(")]}'  \nsome content")
        assert "some content" in result

    def test_no_prefix_unchanged(self):
        assert strip_jsonp_prefix('{"a": 1}') == '{"a": 1}'

    def test_empty_string(self):
        assert strip_jsonp_prefix("") == ""


class TestParseFrames:
    def test_single_frame(self):
        content = '7\n["hi"]\n'
        frames, remainder = parse_frames(content)
        assert len(frames) >= 1

    def test_real_batchexecute_response(self):
        """Test with actual captured batchexecute response (aPya6c poll)."""
        # Strip the JSONP prefix first, like extract_json_from_response does
        content = strip_jsonp_prefix(REAL_BATCH_RESPONSE).lstrip()
        frames, remainder = parse_frames(content)
        assert len(frames) > 0
        # Find wrb.fr frames
        wrb_frames = [
            f for f in frames
            if isinstance(f, list) and len(f) > 0 and f[0] == "wrb.fr"
        ]
        assert len(wrb_frames) >= 1
        assert wrb_frames[0][1] == "aPya6c"
        assert wrb_frames[0][2] == "[false,0,[]]"

    def test_incomplete_frame_stays_in_buffer(self):
        content = "1000\nshort"
        frames, remainder = parse_frames(content)
        assert len(frames) == 0
        assert len(remainder) > 0

    def test_empty_content(self):
        frames, remainder = parse_frames("")
        assert frames == []
        assert remainder == ""

    def test_whitespace_only(self):
        frames, remainder = parse_frames("   \n  \n")
        assert frames == []


class TestExtractJson:
    def test_with_jsonp_prefix(self):
        result = extract_json_from_response(REAL_BATCH_RESPONSE)
        assert len(result) > 0

    def test_plain_json_array(self):
        result = extract_json_from_response("[1, 2, 3]")
        assert result == [1, 2, 3]

    def test_plain_json_object(self):
        result = extract_json_from_response('{"a": 1}')
        assert result == [{"a": 1}]

    def test_ndjson_fallback(self):
        text = '{"a": 1}\n{"b": 2}\n'
        result = extract_json_from_response(text)
        assert len(result) == 2

    def test_invalid_json_raises(self):
        try:
            extract_json_from_response("not json at all xyz")
            assert False, "Should have raised ValueError"
        except ValueError:
            pass


class TestGetNested:
    def test_simple_list_access(self):
        data = [1, 2, [3, 4]]
        assert get_nested(data, [2, 1]) == 4

    def test_dict_access(self):
        data = {"a": {"b": 42}}
        assert get_nested(data, ["a", "b"]) == 42

    def test_out_of_bounds_returns_default(self):
        data = [1, 2]
        assert get_nested(data, [5]) is None
        assert get_nested(data, [5], "fallback") == "fallback"

    def test_missing_key_returns_default(self):
        data = {"a": 1}
        assert get_nested(data, ["b"]) is None

    def test_deep_path(self):
        data = [[[[["deep"]]]]]
        assert get_nested(data, [0, 0, 0, 0, 0]) == "deep"

    def test_none_returns_default(self):
        data = [None, [1, 2]]
        assert get_nested(data, [0]) is None

    def test_empty_path_returns_data(self):
        data = {"x": 1}
        assert get_nested(data, []) == {"x": 1}

    def test_type_mismatch_returns_default(self):
        data = "string"
        assert get_nested(data, [0]) is None

    def test_negative_index(self):
        data = [10, 20, 30]
        assert get_nested(data, [-1]) == 30

    def test_sparse_dict_wrapped_in_list(self):
        """Google's sparse protobuf format: [{"field_num": value}]."""
        # candidate[12] = [{"7": [0], "8": [], "87": music_data}]
        data = [{"7": [0], "8": [], "87": [["track1"], ["track2"]]}]
        # 0-based index 6 → protobuf field 7 → dict key "7"
        assert get_nested(data, [6]) == [0]
        # 0-based index 7 → protobuf field 8 → dict key "8"
        assert get_nested(data, [7]) == []
        # 0-based index 86 → protobuf field 87 → dict key "87"
        assert get_nested(data, [86]) == [["track1"], ["track2"]]
        # Missing key returns default
        assert get_nested(data, [58]) is None

    def test_sparse_dict_in_nested_path(self):
        """Sparse dict at candidate[12] in a full candidate structure."""
        candidate = [None] * 13
        candidate[0] = "rcid"
        candidate[1] = ["text"]
        candidate[12] = [{"7": [0], "87": "music_here"}]
        # get_nested(candidate, [12, 86]) should find "music_here"
        assert get_nested(candidate, [12, 86]) == "music_here"
        assert get_nested(candidate, [0]) == "rcid"
        assert get_nested(candidate, [1, 0]) == "text"

    def test_sparse_dict_direct(self):
        """Direct dict (not wrapped in list) with protobuf field keys."""
        data = {"3": "value_at_field_3"}
        assert get_nested(data, [2]) == "value_at_field_3"
        assert get_nested(data, [5]) is None

    def test_sparse_dict_does_not_affect_normal_lists(self):
        """Normal lists with one element that's not a dict still work normally."""
        data = [42]
        assert get_nested(data, [0]) == 42
        assert get_nested(data, [1]) is None

    def test_sparse_dict_nested_traversal(self):
        """Sparse dict followed by normal list access."""
        data = [{"3": [[10, 20, 30]]}]
        assert get_nested(data, [2, 0, 1]) == 20


class TestParseBatchexecuteResponse:
    def test_real_aPya6c_response(self):
        results = parse_batchexecute_response(REAL_BATCH_RESPONSE)
        assert len(results) == 1
        assert results[0]["rpc_id"] == "aPya6c"
        assert results[0]["data"] == [False, 0, []]

    def test_no_wrb_fr_frames(self):
        text = ")]}'\n\n25\n" + '[["e",4,null,null,154]]\n'
        results = parse_batchexecute_response(text)
        assert len(results) == 0

    def test_null_rpc_id_streamgenerate_style(self):
        """StreamGenerate-style responses have null rpc_id."""
        inner_json = orjson.dumps([None, ["c_123", "r_456"]]).decode()
        escaped = orjson.dumps(inner_json).decode()
        frame = f'[["wrb.fr",null,{escaped}]]'
        length = len(frame)
        prefix = ")]}'\n\n"
        text = f"{prefix}{length}\n{frame}\n"
        results = parse_batchexecute_response(text)
        assert len(results) == 1
        assert results[0]["rpc_id"] is None


class TestParseStreamResponse:
    def _build_stream_response(self, inner: list) -> str:
        """Helper to build a synthetic stream response."""
        inner_json = orjson.dumps(inner).decode()
        escaped = orjson.dumps(inner_json).decode()
        frame = f'[["wrb.fr",null,{escaped}]]'
        length = len(frame)
        prefix = ")]}'\n\n"
        return f"{prefix}{length}\n{frame}\n"

    def test_extracts_text_from_candidate(self):
        inner = [None] * 26
        inner[1] = ["c_test", "r_test"]
        inner[4] = [["rc_test", ["Hello world"]]]
        text = self._build_stream_response(inner)

        results = parse_stream_response(text)
        assert len(results) >= 1
        assert results[0]["text"] == "Hello world"
        assert results[0]["metadata"] == ["c_test", "r_test"]

    def test_extracts_rcid(self):
        inner = [None] * 26
        inner[1] = ["c_abc", "r_def"]
        inner[4] = [["rc_ghi", ["Some text"]]]
        text = self._build_stream_response(inner)

        results = parse_stream_response(text)
        assert results[0]["candidates"][0]["rcid"] == "rc_ghi"

    def test_no_candidates_returns_none_text(self):
        inner = [None] * 26
        inner[1] = ["c_test", "r_test"]
        text = self._build_stream_response(inner)

        results = parse_stream_response(text)
        assert len(results) >= 1
        assert results[0]["text"] is None
        assert results[0]["candidates"] == []

    def test_empty_response_no_wrb_frames(self):
        text = ")]}'\n\n25\n" + '[["e",4,null,null,154]]\n'
        results = parse_stream_response(text)
        assert len(results) == 0

    def test_metadata_extraction(self):
        inner = [None] * 26
        inner[1] = ["c_conv123", "r_resp456", "rc_cand789"]
        text = self._build_stream_response(inner)

        results = parse_stream_response(text)
        meta = results[0]["metadata"]
        assert meta[0] == "c_conv123"
        assert meta[1] == "r_resp456"
        assert meta[2] == "rc_cand789"

    def test_server_model_extraction(self):
        """Test that server-confirmed model hash and label are extracted."""
        # Build an inner JSON with a model hash and label at the end,
        # mimicking the real response structure
        inner = [None] * 45
        inner[1] = ["c_test", "r_test"]
        inner[4] = [["rc_test", ["Hello"]]]
        # Model hash and label appear in the context section
        inner[40] = "56fdd199312815e2"  # Fast model hash
        inner[41] = None
        inner[42] = None
        inner[43] = "Fast"
        text = self._build_stream_response(inner)

        results = parse_stream_response(text)
        assert len(results) >= 1
        assert results[0]["server_model_hash"] == "56fdd199312815e2"
        assert results[0]["server_model_label"] == "Fast"

    def test_no_model_in_early_frames(self):
        """Early streaming frames may not have model info."""
        inner = [None] * 26
        inner[1] = ["c_test", "r_test"]
        inner[4] = [["rc_test", ["partial"]]]
        text = self._build_stream_response(inner)

        results = parse_stream_response(text)
        assert results[0]["server_model_hash"] is None
        assert results[0]["server_model_label"] is None
