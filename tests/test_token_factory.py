"""Tests for the Token Factory: constants, dataclass, and routing logic."""

import atexit
import base64
import hashlib
import json
import threading

from gemini_web_mcp_cli.core import token_factory
from gemini_web_mcp_cli.core.constants import (
    CHROME_HEADERS,
    CHROME_USER_AGENT,
    TOKEN_FACTORY_MODELS,
    XBV_API_KEY,
    compute_xbv,
)
from gemini_web_mcp_cli.core.token_factory import CapturedRequest


class TestComputeXbv:
    """Tests for the x-browser-validation computation."""

    def test_known_answer(self):
        """Verify compute_xbv produces BASE64(SHA1(API_KEY + UA))."""
        expected = base64.b64encode(
            hashlib.sha1((XBV_API_KEY + CHROME_USER_AGENT).encode()).digest()
        ).decode()
        assert compute_xbv(CHROME_USER_AGENT) == expected

    def test_deterministic(self):
        """Same input always produces same output."""
        result1 = compute_xbv(CHROME_USER_AGENT)
        result2 = compute_xbv(CHROME_USER_AGENT)
        assert result1 == result2

    def test_different_ua_different_result(self):
        """Different user agents produce different results."""
        result1 = compute_xbv(CHROME_USER_AGENT)
        result2 = compute_xbv("SomeOtherUA/1.0")
        assert result1 != result2

    def test_result_is_base64(self):
        """Result should be valid base64."""
        result = compute_xbv(CHROME_USER_AGENT)
        # Should be decodable as base64
        decoded = base64.b64decode(result)
        # SHA-1 produces 20 bytes
        assert len(decoded) == 20


class TestCapturedRequest:
    """Tests for the CapturedRequest dataclass."""

    def test_construction(self):
        """CapturedRequest can be constructed with all fields."""
        req = CapturedRequest(
            url="https://gemini.google.com/_/BardChatUi/data/StreamGenerate",
            body="f.req=test&at=token",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            cookies={"__Secure-1PSID": "abc123"},
        )
        assert "StreamGenerate" in req.url
        assert req.body == "f.req=test&at=token"
        assert req.headers["Content-Type"] == "application/x-www-form-urlencoded"
        assert req.cookies["__Secure-1PSID"] == "abc123"

    def test_field_access(self):
        """All fields are accessible."""
        req = CapturedRequest(
            url="https://example.com",
            body="body",
            headers={"h1": "v1", "h2": "v2"},
            cookies={"c1": "v1"},
        )
        assert req.url == "https://example.com"
        assert req.body == "body"
        assert len(req.headers) == 2
        assert len(req.cookies) == 1


class TestChromeHeaders:
    """Tests for CHROME_HEADERS completeness."""

    def test_required_headers_present(self):
        """All headers needed for Chrome-like requests are present."""
        required = [
            "Accept",
            "Accept-Language",
            "Content-Type",
            "Origin",
            "Referer",
            "User-Agent",
            "X-Same-Domain",
            "x-browser-channel",
            "x-browser-year",
            "x-client-data",
            "Sec-Ch-Ua",
            "Sec-Ch-Ua-Mobile",
            "Sec-Ch-Ua-Platform",
            "Sec-Fetch-Dest",
            "Sec-Fetch-Mode",
            "Sec-Fetch-Site",
        ]
        for header in required:
            assert header in CHROME_HEADERS, f"Missing header: {header}"

    def test_origin_is_gemini(self):
        assert CHROME_HEADERS["Origin"] == "https://gemini.google.com"

    def test_user_agent_is_chrome(self):
        assert CHROME_HEADERS["User-Agent"] == CHROME_USER_AGENT
        assert "Chrome" in CHROME_USER_AGENT

    def test_content_type(self):
        assert "x-www-form-urlencoded" in CHROME_HEADERS["Content-Type"]


class TestTokenFactoryModels:
    """Tests for TOKEN_FACTORY_MODELS set."""

    def test_pro_requires_token_factory(self):
        assert "pro" in TOKEN_FACTORY_MODELS

    def test_thinking_requires_token_factory(self):
        assert "thinking" in TOKEN_FACTORY_MODELS

    def test_fast_does_not_require(self):
        assert "fast" not in TOKEN_FACTORY_MODELS

    def test_unspecified_does_not_require(self):
        assert "unspecified" not in TOKEN_FACTORY_MODELS


