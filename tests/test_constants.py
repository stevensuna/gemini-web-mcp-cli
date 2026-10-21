"""Tests for core constants."""

from gemini_web_mcp_cli.core.constants import (
    DEFAULT_MODEL,
    GEMINI_HEADERS,
    IMAGE_ASPECTS,
    MODELS,
    MUSIC_TEMPLATES,
    RESPONSE_PATHS,
    RPC,
    VIDEO_ORIENTATION_FLAGS,
    VIDEO_ORIENTATION_LABELS,
    VIDEO_ORIENTATIONS,
    Endpoint,
    ErrorCode,
    Model,
    get_model,
    normalize_image_aspect,
    normalize_music_genre,
    normalize_music_length,
    normalize_music_vocals,
    normalize_video_orientation,
)


class TestEndpoints:
    def test_init_endpoint(self):
        assert Endpoint.INIT == "https://gemini.google.com/app"

    def test_generate_endpoint(self):
        assert "StreamGenerate" in Endpoint.GENERATE

    def test_batch_exec_endpoint(self):
        assert "batchexecute" in Endpoint.BATCH_EXEC

    def test_upload_endpoint(self):
        assert "content-push.googleapis.com" in Endpoint.UPLOAD

    def test_rotate_cookies_endpoint(self):
        assert "RotateCookies" in Endpoint.ROTATE_COOKIES


class TestRPCIds:
    def test_known_rpcs_from_gemini_webapi(self):
        assert RPC.LIST_CHATS == "MaZiqc"
        assert RPC.READ_CHAT == "hNvQHb"
        assert RPC.DELETE_CHAT == "GzXR5e"
        assert RPC.LIST_GEMS == "CNgdBe"
        assert RPC.CREATE_GEM == "oMH3Zd"
        assert RPC.UPDATE_GEM == "kHv0Vd"
        assert RPC.DELETE_GEM == "UXcSJb"
        assert RPC.BARD_ACTIVITY == "ESY5D"

    def test_discovered_rpcs(self):
        assert RPC.STATUS_POLL == "aPya6c"
        assert RPC.ASYNC_POLL == "kwDCne"
        assert RPC.POST_PROCESS == "PCck7e"
        assert RPC.INIT_CONFIG == "otAQ7b"


