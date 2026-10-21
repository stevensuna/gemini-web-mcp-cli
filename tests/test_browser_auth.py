"""Tests for shared browser auth/CDP helpers."""

from gemini_web_mcp_cli.core import browser_auth
from gemini_web_mcp_cli.core.browser_auth import (
    BrowserAuthStatus,
    get_browser_auth_status_for_port,
)


def test_status_for_port_is_read_only(monkeypatch):
    """Checking a Chrome's auth must never inject saved cookies into it (issue #3)."""
    monkeypatch.setattr(
        browser_auth,
        "find_or_create_gemini_page",
        lambda _port: {"webSocketDebuggerUrl": "ws://test"},
    )
    observed = BrowserAuthStatus(
        ws_url="ws://test", cookies={"__Secure-1PSID": "psid"}, access_token=""
    )
    monkeypatch.setattr(browser_auth, "extract_browser_auth_status", lambda _ws: observed)

    status = get_browser_auth_status_for_port(9222)

    assert status is observed
    assert status.is_authenticated is False
    for name in ("sync_saved_auth_to_chrome", "cdp_cookies_from_saved",
                 "execute_cdp_command"):
        assert not hasattr(browser_auth, name)


def test_status_for_port_reports_missing_page(monkeypatch):
    monkeypatch.setattr(browser_auth, "find_or_create_gemini_page", lambda _port: None)

    status = get_browser_auth_status_for_port(9222)

    assert status.is_authenticated is False
    assert "not found" in status.error