class TestNeedsTokenFactory:
    """Test the _needs_token_factory routing logic on GeminiClient."""

    def test_pro_needs_token_factory(self):
        from gemini_web_mcp_cli.core.client import GeminiClient
        from gemini_web_mcp_cli.core.constants import MODELS

        client = GeminiClient.__new__(GeminiClient)
        assert client._needs_token_factory(MODELS["pro"]) is True

    def test_thinking_needs_token_factory(self):
        from gemini_web_mcp_cli.core.client import GeminiClient
        from gemini_web_mcp_cli.core.constants import MODELS

        client = GeminiClient.__new__(GeminiClient)
        assert client._needs_token_factory(MODELS["thinking"]) is True

    def test_fast_does_not_need(self):
        from gemini_web_mcp_cli.core.client import GeminiClient
        from gemini_web_mcp_cli.core.constants import MODELS

        client = GeminiClient.__new__(GeminiClient)
        assert client._needs_token_factory(MODELS["fast"]) is False

    def test_extended_fast_needs_token_factory(self):
        from gemini_web_mcp_cli.core.client import GeminiClient
        from gemini_web_mcp_cli.core.constants import MODELS

        client = GeminiClient.__new__(GeminiClient)
        assert client._needs_token_factory(MODELS["fast"].with_extended_thinking()) is True

    def test_argon_and_medium_need_token_factory(self):
        from gemini_web_mcp_cli.core.client import GeminiClient
        from gemini_web_mcp_cli.core.constants import MODELS

        client = GeminiClient.__new__(GeminiClient)
        assert client._needs_token_factory(MODELS["argon"]) is True
        assert client._needs_token_factory(MODELS["fast"].with_thinking_level("medium")) is True

    def test_unspecified_does_not_need(self):
        from gemini_web_mcp_cli.core.client import GeminiClient
        from gemini_web_mcp_cli.core.constants import MODELS

        client = GeminiClient.__new__(GeminiClient)
        assert client._needs_token_factory(MODELS["unspecified"]) is False


class TestExtractAtFromBody:
    """Tests for _extract_at_from_body helper."""

    def test_extracts_at_token(self):
        """Extracts at= token from URL-encoded form data."""
        from gemini_web_mcp_cli.core.client import GeminiClient

        body = "f.req=%5Bnull%5D&at=SNlM0e_test_token_123&"
        result = GeminiClient._extract_at_from_body(body)
        assert result == "SNlM0e_test_token_123"

    def test_returns_none_for_missing_at(self):
        """Returns None when no at= parameter exists."""
        from gemini_web_mcp_cli.core.client import GeminiClient

        body = "f.req=%5Bnull%5D&other=value"
        result = GeminiClient._extract_at_from_body(body)
        assert result is None

    def test_returns_none_for_empty_body(self):
        """Returns None for empty body string."""
        from gemini_web_mcp_cli.core.client import GeminiClient

        result = GeminiClient._extract_at_from_body("")
        assert result is None

    def test_returns_none_for_empty_at_value(self):
        """Returns None when at= has no value."""
        from gemini_web_mcp_cli.core.client import GeminiClient

        body = "f.req=%5Bnull%5D&at=&"
        result = GeminiClient._extract_at_from_body(body)
        assert result is None

    def test_handles_malformed_body(self):
        """Handles malformed input gracefully."""
        from gemini_web_mcp_cli.core.client import GeminiClient

        result = GeminiClient._extract_at_from_body(None)
        assert result is None


class TestToolIdToName:
    """Tests for the TOOL_ID_TO_NAME mapping."""

    def test_image_tool_id_maps_to_images(self):
        from gemini_web_mcp_cli.core.token_factory import TOOL_ID_TO_NAME

        assert TOOL_ID_TO_NAME[14] == "Images"

    def test_video_tool_id_maps_to_videos(self):
        from gemini_web_mcp_cli.core.token_factory import TOOL_ID_TO_NAME

        assert TOOL_ID_TO_NAME[11] == "Videos"

    def test_music_tool_id_maps_to_music(self):
        from gemini_web_mcp_cli.core.token_factory import TOOL_ID_TO_NAME

        assert TOOL_ID_TO_NAME[21] == "Music"

    def test_tool_ids_match_constants(self):
        """Verify TOOL_ID_TO_NAME keys match the constants in constants.py."""
        from gemini_web_mcp_cli.core.constants import (
            IMAGE_TOOL_ID,
            MUSIC_TOOL_ID,
            VIDEO_TOOL_ID,
        )
        from gemini_web_mcp_cli.core.token_factory import TOOL_ID_TO_NAME

        assert IMAGE_TOOL_ID in TOOL_ID_TO_NAME
        assert VIDEO_TOOL_ID in TOOL_ID_TO_NAME
        assert MUSIC_TOOL_ID in TOOL_ID_TO_NAME