class TestModels:
    def test_known_models(self):
        assert "fast" in MODELS
        assert "thinking" in MODELS
        assert "pro" in MODELS
        assert "unspecified" in MODELS

    def test_gemini_37_flash_alias(self):
        assert get_model("gemini-3.7-flash") == MODELS["fast"]
        assert get_model("gemini-3.8-flash") == MODELS["fast"]
        assert get_model("gemini-3.7-flash-extended") == MODELS["thinking"]
        assert get_model("gemini-3.7-flash-thinking") == MODELS["thinking"]
        assert get_model("gemini-4-argon") == MODELS["argon"]
        assert get_model("argon").hash == "95a4c0abcba24364"
        assert get_model("argon").header_tail == "8,1"

    def test_model_header(self):
        model = MODELS["pro"]
        header = model.header
        assert "x-goog-ext-525001261-jspb" in header
        assert "e6fa609c3fa255c0" in header["x-goog-ext-525001261-jspb"]

    def test_model_header_tails_distinguish_standard_and_extended(self):
        fast_header = MODELS["fast"].header["x-goog-ext-525001261-jspb"]
        extended_header = MODELS["fast"].with_extended_thinking().header[
            "x-goog-ext-525001261-jspb"
        ]
        assert "[4,5,6,8]" in fast_header
        assert fast_header.endswith("null,null,1,1]")
        assert extended_header.endswith("null,null,1,2]")
        assert MODELS["fast"].hash in extended_header

    def test_legacy_thinking_model_is_extended_fast(self):
        thinking = MODELS["thinking"]
        assert thinking.hash == MODELS["fast"].hash
        assert thinking.extended_thinking is True
        assert thinking.header["x-goog-ext-525001261-jspb"].endswith("null,null,1,2]")

    def test_thinking_levels_use_captured_toggles(self):
        fast = MODELS["fast"]
        assert fast.thinking_level == "low"
        assert fast.with_thinking_level("medium").header_tail == "1,4"
        assert fast.with_thinking_level("high").header_tail == "1,2"
        assert fast.with_thinking_level("high").extended_thinking is True
        assert MODELS["pro"].with_thinking_level("medium").header_tail == "3,4"
        argon = MODELS["argon"].with_thinking_level("high")
        assert argon.header_tail == "8,2"
        assert argon.hash == "95a4c0abcba24364"

    def test_rewrite_keeps_fields_after_the_thinking_pair(self):
        from gemini_web_mcp_cli.core.constants import rewrite_captured_model_header

        captured = (
            '[1,null,null,null,"56fdd199312815e2",null,null,0,'
            '[4,5,6,8,16,19,20],null,null,2,null,null,1,1,"SESSION",["build"],null,[1]]'
        )
        rewritten = rewrite_captured_model_header(captured, MODELS["argon"])
        assert '"95a4c0abcba24364"' in rewritten
        assert rewritten.endswith(',8,1,"SESSION",["build"],null,[1]]')

    def test_thinking_model_hash(self):
        model = MODELS["thinking"]
        assert model.hash == "56fdd199312815e2"

    def test_lite_model_hash(self):
        model = MODELS["lite"]
        assert model.hash == "8c46e95b1a07cecc"

    def test_fast_model_hash(self):
        model = MODELS["fast"]
        assert model.hash == "56fdd199312815e2"

    def test_unspecified_model_has_no_header(self):
        model = MODELS["unspecified"]
        assert model.header == {}

    def test_default_model(self):
        assert DEFAULT_MODEL.name == "fast"
        assert DEFAULT_MODEL.hash == "56fdd199312815e2"

    def test_get_model_valid(self):
        model = get_model("pro")
        assert model.name == "pro"

    def test_get_model_by_alias(self):
        assert get_model("flash").name == "fast"
        assert get_model("default").name == "fast"
        assert get_model("omni").name == "pro"
        assert get_model("gemini-3.1-omni").name == "pro"
        assert get_model("gemini-omni").name == "pro"

    def test_get_model_invalid(self):
        try:
            get_model("nonexistent-model")
            assert False, "Should have raised ValueError"
        except ValueError as e:
            assert "nonexistent-model" in str(e)

    def test_model_equality(self):
        a = Model("test", "abc")
        b = Model("test", "abc")
        assert a == b

    def test_model_repr(self):
        m = Model("test", "abc123")
        assert "test" in repr(m)
        assert "abc123" in repr(m)


class TestErrorCodes:
    def test_error_code_values(self):
        assert ErrorCode.TEMPORARY_ERROR == 1013
        assert ErrorCode.USAGE_LIMIT_EXCEEDED == 1037
        assert ErrorCode.MODEL_INCONSISTENT == 1050
        assert ErrorCode.MODEL_HEADER_INVALID == 1052
        assert ErrorCode.IP_TEMPORARILY_BLOCKED == 1060


class TestHeaders:
    def test_gemini_headers_has_required_fields(self):
        assert "Content-Type" in GEMINI_HEADERS
        assert "Host" in GEMINI_HEADERS
        assert "Origin" in GEMINI_HEADERS
        assert "X-Same-Domain" in GEMINI_HEADERS

    def test_user_agent_is_chrome(self):
        assert "Chrome" in GEMINI_HEADERS["User-Agent"]


class TestResponsePaths:
    def test_required_paths_exist(self):
        assert "metadata" in RESPONSE_PATHS
        assert "candidates" in RESPONSE_PATHS
        assert "error_code" in RESPONSE_PATHS
        assert "candidate_text" in RESPONSE_PATHS
        assert "candidate_generated_images" in RESPONSE_PATHS


