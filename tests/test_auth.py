"""Tests for authentication manager and CDP cookie filtering."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from gemini_web_mcp_cli.core.auth import (
    AuthManager,
    AuthState,
    AuthTokens,
    extract_email,
    extract_tokens,
)
from gemini_web_mcp_cli.core.cdp import _filter_gemini_cookies, _has_auth_cookies
from gemini_web_mcp_cli.core.exceptions import AuthError


class TestExtractTokens:
    def test_extracts_all_tokens(self):
        html = '''
        some content
        "SNlM0e":"token_abc_123"
        more content
        "cfb2h":"build_label_456"
        "FdrFJe":"session_id_789"
        '''
        tokens = extract_tokens(html)
        assert tokens.snlm0e == "token_abc_123"
        assert tokens.cfb2h == "build_label_456"
        assert tokens.fdrfje == "session_id_789"

    def test_extracts_snlm0e_with_spaces(self):
        html = '"SNlM0e": "spaced_token"'
        tokens = extract_tokens(html)
        assert tokens.snlm0e == "spaced_token"

    def test_missing_snlm0e_raises(self):
        html = '"cfb2h":"build_label"'
        with pytest.raises(AuthError, match="SNlM0e"):
            extract_tokens(html)

    def test_missing_optional_tokens_ok(self):
        html = '"SNlM0e":"token_only"'
        tokens = extract_tokens(html)
        assert tokens.snlm0e == "token_only"
        assert tokens.cfb2h == ""
        assert tokens.fdrfje == ""

    def test_empty_html_raises(self):
        with pytest.raises(AuthError):
            extract_tokens("")


class TestAuthTokens:
    def test_defaults(self):
        tokens = AuthTokens()
        assert tokens.snlm0e == ""
        assert tokens.cfb2h == ""
        assert tokens.fdrfje == ""


class TestAuthState:
    def test_to_dict_and_back(self):
        state = AuthState(
            cookies={"__Secure-1PSID": "cookie_val"},
            tokens=AuthTokens(snlm0e="tok", cfb2h="bl", fdrfje="sid"),
            chrome_profile_path="/path/to/profile",
            email="user@gmail.com",
        )
        d = state.to_dict()
        restored = AuthState.from_dict(d)
        assert restored.cookies["__Secure-1PSID"] == "cookie_val"
        assert restored.tokens.snlm0e == "tok"
        assert restored.tokens.cfb2h == "bl"
        assert restored.chrome_profile_path == "/path/to/profile"
        assert restored.email == "user@gmail.com"

    def test_to_dict_email_omitted_when_empty(self):
        state = AuthState(
            cookies={"__Secure-1PSID": "val"},
            tokens=AuthTokens(snlm0e="tok"),
        )
        d = state.to_dict()
        assert "email" not in d

    def test_is_valid_with_cookies_and_token(self):
        state = AuthState(
            cookies={"__Secure-1PSID": "val"},
            tokens=AuthTokens(snlm0e="tok"),
        )
        assert state.is_valid

    def test_is_valid_missing_cookie(self):
        state = AuthState(
            cookies={},
            tokens=AuthTokens(snlm0e="tok"),
        )
        assert not state.is_valid

    def test_is_valid_missing_token(self):
        state = AuthState(
            cookies={"__Secure-1PSID": "val"},
            tokens=AuthTokens(),
        )
        assert not state.is_valid

    def test_from_dict_empty(self):
        state = AuthState.from_dict({})
        assert not state.is_valid
        assert state.cookies == {}
        assert state.email == ""

    def test_from_dict_partial(self):
        state = AuthState.from_dict({"cookies": {"x": "y"}})
        assert state.cookies == {"x": "y"}
        assert state.tokens.snlm0e == ""

    def test_from_dict_with_email(self):
        state = AuthState.from_dict({"email": "test@example.com"})
        assert state.email == "test@example.com"

    def test_from_dict_without_email_backward_compat(self):
        """Old auth.json files without email field should still load."""
        state = AuthState.from_dict({
            "cookies": {"__Secure-1PSID": "val"},
            "tokens": {"snlm0e": "tok", "cfb2h": "", "fdrfje": ""},
        })
        assert state.email == ""
        assert state.is_valid


class TestFilterGeminiCookies:
    """Tests for _filter_gemini_cookies in cdp.py.

    Network.getAllCookies returns cookies from ALL domains. The filter must
    keep only google.com-relevant cookies and discard others to avoid cookie
    name collisions that break token extraction.
    """

    def test_keeps_google_domain_cookies(self):
        cookies_list = [
            {"name": "__Secure-1PSID", "value": "psid_val", "domain": ".google.com"},
            {"name": "__Secure-1PSIDTS", "value": "ts_val", "domain": ".google.com"},
            {"name": "NID", "value": "google_nid", "domain": ".google.com"},
        ]
        result = _filter_gemini_cookies(cookies_list)
        assert result["__Secure-1PSID"] == "psid_val"
        assert result["__Secure-1PSIDTS"] == "ts_val"
        assert result["NID"] == "google_nid"

    def test_keeps_gemini_subdomain_cookies(self):
        cookies_list = [
            {"name": "SomeCookie", "value": "gem_val", "domain": "gemini.google.com"},
            {"name": "Other", "value": "other_val", "domain": ".gemini.google.com"},
        ]
        result = _filter_gemini_cookies(cookies_list)
        assert result["SomeCookie"] == "gem_val"
        assert result["Other"] == "other_val"

    def test_discards_non_google_cookies(self):
        cookies_list = [
            {"name": "__Secure-1PSID", "value": "psid_val", "domain": ".google.com"},
            {"name": "NID", "value": "yt_nid", "domain": ".youtube.com"},
            {"name": "VISITOR", "value": "v", "domain": ".doubleclick.net"},
            {"name": "PREF", "value": "p", "domain": ".facebook.com"},
        ]
        result = _filter_gemini_cookies(cookies_list)
        assert "__Secure-1PSID" in result
        assert "VISITOR" not in result
        assert "PREF" not in result
        # NID from youtube.com should be discarded
        assert "NID" not in result

    def test_google_domain_wins_over_non_google(self):
        """When same-name cookies exist on google.com and youtube.com,
        only the google.com one should be kept."""
        cookies_list = [
            {"name": "NID", "value": "wrong_yt", "domain": ".youtube.com"},
            {"name": "NID", "value": "correct_google", "domain": ".google.com"},
        ]
        result = _filter_gemini_cookies(cookies_list)
        assert result["NID"] == "correct_google"

    def test_empty_list(self):
        assert _filter_gemini_cookies([]) == {}

    def test_missing_domain_field(self):
        cookies_list = [
            {"name": "NoDomain", "value": "val"},
            {"name": "__Secure-1PSID", "value": "psid", "domain": ".google.com"},
        ]
        result = _filter_gemini_cookies(cookies_list)
        assert "NoDomain" not in result
        assert result["__Secure-1PSID"] == "psid"

    def test_accounts_google_com_included(self):
        cookies_list = [
            {"name": "LSID", "value": "lsid_val", "domain": "accounts.google.com"},
        ]
        result = _filter_gemini_cookies(cookies_list)
        assert result["LSID"] == "lsid_val"

    def test_realistic_cdp_cookie_dump(self):
        """Simulates a realistic Network.getAllCookies response with cookies
        from multiple Google and non-Google domains."""
        cookies_list = [
            {"name": "__Secure-1PSID", "value": "psid", "domain": ".google.com"},
            {"name": "__Secure-1PSIDTS", "value": "psidts", "domain": ".google.com"},
            {"name": "SID", "value": "sid_google", "domain": ".google.com"},
            {"name": "HSID", "value": "hsid_google", "domain": ".google.com"},
            {"name": "SSID", "value": "ssid_google", "domain": ".google.com"},
            {"name": "SAPISID", "value": "sapisid_google", "domain": ".google.com"},
            {"name": "NID", "value": "nid_google", "domain": ".google.com"},
            {"name": "NID", "value": "nid_youtube", "domain": ".youtube.com"},
            {"name": "VISITOR_INFO", "value": "vi", "domain": ".youtube.com"},
            {"name": "YSC", "value": "ysc", "domain": ".youtube.com"},
            {"name": "CONSENT", "value": "c_yt", "domain": ".youtube.com"},
            {"name": "IDE", "value": "ide", "domain": ".doubleclick.net"},
            {"name": "test_cookie", "value": "tc", "domain": ".adsense.google.com"},
        ]
        result = _filter_gemini_cookies(cookies_list)
        assert result["__Secure-1PSID"] == "psid"
        assert result["__Secure-1PSIDTS"] == "psidts"
        assert result["SID"] == "sid_google"
        assert result["NID"] == "nid_google"
        assert result["SAPISID"] == "sapisid_google"
        assert result["test_cookie"] == "tc"  # adsense.google.com is still google.com
        assert "VISITOR_INFO" not in result
        assert "YSC" not in result
        assert "IDE" not in result


class TestHasAuthCookies:
    def test_has_psid(self):
        assert _has_auth_cookies({"__Secure-1PSID": "some_value"})

    def test_missing_psid(self):
        assert not _has_auth_cookies({"__Secure-1PSIDTS": "some_value"})

    def test_empty_psid(self):
        assert not _has_auth_cookies({"__Secure-1PSID": ""})

    def test_empty_dict(self):
        assert not _has_auth_cookies({})


class TestExtractEmail:
    def test_extracts_email_from_wiz_global_data(self):
        html = 'some content "oPEP7c":"user@gmail.com" more content'
        assert extract_email(html) == "user@gmail.com"

    def test_extracts_email_with_spaces(self):
        html = '"oPEP7c": "user@example.org"'
        assert extract_email(html) == "user@example.org"

    def test_returns_empty_when_no_email(self):
        html = '"SNlM0e":"some_token"'
        assert extract_email(html) == ""

    def test_returns_empty_for_empty_html(self):
        assert extract_email("") == ""

    def test_extracts_corporate_email(self):
        html = '"oPEP7c":"jbendavi@redhat.com"'
        assert extract_email(html) == "jbendavi@redhat.com"

    def test_ignores_non_email_opep7c(self):
        html = '"oPEP7c":"not_an_email"'
        assert extract_email(html) == ""

    def test_extracts_email_with_dots_and_plus(self):
        html = '"oPEP7c":"first.last+tag@sub.domain.com"'
        assert extract_email(html) == "first.last+tag@sub.domain.com"


class TestLoginCheckFlow:
    """Tests for the login --check validation flow."""

    async def test_refresh_tokens_success(self):
        pm = MagicMock()
        pm.load_auth.return_value = {
            "cookies": {"__Secure-1PSID": "psid_val"},
            "tokens": {"snlm0e": "old_token", "cfb2h": "", "fdrfje": ""},
            "chrome_profile_path": None,
            "last_refreshed": 0.0,
        }
        auth = AuthManager(pm, profile_name="test")
        auth.load()

        new_tokens = AuthTokens(snlm0e="new_token", cfb2h="bl", fdrfje="fj")
        mock_cookies = MagicMock()
        mock_cookies.items.return_value = []

        with patch(
            "gemini_web_mcp_cli.core.auth.fetch_tokens",
            new_callable=AsyncMock,
            return_value=(new_tokens, mock_cookies, "user@gmail.com"),
        ):
            result = await auth.refresh_tokens()
            assert result.snlm0e == "new_token"
            assert auth.state.email == "user@gmail.com"

    async def test_refresh_tokens_preserves_existing_email(self):
        pm = MagicMock()
        pm.load_auth.return_value = {
            "cookies": {"__Secure-1PSID": "psid_val"},
            "tokens": {"snlm0e": "old_token", "cfb2h": "", "fdrfje": ""},
            "chrome_profile_path": None,
            "last_refreshed": 0.0,
            "email": "existing@gmail.com",
        }
        auth = AuthManager(pm, profile_name="test")
        auth.load()

        new_tokens = AuthTokens(snlm0e="new_token", cfb2h="bl", fdrfje="fj")
        mock_cookies = MagicMock()
        mock_cookies.items.return_value = []

        with patch(
            "gemini_web_mcp_cli.core.auth.fetch_tokens",
            new_callable=AsyncMock,
            return_value=(new_tokens, mock_cookies, ""),
        ):
            await auth.refresh_tokens()
            assert auth.state.email == "existing@gmail.com"

    async def test_refresh_tokens_auth_error(self):
        pm = MagicMock()
        pm.load_auth.return_value = {
            "cookies": {"__Secure-1PSID": "psid_val"},
            "tokens": {"snlm0e": "old_token", "cfb2h": "", "fdrfje": ""},
            "chrome_profile_path": None,
            "last_refreshed": 0.0,
        }
        auth = AuthManager(pm, profile_name="test")
        auth.load()

        with patch(
            "gemini_web_mcp_cli.core.auth.fetch_tokens",
            new_callable=AsyncMock,
            side_effect=AuthError("Failed to extract SNlM0e"),
        ):
            with pytest.raises(AuthError, match="SNlM0e"):
                await auth.refresh_tokens()

    async def test_refresh_tokens_no_cookies(self):
        pm = MagicMock()
        pm.load_auth.return_value = {
            "cookies": {},
            "tokens": {"snlm0e": "", "cfb2h": "", "fdrfje": ""},
            "chrome_profile_path": None,
            "last_refreshed": 0.0,
        }
        auth = AuthManager(pm, profile_name="test")
        auth.load()

        with pytest.raises(AuthError, match="No cookies"):
            await auth.refresh_tokens()


class TestResolvedProfileName:
    """Token Factory and cookie write-back must target the real profile."""

    def test_uses_explicit_profile(self):
        pm = MagicMock()
        pm.get_active_profile.return_value = "active"
        assert AuthManager(pm, profile_name="work").resolved_profile_name == "work"

    def test_falls_back_to_active_profile_not_default(self):
        pm = MagicMock()
        pm.get_active_profile.return_value = "mail4jbd2"
        assert AuthManager(pm).resolved_profile_name == "mail4jbd2"


class TestCliFailExitCodes:
    """CLI errors must exit non-zero so `cmd || gemcli login` fallbacks run."""

    def test_auth_error_exits_auth_required(self):
        from gemini_web_mcp_cli.cli import EXIT_AUTH_REQUIRED, _fail

        with pytest.raises(SystemExit) as exc:
            _fail(AuthError("Session expired"))
        assert exc.value.code == EXIT_AUTH_REQUIRED == 3

    def test_other_error_exits_one(self):
        from gemini_web_mcp_cli.cli import _fail
        from gemini_web_mcp_cli.core.exceptions import GeminiError

        with pytest.raises(SystemExit) as exc:
            _fail(GeminiError("boom"))
        assert exc.value.code == 1


class TestOrphanCleanupPattern:
    """Killing one profile's Chrome must not kill a sibling (mail4jbd vs mail4jbd2)."""

    def _matches(self, pattern: str, cmdline: str) -> bool:
        import subprocess

        # grep -E uses the same POSIX ERE dialect as pgrep -f
        return subprocess.run(
            ["grep", "-qE", "--", pattern], input=cmdline, text=True
        ).returncode == 0

    def test_matches_only_exact_profile_dir(self):
        from pathlib import Path

        from gemini_web_mcp_cli.core.cdp import _user_data_dir_pgrep_pattern

        base = "/Users/x/.gemini-web-mcp-cli/chrome-profiles"
        pattern = _user_data_dir_pgrep_pattern(Path(f"{base}/mail4jbd"))
        chrome = "Google Chrome --remote-debugging-port=9223"

        assert self._matches(pattern, f"{chrome} --user-data-dir={base}/mail4jbd --headless")
        assert self._matches(pattern, f"{chrome} --user-data-dir={base}/mail4jbd")
        assert not self._matches(pattern, f"{chrome} --user-data-dir={base}/mail4jbd2 --x")
        assert not self._matches(pattern, f"{chrome} --user-data-dir={base}/mail4jbd_tf --x")