class TestCaptureAcceptsToolId:
    """Tests that capture() accepts the tool_id parameter."""

    def test_capture_signature_has_tool_id(self):
        """capture() method accepts a tool_id keyword argument."""
        import inspect

        from gemini_web_mcp_cli.core.token_factory import TokenFactory

        sig = inspect.signature(TokenFactory.capture)
        assert "tool_id" in sig.parameters
        # Should default to None
        assert sig.parameters["tool_id"].default is None

    def test_capture_signature_has_video_orientation(self):
        """capture() method accepts a video_orientation keyword argument."""
        import inspect

        from gemini_web_mcp_cli.core.token_factory import TokenFactory

        sig = inspect.signature(TokenFactory.capture)
        assert "video_orientation" in sig.parameters
        assert sig.parameters["video_orientation"].default is None

    def test_capture_signature_has_template(self):
        """capture() method accepts a template keyword argument."""
        import inspect

        from gemini_web_mcp_cli.core.token_factory import TokenFactory

        sig = inspect.signature(TokenFactory.capture)
        assert "template" in sig.parameters
        assert sig.parameters["template"].default is None

    def test_capture_signature_has_image_and_music_options(self):
        """capture() accepts image_aspect and music length/vocals/genre."""
        import inspect

        from gemini_web_mcp_cli.core.token_factory import TokenFactory

        sig = inspect.signature(TokenFactory.capture)
        for name in ("image_aspect", "music_length", "music_vocals", "music_genre"):
            assert name in sig.parameters
            assert sig.parameters[name].default is None


class TestToolActivation:
    """Tests for _activate_tool result handling."""

    def _make_factory(self, monkeypatch, run_js_result):
        from gemini_web_mcp_cli.core import token_factory
        from gemini_web_mcp_cli.core.token_factory import TokenFactory

        monkeypatch.setattr(token_factory, "run_js", lambda ws, js: run_js_result)
        monkeypatch.setattr(token_factory.time, "sleep", lambda s: None)
        factory = TokenFactory.__new__(TokenFactory)
        factory._ws_url = "ws://test"
        return factory

    def test_activated(self, monkeypatch):
        factory = self._make_factory(monkeypatch, "activated")
        assert factory._activate_tool(11) == "activated"

    def test_already_active(self, monkeypatch):
        factory = self._make_factory(monkeypatch, "already_active")
        assert factory._activate_tool(11) == "already_active"

    def test_disabled(self, monkeypatch):
        factory = self._make_factory(monkeypatch, "disabled")
        assert factory._activate_tool(11) == "disabled"

    def test_not_found(self, monkeypatch):
        factory = self._make_factory(monkeypatch, "not_found")
        assert factory._activate_tool(11) == "not_found"

    def test_none_result_becomes_error(self, monkeypatch):
        """A JS exception yields None — reported as 'error', not success."""
        factory = self._make_factory(monkeypatch, None)
        assert factory._activate_tool(11) == "error"

    def test_unknown_tool_id(self, monkeypatch):
        factory = self._make_factory(monkeypatch, "activated")
        assert factory._activate_tool(999) == "unsupported"


