"""Shared browser authentication helpers for CDP-backed Gemini sessions."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from loguru import logger

from .cdp import (
    find_or_create_gemini_page,
    get_page_cookies,
    run_js,
)
from .constants import COOKIE_1PSID, TOKEN_PATTERNS

GEMINI_APP_URL = "https://gemini.google.com/app"


@dataclass
class BrowserAuthStatus:
    """Observed auth state for a Chrome/CDP Gemini page."""

    ws_url: str | None = None
    url: str = ""
    raw_cookies: list[dict] = field(default_factory=list)
    cookies: dict[str, str] = field(default_factory=dict)
    access_token: str = ""
    error: str = ""

    @property
    def has_auth_cookie(self) -> bool:
        return bool(self.cookies.get(COOKIE_1PSID))

    @property
    def is_authenticated(self) -> bool:
        return bool(self.has_auth_cookie and self.access_token)


def extract_browser_auth_status(ws_url: str) -> BrowserAuthStatus:
    """Inspect a Gemini CDP page for Google cookies and live SNlM0e."""
    status = BrowserAuthStatus(ws_url=ws_url)
    try:
        status.url = run_js(ws_url, "window.location.href") or ""
    except Exception:
        status.url = ""

    try:
        status.raw_cookies = get_page_cookies(ws_url)
        status.cookies = {
            c["name"]: c["value"]
            for c in status.raw_cookies
            if c.get("name") and c.get("value") and "google.com" in c.get("domain", "")
        }
    except Exception as e:
        status.error = f"cookie extraction failed: {e}"
        return status

    try:
        status.access_token = (
            run_js(ws_url, "window.WIZ_global_data?.SNlM0e || ''") or ""
        )
    except Exception as e:
        logger.debug(f"Browser auth: SNlM0e JS extraction failed: {e}")

    if not status.access_token:
        try:
            from .cdp import get_page_html

            html = get_page_html(ws_url)
            match = re.search(TOKEN_PATTERNS["snlm0e"], html)
            if match:
                status.access_token = match.group(1)
        except Exception as e:
            logger.debug(f"Browser auth: SNlM0e HTML extraction failed: {e}")

    return status


def get_browser_auth_status_for_port(port: int) -> BrowserAuthStatus:
    """Find/create a Gemini page on a CDP port and inspect browser auth.

    Read-only: never injects saved cookies into Chrome (issue #3).
    """
    page = find_or_create_gemini_page(port)
    if not page:
        return BrowserAuthStatus(error="Gemini page not found")

    ws_url = page.get("webSocketDebuggerUrl")
    if not ws_url:
        return BrowserAuthStatus(error="Gemini page has no WebSocket URL")

    return extract_browser_auth_status(ws_url)