class TestVideoOrientation:
    def test_orientation_ids(self):
        assert VIDEO_ORIENTATIONS["landscape"] == 16
        assert VIDEO_ORIENTATIONS["portrait"] == 17

    def test_orientation_flags(self):
        assert VIDEO_ORIENTATION_FLAGS["landscape"] == 1
        assert VIDEO_ORIENTATION_FLAGS["portrait"] == 2

    def test_labels_match_ui(self):
        assert VIDEO_ORIENTATION_LABELS["landscape"] == "Landscape (16:9)"
        assert VIDEO_ORIENTATION_LABELS["portrait"] == "Portrait (9:16)"

    def test_normalize_none(self):
        assert normalize_video_orientation(None) is None

    def test_normalize_canonical(self):
        assert normalize_video_orientation("landscape") == "landscape"
        assert normalize_video_orientation("portrait") == "portrait"

    def test_normalize_aliases(self):
        assert normalize_video_orientation("16:9") == "landscape"
        assert normalize_video_orientation("9:16") == "portrait"
        assert normalize_video_orientation("vertical") == "portrait"
        assert normalize_video_orientation("wide") == "landscape"

    def test_normalize_case_and_whitespace(self):
        assert normalize_video_orientation("  Portrait ") == "portrait"

    def test_normalize_rejects_unknown(self):
        import pytest

        with pytest.raises(ValueError, match="Unknown video orientation"):
            normalize_video_orientation("diagonal")


class TestImageAspect:
    def test_aspect_ids(self):
        assert IMAGE_ASPECTS == {"9:16": 59, "3:4": 60, "1:1": 61, "4:3": 62, "16:9": 63}

    def test_normalize_none(self):
        assert normalize_image_aspect(None) is None

    def test_normalize_canonical(self):
        for ratio in IMAGE_ASPECTS:
            assert normalize_image_aspect(ratio) == ratio

    def test_normalize_aliases(self):
        assert normalize_image_aspect("square") == "1:1"
        assert normalize_image_aspect("portrait") == "9:16"
        assert normalize_image_aspect("landscape") == "16:9"
        assert normalize_image_aspect("vertical") == "9:16"

    def test_normalize_rejects_unknown(self):
        import pytest

        with pytest.raises(ValueError, match="Unknown image aspect ratio"):
            normalize_image_aspect("5:4")


class TestMusicOptions:
    def test_lengths(self):
        assert normalize_music_length("short") == "Short"
        assert normalize_music_length("standard") == "Standard"
        assert normalize_music_length(None) is None

    def test_length_rejects_unknown(self):
        import pytest

        with pytest.raises(ValueError, match="Unknown music length"):
            normalize_music_length("epic")

    def test_vocals(self):
        assert normalize_music_vocals("custom") == "Custom, Based on your prompt"
        assert normalize_music_vocals("vocals") == "Vocals on"
        assert normalize_music_vocals("vocals_on") == "Vocals on"
        assert normalize_music_vocals("Instrumental") == "Instrumental"
        assert normalize_music_vocals(None) is None

    def test_vocals_rejects_unknown(self):
        import pytest

        with pytest.raises(ValueError, match="Unknown music vocals"):
            normalize_music_vocals("whisper")

    def test_genres(self):
        assert normalize_music_genre("pop") == "Pop"
        assert normalize_music_genre("ROCK") == "Rock"
        assert normalize_music_genre("K-pop") == "K-pop"
        assert normalize_music_genre("R&B") == "R&B"

    def test_genre_aliases(self):
        assert normalize_music_genre("hip hop") == "Hip-hop & rap"
        assert normalize_music_genre("hiphop") == "Hip-hop & rap"
        assert normalize_music_genre("rnb") == "R&B"
        assert normalize_music_genre("lofi") == "Lo-fi"
        assert normalize_music_genre("jazz") == "Jazz & blues"

    def test_genre_custom(self):
        assert normalize_music_genre("custom") == "Custom, Based on your prompt"
        assert normalize_music_genre(None) is None

    def test_genre_rejects_unknown(self):
        import pytest

        with pytest.raises(ValueError, match="Unknown music genre"):
            normalize_music_genre("polka")

    def test_templates_exist(self):
        assert "Soundscape" in MUSIC_TEMPLATES
        assert "Brand jingle" in MUSIC_TEMPLATES
        assert "Rap battle" in MUSIC_TEMPLATES