class TestCaptureFailsFastWhenToolDisabled:
    """capture() must not send a request when the requested tool is disabled."""

    def test_disabled_tool_raises(self, monkeypatch):
        import pytest

        from gemini_web_mcp_cli.core import token_factory
        from gemini_web_mcp_cli.core.constants import MODELS
        from gemini_web_mcp_cli.core.exceptions import UsageLimitExceeded
        from gemini_web_mcp_cli.core.token_factory import TokenFactory

        factory = TokenFactory.__new__(TokenFactory)
        factory._ws_url = "ws://test"
        factory._chrome_profile_path = None
        factory._profile_name = "default"
        factory._ready = True
        factory._generation_count = 1
        factory._idle_timer = None
        factory._idle_generation = 0
        factory._idle_lock = threading.Lock()
        factory._idle_timeout = 0
        factory._we_launched = False
        factory._raw_cookies = []
        factory._tf_profile_dir = None

        monkeypatch.setattr(factory, "_ensure_ready_locked", lambda: None)
        monkeypatch.setattr(
            token_factory, "get_current_url", lambda ws: token_factory.GEMINI_APP_URL
        )
        monkeypatch.setattr(factory, "_wait_for_input", lambda timeout=20: True)
        monkeypatch.setattr(factory, "_activate_tool", lambda tool_id: "disabled")

        with pytest.raises(UsageLimitExceeded, match="disabled"):
            factory.capture("a video", MODELS["fast"], tool_id=11)

    def test_missing_tool_raises_after_retry(self, monkeypatch):
        """A tool that cannot be activated must not send a fallback request."""
        import threading

        import pytest

        from gemini_web_mcp_cli.core import token_factory
        from gemini_web_mcp_cli.core.constants import MODELS
        from gemini_web_mcp_cli.core.exceptions import ToolActivationError
        from gemini_web_mcp_cli.core.token_factory import TokenFactory

        factory = TokenFactory.__new__(TokenFactory)
        factory._ws_url = "ws://test"
        factory._chrome_profile_path = None
        factory._profile_name = "default"
        factory._ready = True
        factory._generation_count = 1
        factory._idle_timer = None
        factory._idle_generation = 0
        factory._idle_lock = threading.Lock()
        factory._idle_timeout = 0
        factory._we_launched = False
        factory._raw_cookies = []
        factory._tf_profile_dir = None

        attempts = []

        monkeypatch.setattr(factory, "_ensure_ready_locked", lambda: None)
        monkeypatch.setattr(
            token_factory, "get_current_url", lambda ws: token_factory.GEMINI_APP_URL
        )
        monkeypatch.setattr(factory, "_wait_for_input", lambda timeout=20: True)
        monkeypatch.setattr(token_factory, "navigate_to_url", lambda ws, url: None)

        def fake_activate(tool_id):
            attempts.append(tool_id)
            return "not_found"

        monkeypatch.setattr(factory, "_activate_tool", fake_activate)

        with pytest.raises(ToolActivationError, match="Could not activate"):
            factory.capture("a video", MODELS["fast"], tool_id=11)

        # It retries activation once after re-navigating, then aborts
        assert len(attempts) == 2


class TestTemplateSelection:
    """Tests for the Token Factory's template-card UI control."""

    def _make_factory(self, monkeypatch, run_js_results):
        from gemini_web_mcp_cli.core import token_factory
        from gemini_web_mcp_cli.core.token_factory import TokenFactory

        calls = []

        def fake_run_js(ws_url, script):
            calls.append(script)
            return run_js_results.pop(0)

        monkeypatch.setattr(token_factory, "run_js", fake_run_js)
        factory = TokenFactory.__new__(TokenFactory)
        factory._ws_url = "ws://test"
        return factory, calls

    def test_template_selected(self, monkeypatch):
        factory, calls = self._make_factory(monkeypatch, ["selected"])
        assert factory._set_template("Anime") is True
        assert "Anime" in calls[0]

    def test_template_not_found_returns_false(self, monkeypatch):
        factory, _ = self._make_factory(monkeypatch, ["not_found"])
        assert factory._set_template("Nonexistent") is False

    def test_empty_template_skips_js(self, monkeypatch):
        factory, calls = self._make_factory(monkeypatch, [])
        assert factory._set_template("  ") is False
        assert calls == []

    def test_template_name_escapes_quotes(self, monkeypatch):
        factory, calls = self._make_factory(monkeypatch, ["selected"])
        factory._set_template("Jacob's story")
        assert "Jacob\\'s story" in calls[0]


class TestToolUiAliases:
    """Tests for TOOL_ID_UI_ALIASES — both drawer layouts must be matched."""

    def test_video_aliases_cover_both_layouts(self):
        from gemini_web_mcp_cli.core.token_factory import TOOL_ID_UI_ALIASES

        aliases = TOOL_ID_UI_ALIASES[11]
        assert "Videos" in aliases
        assert "Create video" in aliases

    def test_image_aliases_cover_both_layouts(self):
        from gemini_web_mcp_cli.core.token_factory import TOOL_ID_UI_ALIASES

        aliases = TOOL_ID_UI_ALIASES[14]
        assert "Images" in aliases
        assert "Create image" in aliases

    def test_music_aliases_cover_both_layouts(self):
        from gemini_web_mcp_cli.core.token_factory import TOOL_ID_UI_ALIASES

        aliases = TOOL_ID_UI_ALIASES[21]
        assert "Music" in aliases
        assert "Create music" in aliases


