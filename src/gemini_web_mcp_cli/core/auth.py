"""Authentication manager for the Gemini web interface.

Handles:
- Token extraction (SNlM0e, cfb2h, FdrFJe) from the Gemini app page
- Cookie management (__Secure-1PSID, __Secure-1PSIDTS)
- Cookie refresh via RotateCookies endpoint
- 3-layer recovery: CSRF refresh -> disk reload -> headless re-auth
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from pathlib import Path

import httpx
from loguru import logger

from .constants import (
    COOKIE_1PSID,
    COOKIE_1PSIDTS,
    COOKIE_REFRESH_COOLDOWN,
    EMAIL_PATTERN,
    GEMINI_HEADERS,
    ROTATE_COOKIES_BODY,
    ROTATE_COOKIES_HEADERS,
    TOKEN_PATTERNS,
    Endpoint,
)
from .exceptions import AuthError
from .profiles import ProfileManager


@dataclass
class AuthTokens:
    """Extracted authentication tokens from the Gemini init page."""

    snlm0e: str = ""  # Access token (at parameter)
    cfb2h: str = ""  # Build label (bl parameter)
    fdrfje: str = ""  # Session ID (f.sid parameter)


@dataclass
class AuthState:
    """Full authentication state for a session."""

    cookies: dict[str, str] = field(default_factory=dict)
    tokens: AuthTokens = field(default_factory=AuthTokens)
    chrome_profile_path: str | None = None
    last_refreshed: float = 0.0
    email: str = ""

    def to_dict(self) -> dict:
        """Serialize to dict for storage in auth.json."""
        d = {
            "cookies": self.cookies,
            "tokens": {
                "snlm0e": self.tokens.snlm0e,
                "cfb2h": self.tokens.cfb2h,
                "fdrfje": self.tokens.fdrfje,
            },
            "chrome_profile_path": self.chrome_profile_path,
            "last_refreshed": self.last_refreshed,
        }
        if self.email:
            d["email"] = self.email
        return d

    @classmethod
    def from_dict(cls, data: dict) -> AuthState:
        """Deserialize from auth.json dict."""
        tokens_data = data.get("tokens", {})
        return cls(
            cookies=data.get("cookies", {}),
            tokens=AuthTokens(
                snlm0e=tokens_data.get("snlm0e", ""),
                cfb2h=tokens_data.get("cfb2h", ""),
                fdrfje=tokens_data.get("fdrfje", ""),
            ),
            chrome_profile_path=data.get("chrome_profile_path"),
            last_refreshed=data.get("last_refreshed", 0.0),
            email=data.get("email", ""),
        )

    @property
    def is_valid(self) -> bool:
        """Check if we have minimum required auth (cookies + access token)."""
        return bool(self.cookies.get(COOKIE_1PSID) and self.tokens.snlm0e)


def extract_tokens(html: str) -> AuthTokens:
    """Extract SNlM0e, cfb2h, and FdrFJe tokens from Gemini app page HTML."""
    tokens = AuthTokens()

    for name, pattern in TOKEN_PATTERNS.items():
        match = re.search(pattern, html)
        if match:
            setattr(tokens, name, match.group(1))

    if not tokens.snlm0e:
        raise AuthError(
            "Failed to extract SNlM0e access token from Gemini page. "
            "Cookies may be expired or invalid."
        )

    return tokens


def extract_email(html: str) -> str:
    """Extract user email from Gemini app page HTML (WIZ_global_data.oPEP7c)."""
    match = re.search(EMAIL_PATTERN, html)
    return match.group(1) if match else ""


async def fetch_tokens(
    cookies: dict[str, str],
    proxy: str | None = None,
) -> tuple[AuthTokens, httpx.Cookies, str]:
    """Fetch the Gemini app page and extract tokens + email.

    Returns (tokens, updated_cookies, email).
    """
    async with httpx.AsyncClient(
        http2=True,
        proxy=proxy,
        headers=GEMINI_HEADERS,
        cookies=cookies,
        follow_redirects=True,
    ) as client:
        response = await client.get(Endpoint.INIT)
        response.raise_for_status()
        tokens = extract_tokens(response.text)
        email = extract_email(response.text)
        return tokens, client.cookies, email


async def rotate_cookies(
    cookies: dict[str, str],
    proxy: str | None = None,
) -> dict[str, str] | None:
    """Refresh __Secure-1PSIDTS via the RotateCookies endpoint.

    Returns updated cookies dict, or None if refresh failed.
    """
    async with httpx.AsyncClient(http2=True, proxy=proxy) as client:
        response = await client.post(
            url=Endpoint.ROTATE_COOKIES,
            headers=ROTATE_COOKIES_HEADERS,
            cookies=cookies,
            content=ROTATE_COOKIES_BODY,
        )

    if response.status_code == 401:
        raise AuthError("Cookie rotation returned 401. Full re-authentication required.")

    response.raise_for_status()

    # Use .jar iteration to avoid CookieConflict with duplicate cookie names
    new_1psidts = None
    for cookie in response.cookies.jar:
        if cookie.name == COOKIE_1PSIDTS:
            new_1psidts = cookie.value
            break
    if new_1psidts:
        updated = dict(cookies)
        updated[COOKIE_1PSIDTS] = new_1psidts
        return updated

    return None


class AuthManager:
    """Manages authentication state with 3-layer recovery.

    Recovery layers:
    1. CSRF refresh: re-fetch tokens from Gemini app page
    2. Disk reload: reload auth.json from disk (may have been refreshed externally)
    3. Headless re-auth: launch Chrome via CDP to re-authenticate
    """

    def __init__(
        self,
        profile_manager: ProfileManager,
        profile_name: str | None = None,
        proxy: str | None = None,
    ):
        self.profile_manager = profile_manager
        self.profile_name = profile_name
        self.proxy = proxy
        self._state: AuthState | None = None

    @property
    def resolved_profile_name(self) -> str:
        """The explicit profile name, or the currently active profile."""
        return self.profile_name or self.profile_manager.get_active_profile()

    @property
    def state(self) -> AuthState:
        """Get the current auth state. Raises if not initialized."""
        if self._state is None:
            raise AuthError("AuthManager not initialized. Call load() first.")
        return self._state

    def load(self) -> AuthState:
        """Load auth state from the profile's auth.json."""
        auth_data = self.profile_manager.load_auth(self.profile_name)
        if auth_data:
            self._state = AuthState.from_dict(auth_data)
        else:
            self._state = AuthState()
        return self._state

    def save(self) -> None:
        """Save current auth state to the profile's auth.json."""
        if self._state:
            self.profile_manager.save_auth(
                self._state.to_dict(),
                name=self.profile_name,
            )

    async def refresh_tokens(self) -> AuthTokens:
        """Layer 1: Re-fetch tokens from the Gemini app page."""
        if not self.state.cookies.get(COOKIE_1PSID):
            raise AuthError("No cookies available. Run `gemcli login` first.")

        logger.debug("Refreshing tokens from Gemini app page...")
        tokens, updated_cookies, email = await fetch_tokens(
            self.state.cookies, proxy=self.proxy
        )
        self.state.tokens = tokens

        if email:
            self.state.email = email

        # Iterate over .jar directly to avoid CookieConflict when Google
        # sets the same cookie name for multiple domains (e.g. SIDCC).
        for cookie in updated_cookies.jar:
            self.state.cookies[cookie.name] = cookie.value

        self.state.last_refreshed = time.time()
        self.save()
        logger.debug("Tokens refreshed successfully.")
        return tokens

    async def refresh_cookies(self) -> bool:
        """Refresh __Secure-1PSIDTS via RotateCookies.

        Respects cooldown to avoid 429 errors.
        """
        elapsed = time.time() - self.state.last_refreshed
        if elapsed < COOKIE_REFRESH_COOLDOWN:
            logger.debug(
                f"Cookie refresh cooldown: {COOKIE_REFRESH_COOLDOWN - elapsed:.0f}s remaining"
            )
            return False

        try:
            updated = await rotate_cookies(self.state.cookies, proxy=self.proxy)
            if updated:
                self.state.cookies = updated
                self.state.last_refreshed = time.time()
                self.save()
                logger.debug("Cookies refreshed via RotateCookies.")
                return True
        except AuthError:
            logger.warning("Cookie rotation failed (401). Full re-auth needed.")
            raise
        except Exception as e:
            logger.warning(f"Cookie rotation failed: {e}")

        return False

    async def recover(self) -> AuthState:
        """Attempt 3-layer recovery.

        1. Refresh tokens (re-fetch from Gemini page via httpx)
        2. Reload from disk (may have been refreshed by another process)
        3. Headless CDP extraction (launch Chrome silently to refresh tokens)
        """
        # Layer 1: Try refreshing tokens via httpx
        try:
            await self.refresh_tokens()
            if self.state.is_valid:
                return self.state
        except AuthError:
            logger.debug("Layer 1 (token refresh) failed.")

        # Layer 2: Reload from disk
        try:
            self.load()
            if self.state.is_valid:
                logger.debug("Layer 2 (disk reload) succeeded.")
                return self.state
        except Exception:
            logger.debug("Layer 2 (disk reload) failed.")

        # Layer 3: Headless CDP extraction — launch Chrome with the user's
        # existing profile to silently extract fresh cookies and SNlM0e.
        # Chrome's own cookie jar handles re-negotiation with Google.
        logger.debug("Layer 3: attempting headless CDP recovery...")
        try:
            self._recover_via_cdp()
            if self.state.is_valid:
                logger.info("Layer 3 (headless CDP) succeeded — tokens refreshed silently.")
                return self.state
        except Exception as e:
            logger.debug(f"Layer 3 (headless CDP) failed: {e}")

        raise AuthError(
            "All recovery layers exhausted. Run `gemcli login` to re-authenticate."
        )

    def _recover_via_cdp(self) -> None:
        """Layer 3: Launch headless Chrome with the user's profile to extract fresh tokens.

        Chrome's internal cookie management handles session renewal transparently.
        We navigate to gemini.google.com/app, wait for it to load, then extract:
        - All Google cookies from Chrome's cookie jar
        - SNlM0e token from window.WIZ_global_data.SNlM0e
        """
        import subprocess

        from .cdp import (
            _filter_gemini_cookies,
            find_available_port,
            find_or_create_gemini_page,
            get_chrome_path,
            get_debugger_url,
            get_page_cookies,
            navigate_to_url,
            run_js,
        )
        from .constants import CHROME_USER_AGENT

        chrome_profile_path = self.state.chrome_profile_path
        if not chrome_profile_path:
            chrome_profile_path = self.profile_manager.get_chrome_profile_path(
                self.profile_name
            )
        if not chrome_profile_path:
            raise AuthError("No Chrome profile path available for CDP recovery.")

        chrome_path = get_chrome_path()
        if not chrome_path:
            raise AuthError(
                "No Chromium browser found for CDP recovery. "
                "Set GEMCLI_BROWSER=<name> or install Chrome/Brave/Edge."
            )

        # Use port range 9400+ to avoid conflicts with Token Factory (9300+)
        # and gemcli login (9222+)
        port = find_available_port(start=9400)
        profile_dir = Path(chrome_profile_path)
        profile_dir.mkdir(parents=True, exist_ok=True)

        args = [
            chrome_path,
            f"--remote-debugging-port={port}",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-extensions",
            f"--user-data-dir={profile_dir}",
            "--remote-allow-origins=*",
            "--headless",
            f"--user-agent={CHROME_USER_AGENT}",
            "--disable-blink-features=AutomationControlled",
        ]

        process = None
        try:
            process = subprocess.Popen(
                args, stdout=subprocess.PIPE, stderr=subprocess.PIPE
            )
            time.sleep(3)

            # Wait for debugger to become available
            debugger_url = None
            for _ in range(10):
                debugger_url = get_debugger_url(port)
                if debugger_url:
                    break
                time.sleep(0.5)

            if not debugger_url:
                raise AuthError("Headless Chrome did not start in time.")

            # Find or create Gemini page
            page = find_or_create_gemini_page(port)
            if not page:
                raise AuthError("Failed to open Gemini page in headless Chrome.")

            ws_url = page.get("webSocketDebuggerUrl")
            if not ws_url:
                raise AuthError("No WebSocket URL for headless Gemini page.")

            # Navigate to Gemini app
            current_url = page.get("url", "")
            if "gemini.google.com/app" not in current_url:
                navigate_to_url(ws_url, "https://gemini.google.com/app")
                time.sleep(3)

            # Check we're not stuck on a login page
            try:
                final_url = run_js(ws_url, "window.location.href") or ""
                if "accounts.google.com" in final_url:
                    raise AuthError(
                        "Chrome redirected to login page — cookies are fully expired."
                    )
            except AuthError:
                raise
            except Exception:
                pass

            # Extract cookies from Chrome's cookie jar
            cookies_list = get_page_cookies(ws_url)
            cookies = _filter_gemini_cookies(cookies_list)

            if not cookies.get(COOKIE_1PSID):
                raise AuthError("No auth cookies found in headless Chrome.")

            # Extract SNlM0e from the live page
            snlm0e = ""
            try:
                snlm0e = run_js(
                    ws_url,
                    "window.WIZ_global_data && window.WIZ_global_data.SNlM0e",
                ) or ""
            except Exception as e:
                logger.debug(f"CDP SNlM0e extraction failed: {e}")

            if not snlm0e:
                # Fallback: try parsing the HTML
                try:
                    from .cdp import get_page_html
                    html = get_page_html(ws_url)
                    for name, pattern in TOKEN_PATTERNS.items():
                        match = re.search(pattern, html)
                        if match and name == "snlm0e":
                            snlm0e = match.group(1)
                except Exception:
                    pass

            if not snlm0e:
                raise AuthError("Headless CDP could not extract SNlM0e token.")

            # Extract other tokens and email from HTML
            cfb2h = ""
            fdrfje = ""
            email = ""
            try:
                from .cdp import get_page_html
                html = get_page_html(ws_url)
                for name, pattern in TOKEN_PATTERNS.items():
                    match = re.search(pattern, html)
                    if match:
                        if name == "cfb2h":
                            cfb2h = match.group(1)
                        elif name == "fdrfje":
                            fdrfje = match.group(1)
                email_match = re.search(EMAIL_PATTERN, html)
                if email_match:
                    email = email_match.group(1)
            except Exception:
                pass

            # Update auth state with fresh data
            self.state.cookies = cookies
            self.state.tokens = AuthTokens(
                snlm0e=snlm0e,
                cfb2h=cfb2h or self.state.tokens.cfb2h,
                fdrfje=fdrfje or self.state.tokens.fdrfje,
            )
            if email:
                self.state.email = email
            self.state.last_refreshed = time.time()
            self.save()

            logger.debug(
                f"CDP recovery: extracted SNlM0e ({len(snlm0e)} chars), "
                f"{len(cookies)} cookies"
            )

        finally:
            if process:
                try:
                    process.terminate()
                    process.wait(timeout=5)
                except Exception:
                    try:
                        process.kill()
                    except Exception:
                        pass
                # Clean up all Chrome lock files
                from .cdp import _clean_lock_files
                _clean_lock_files(Path(chrome_profile_path))

    def save_cookies(self, cookies: dict[str, str]) -> None:
        """Save cookies from an external source (e.g., CDP extraction)."""
        if self._state is None:
            self._state = AuthState()
        self._state.cookies = cookies
        self._state.last_refreshed = time.time()
        self.save()