class TestAspectRatioSelection:
    """Tests for the Token Factory's aspect-ratio UI control."""

    def _make_factory(self, monkeypatch, run_js_results):
        from gemini_web_mcp_cli.core import token_factory
        from gemini_web_mcp_cli.core.token_factory import TokenFactory

        calls = []

        def fake_run_js(ws_url, script):
            calls.append(script)
            return run_js_results.pop(0)

        monkeypatch.setattr(token_factory, "run_js", fake_run_js)
        factory = TokenFactory.__new__(TokenFactory)
        factory._ws_url = "ws://test"
        return factory, calls

    def test_video_landscape_label(self, monkeypatch):
        factory, calls = self._make_factory(monkeypatch, ["selected"])
        assert factory._set_aspect_ratio("Landscape (16:9)") is True
        assert "Landscape (16:9)" in calls[0]
        assert "aspect" in calls[0]

    def test_image_aspect_label(self, monkeypatch):
        factory, calls = self._make_factory(monkeypatch, ["selected"])
        assert factory._set_aspect_ratio("9:16") is True
        assert "9:16" in calls[0]

    def test_empty_label_skips_js(self, monkeypatch):
        factory, calls = self._make_factory(monkeypatch, [])
        assert factory._set_aspect_ratio("") is False
        assert calls == []

    def test_failure_returns_false(self, monkeypatch):
        factory, _ = self._make_factory(monkeypatch, ["not_found"])
        assert factory._set_aspect_ratio("1:1") is False


class TestMusicOptionSelection:
    """Tests for the Token Factory's music Length/Vocals/Genre control."""

    def _make_factory(self, monkeypatch, run_js_results):
        from gemini_web_mcp_cli.core import token_factory
        from gemini_web_mcp_cli.core.token_factory import TokenFactory

        calls = []

        def fake_run_js(ws_url, script):
            calls.append(script)
            return run_js_results.pop(0)

        monkeypatch.setattr(token_factory, "run_js", fake_run_js)
        factory = TokenFactory.__new__(TokenFactory)
        factory._ws_url = "ws://test"
        return factory, calls

    def test_length_short(self, monkeypatch):
        factory, calls = self._make_factory(monkeypatch, ["selected"])
        assert factory._set_music_option("Length", "Short") is True
        assert "Length" in calls[0]
        assert "Short" in calls[0]

    def test_vocals_instrumental(self, monkeypatch):
        factory, calls = self._make_factory(monkeypatch, ["selected"])
        assert factory._set_music_option("Vocals", "Instrumental") is True
        assert "Instrumental" in calls[0]

    def test_genre_rock(self, monkeypatch):
        factory, calls = self._make_factory(monkeypatch, ["selected"])
        assert factory._set_music_option("Genre", "Rock") is True
        assert "Genre" in calls[0]
        assert "Rock" in calls[0]

    def test_empty_label_skips_js(self, monkeypatch):
        factory, calls = self._make_factory(monkeypatch, [])
        assert factory._set_music_option("Genre", "") is False
        assert calls == []

    def test_failure_returns_false(self, monkeypatch):
        factory, _ = self._make_factory(monkeypatch, ["no_control"])
        assert factory._set_music_option("Genre", "Rock") is False


class TestModelPickerSelection:
    """Tests for the Token Factory's mode-picker UI control."""

    def _make_factory(self, monkeypatch, run_js_results):
        from gemini_web_mcp_cli.core import token_factory
        from gemini_web_mcp_cli.core.token_factory import TokenFactory

        calls = []

        def fake_run_js(ws_url, script):
            calls.append(script)
            return run_js_results.pop(0)

        monkeypatch.setattr(token_factory, "run_js", fake_run_js)
        factory = TokenFactory.__new__(TokenFactory)
        factory._ws_url = "ws://test"
        return factory, calls

    def test_set_model_uses_hash_test_id(self, monkeypatch):
        from gemini_web_mcp_cli.core.constants import MODELS

        factory, calls = self._make_factory(monkeypatch, ["set"])
        assert factory._set_model_picker(MODELS["pro"]) is True
        assert "bard-mode-option-" in calls[0]
        assert "'e6fa609c3fa255c0'" in calls[0]
        assert "'Low'" in calls[0]

    def test_set_thinking_model_requests_extended(self, monkeypatch):
        from gemini_web_mcp_cli.core.constants import MODELS

        factory, calls = self._make_factory(monkeypatch, ["set"])
        assert factory._set_model_picker(MODELS["thinking"]) is True
        assert "'High'" in calls[0]

    def test_set_model_without_hash_skips(self, monkeypatch):
        from gemini_web_mcp_cli.core.constants import MODELS

        factory, calls = self._make_factory(monkeypatch, [])
        assert factory._set_model_picker(MODELS["unspecified"]) is False
        assert calls == []

    def test_set_model_failure_returns_false(self, monkeypatch):
        from gemini_web_mcp_cli.core.constants import MODELS

        factory, _ = self._make_factory(monkeypatch, ["no_picker"])
        assert factory._set_model_picker(MODELS["fast"]) is False

    def test_model_picker_js_is_parser_safe(self):
        """The rendered JS must not contain unreplaced template tokens."""
        from gemini_web_mcp_cli.core.constants import MODELS
        from gemini_web_mcp_cli.core.token_factory import SET_MODEL_PICKER_JS

        js = SET_MODEL_PICKER_JS.replace("{hash}", MODELS["fast"].hash).replace(
            "{level}", "Low"
        )
        assert "{hash}" not in js
        assert "{level}" not in js
        assert "thinking_level" in js


def _write_auth(
    tmp_path,
    email: str,
    cookies: dict[str, str] | None = None,
) -> None:
    auth_file = (
        tmp_path
        / ".gemini-web-mcp-cli"
        / "profiles"
        / "default"
        / "auth.json"
    )
    auth_file.parent.mkdir(parents=True)
    auth_file.write_text(
        json.dumps(
            {
                "cookies": cookies or {"__Secure-1PSID": "old-cookie"},
                "tokens": {"snlm0e": "", "cfb2h": "", "fdrfje": ""},
                "last_refreshed": 0,
                "email": email,
            }
        ),
        encoding="utf-8",
    )


class TestAutoSignInIdentifierPage:
    def test_signed_out_gemini_page_with_snlm0e_is_not_success(self, tmp_path, monkeypatch):
        """The signed-out Gemini page also carries SNlM0e; only the email proves sign-in."""
        monkeypatch.setenv("HOME", str(tmp_path))
        _write_auth(tmp_path, "user@example.com")

        def fake_run_js(ws_url, script):
            if "btn.textContent.trim() === 'Sign in'" in script:
                return True
            if script == "window.location.href":
                return "https://gemini.google.com/app"  # redirect never happens
            if script == "window.WIZ_global_data?.oPEP7c || ''":
                return ""  # signed out
            if script == "window.WIZ_global_data?.SNlM0e || ''":
                return "guest-snlm0e"
            raise AssertionError(f"unexpected script: {script}")

        monkeypatch.setattr(token_factory, "run_js", fake_run_js)
        monkeypatch.setattr(token_factory.time, "sleep", lambda _seconds: None)

        from gemini_web_mcp_cli.core.token_factory import TokenFactory

        factory = TokenFactory(profile_name="default")
        atexit.unregister(factory.shutdown)
        factory._ws_url = "ws://test"

        assert factory._auto_sign_in() is None

    def test_auto_sign_in_submits_saved_email_on_identifier_page(
        self,
        tmp_path,
        monkeypatch,
    ):
        monkeypatch.setenv("HOME", str(tmp_path))
        _write_auth(tmp_path, "user@example.com")

        urls = [
            "https://accounts.google.com/v3/signin/identifier",
            "https://gemini.google.com/app",
        ]
        submitted_email_scripts = []

        def fake_run_js(ws_url, script):
            assert ws_url == "ws://test"
            if "btn.textContent.trim() === 'Sign in'" in script:
                return True
            if script == "window.location.href":
                return urls.pop(0)
            if script == "document.body.innerText.substring(0, 500)":
                return "Email or phone"
            if 'input[type="email"]' in script:
                submitted_email_scripts.append(script)
                return True
            if "[data-identifier]" in script:
                raise AssertionError("account chooser fallback should not run")
            if script == "window.WIZ_global_data?.oPEP7c || ''":
                return "user@example.com"
            if script == "window.WIZ_global_data?.SNlM0e || ''":
                return "fresh-snlm0e"
            raise AssertionError(f"unexpected script: {script}")

        monkeypatch.setattr(token_factory, "run_js", fake_run_js)
        monkeypatch.setattr(token_factory.time, "sleep", lambda _seconds: None)
        monkeypatch.setattr(
            token_factory,
            "get_page_cookies",
            lambda _ws_url: [
                {
                    "domain": ".google.com",
                    "name": "__Secure-1PSID",
                    "value": "fresh-cookie",
                }
            ],
        )

        from gemini_web_mcp_cli.core.token_factory import TokenFactory

        factory = TokenFactory(profile_name="default")
        atexit.unregister(factory.shutdown)
        factory._ws_url = "ws://test"

        assert factory._auto_sign_in() == "fresh-snlm0e"
        assert submitted_email_scripts
        assert "user@example.com" in submitted_email_scripts[0]

        saved = json.loads(
            (
                tmp_path
                / ".gemini-web-mcp-cli"
                / "profiles"
                / "default"
                / "auth.json"
            ).read_text(encoding="utf-8")
        )
        assert saved["cookies"]["__Secure-1PSID"] == "fresh-cookie"
        assert saved["tokens"]["snlm0e"] == "fresh-snlm0e"

    def test_load_auth_email_strips_saved_email(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        _write_auth(tmp_path, "  user@example.com  ")

        from gemini_web_mcp_cli.core.token_factory import TokenFactory

        factory = TokenFactory(profile_name="default")
        atexit.unregister(factory.shutdown)

        assert factory._load_auth_email() == "user@example.com"



def _bare_factory():
    from gemini_web_mcp_cli.core.token_factory import TokenFactory

    factory = TokenFactory.__new__(TokenFactory)
    factory._ws_url = "ws://test"
    factory._chrome_profile_path = None
    factory._profile_name = "eltanium"
    factory._ready = True
    factory._generation_count = 1
    factory._idle_timer = None
    factory._idle_generation = 0
    factory._idle_lock = threading.Lock()
    factory._idle_timeout = 0
    factory._we_launched = False
    factory._raw_cookies = []
    factory._tf_profile_dir = None
    return factory


class TestProcessSessionCapture:
    """Token Factory captures both chat transports (processSession, Sep 2026)."""

    def test_hook_covers_both_transports(self):
        js = token_factory.XHR_INTERCEPTOR_JS
        assert "StreamGenerate" in js
        assert "/processSession" in js and "X-HTTP-Session-Id" in js
        assert "___data__" in js

    def test_capture_normalizes_relative_and_absolute_stream_urls(self, monkeypatch):
        factory = _bare_factory()
        monkeypatch.setattr(factory, "_ensure_ready_locked", lambda: None)
        monkeypatch.setattr(factory, "_wait_for_input", lambda timeout=20: True)
        monkeypatch.setattr(factory, "_set_composer_mode", lambda task: None)
        monkeypatch.setattr(factory, "_get_google_cookies", lambda: {})
        monkeypatch.setattr(
            token_factory, "get_current_url", lambda ws: token_factory.GEMINI_APP_URL
        )
        monkeypatch.setattr(token_factory, "navigate_to_url", lambda ws, url: None)
        monkeypatch.setattr(token_factory.time, "sleep", lambda s: None)
        monkeypatch.setattr(token_factory, "run_js", lambda ws, js: "synthetic")
        path = "/_/BardChatUi/data/StreamGenerate?rt=c"
        absolute = "https://gemini.google.com" + path
        for url in (path, absolute):
            monkeypatch.setattr(
                factory, "_poll_capture", lambda: {"url": url, "body": "f.req=synthetic"}
            )
            assert factory._capture_locked("hello", None).url == absolute

    def test_poll_rejects_process_session_without_open_url(self, monkeypatch):
        factory = _bare_factory()
        monkeypatch.setattr(token_factory.time, "sleep", lambda s: None)
        monkeypatch.setattr(
            token_factory, "run_js",
            lambda ws, js: {"transport": "processSession", "url": None, "body": "count=1"},
        )
        assert factory._poll_capture(timeout=2) is None

    def test_poll_accepts_process_session(self, monkeypatch):
        factory = _bare_factory()
        cap = {"transport": "processSession", "url": "https://x/processSession?a", "body": "b"}
        monkeypatch.setattr(token_factory.time, "sleep", lambda s: None)
        monkeypatch.setattr(token_factory, "run_js", lambda ws, js: cap)
        assert factory._poll_capture(timeout=2) == cap

    def test_escaped_prompt_raises_without_retry(self, monkeypatch):
        import pytest

        from gemini_web_mcp_cli.core.constants import MODELS
        from gemini_web_mcp_cli.core.exceptions import PromptEscaped, TokenFactoryError

        factory = _bare_factory()
        urls = iter([token_factory.GEMINI_APP_URL, "https://gemini.google.com/app/1234abcd"])
        sends = []
        monkeypatch.setattr(factory, "_ensure_ready_locked", lambda: None)
        monkeypatch.setattr(factory, "_wait_for_input", lambda timeout=20: True)
        monkeypatch.setattr(factory, "_poll_capture", lambda timeout=20: None)
        monkeypatch.setattr(token_factory, "get_current_url", lambda ws: next(urls))
        monkeypatch.setattr(token_factory, "navigate_to_url", lambda ws, url: None)
        monkeypatch.setattr(token_factory.time, "sleep", lambda s: None)
        monkeypatch.setattr(
            token_factory, "run_js",
            lambda ws, js: sends.append(js) if js == token_factory.CLICK_SEND_JS else None,
        )
        with pytest.raises(PromptEscaped, match="doctor --deep"):
            factory.capture("hello", MODELS["fast"])
        assert len(sends) == 1
        assert not issubclass(PromptEscaped, TokenFactoryError)

    def test_follow_up_navigates_without_c_prefix(self, monkeypatch):
        import pytest

        from gemini_web_mcp_cli.core.constants import MODELS
        from gemini_web_mcp_cli.core.exceptions import TokenFactoryError
        from gemini_web_mcp_cli.core.models import ConversationMetadata

        factory = _bare_factory()
        visited = []
        monkeypatch.setattr(factory, "_ensure_ready_locked", lambda: None)
        monkeypatch.setattr(factory, "_wait_for_input", lambda timeout=20: True)
        monkeypatch.setattr(factory, "_poll_capture", lambda timeout=20: None)
        monkeypatch.setattr(
            token_factory, "get_current_url", lambda ws: token_factory.GEMINI_APP_URL
        )
        monkeypatch.setattr(token_factory, "navigate_to_url", lambda ws, url: visited.append(url))
        monkeypatch.setattr(token_factory.time, "sleep", lambda s: None)
        monkeypatch.setattr(token_factory, "run_js", lambda ws, js: None)
        with pytest.raises(TokenFactoryError):
            factory.capture("more", MODELS["fast"], metadata=ConversationMetadata(cid="c_fc89"))
        assert visited[0] == f"{token_factory.GEMINI_APP_URL}/fc89"


class TestMultiLinePrompt:
    """Issue #2: typing a newline cut the captured prompt off at the first line."""

    def test_typed_text_has_no_newlines(self, monkeypatch):
        import pytest

        from gemini_web_mcp_cli.core.constants import MODELS
        from gemini_web_mcp_cli.core.exceptions import TokenFactoryError

        factory = _bare_factory()
        typed = []
        monkeypatch.setattr(factory, "_ensure_ready_locked", lambda: None)
        monkeypatch.setattr(factory, "_wait_for_input", lambda timeout=20: True)
        monkeypatch.setattr(factory, "_poll_capture", lambda timeout=20: None)
        monkeypatch.setattr(
            token_factory, "get_current_url", lambda ws: token_factory.GEMINI_APP_URL
        )
        monkeypatch.setattr(token_factory, "navigate_to_url", lambda ws, url: None)
        monkeypatch.setattr(token_factory.time, "sleep", lambda s: None)
        monkeypatch.setattr(
            token_factory, "run_js",
            lambda ws, js: typed.append(js) if "insertText" in js else None,
        )
        with pytest.raises(TokenFactoryError):
            factory.capture("Line one.\n\nLine two.\nLine three.", MODELS["fast"])
        assert typed
        assert all("\\n" not in js and "Line one. Line two. Line three." in js for js in typed)

    def test_hook_aborts_every_stream_generate(self):
        js = token_factory.XHR_INTERCEPTOR_JS
        block = js[js.index("includes('StreamGenerate')"):js.index("/processSession")]
        # capture is conditional, abort is not
        assert "if (!window.__cap)" in block and block.count("this.abort()") == 1
        assert block.index("this.abort()") > block.index("if (!window.__cap)")
