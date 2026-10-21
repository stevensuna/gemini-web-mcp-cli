"""One Chrome owns each Google session (issue #3).

Regression tests for the rules that stop gemcli from mixing sessions:
- the Chrome daemon is only used for the profile it holds;
- a Chrome signed in to a different account is never used;
- Token Factory runs on the profile's own user-data-dir, never a copy;
- orphan cleanup matches the profile directory exactly.
"""

from __future__ import annotations

import atexit
from pathlib import Path
from types import SimpleNamespace

import pytest

from gemini_web_mcp_cli.core import browser_auth, chrome_manager, token_factory
from gemini_web_mcp_cli.core import cdp as cdp_mod
from gemini_web_mcp_cli.core.auth import AuthState
from gemini_web_mcp_cli.core.browser_auth import BrowserAuthStatus
from gemini_web_mcp_cli.core.client import GeminiClient


def _client(profile: str, email: str, chrome_path: str) -> GeminiClient:
    client = GeminiClient(profile_name=profile)
    client.auth_manager._state = AuthState(email=email, chrome_profile_path=chrome_path)
    client.profile_manager.get_chrome_profile_path = lambda _name=None: chrome_path
    return client


def _daemon(profile: str, path: str, port: int = 9222):
    return SimpleNamespace(profile_name=profile, chrome_profile_path=path, port=port)


def _authed(email: str) -> BrowserAuthStatus:
    return BrowserAuthStatus(
        ws_url=f"ws://{email}", cookies={"__Secure-1PSID": "psid"}, access_token="tok"
    )


class TestClientBrowserCookies:
    async def test_daemon_for_another_profile_is_not_used(self, monkeypatch):
        client = _client("gns", "gns@gmail.com", "/profiles/gns")
        monkeypatch.setattr(
            chrome_manager, "check_daemon_health",
            lambda: (_daemon("mail4jbd2", "/profiles/mail4jbd2"), "running"),
        )
        looked_up = []
        monkeypatch.setattr(
            cdp_mod, "find_existing_gemcli_chrome",
            lambda profile_name: looked_up.append(profile_name) or (None, None),
        )
        used_ports = []
        monkeypatch.setattr(
            browser_auth, "get_browser_auth_status_for_port",
            lambda port: used_ports.append(port) or _authed("x"),
        )

        class _NoLaunch:
            _port = None

            def ensure_ready(self):
                raise RuntimeError("stop before launching Chrome")

        monkeypatch.setattr(client, "_ensure_token_factory", lambda: _NoLaunch())

        assert await client._ensure_browser_cookies(force=True) is False
        assert looked_up == ["gns"]        # searched for gns's own Chrome
        assert 9222 not in used_ports      # never read mail4jbd2's daemon

    async def test_daemon_for_this_profile_is_used(self, monkeypatch):
        client = _client("mail4jbd2", "mail4jbd2@gmail.com", "/profiles/mail4jbd2")
        monkeypatch.setattr(
            chrome_manager, "check_daemon_health",
            lambda: (_daemon("mail4jbd2", "/profiles/mail4jbd2"), "running"),
        )
        monkeypatch.setattr(
            browser_auth, "get_browser_auth_status_for_port",
            lambda port: _authed("mail4jbd2@gmail.com"),
        )
        monkeypatch.setattr(cdp_mod, "run_js", lambda _ws, _js: "mail4jbd2@gmail.com")

        assert await client._ensure_browser_cookies(force=True) is True
        assert client._browser_cookies == {"__Secure-1PSID": "psid"}

    async def test_chrome_signed_in_as_other_account_is_refused(self, monkeypatch):
        client = _client("mail4jbd2", "mail4jbd2@gmail.com", "/profiles/mail4jbd2")
        monkeypatch.setattr(
            chrome_manager, "check_daemon_health",
            lambda: (_daemon("mail4jbd2", "/profiles/mail4jbd2"), "running"),
        )
        monkeypatch.setattr(
            browser_auth, "get_browser_auth_status_for_port",
            lambda port: _authed("someone-else@gmail.com"),
        )
        monkeypatch.setattr(cdp_mod, "run_js", lambda _ws, _js: "someone-else@gmail.com")

        class _NoLaunch:
            _port = None

            def ensure_ready(self):
                raise RuntimeError("stop before launching Chrome")

        monkeypatch.setattr(client, "_ensure_token_factory", lambda: _NoLaunch())

        assert await client._ensure_browser_cookies(force=True) is False
        assert client._browser_cookies is None


class TestTokenFactoryOwnProfile:
    def test_launches_on_profile_dir_not_a_copy(self, tmp_path, monkeypatch):
        profile_dir = tmp_path / "chrome-profiles" / "gns"
        profile_dir.mkdir(parents=True)
        popen_args = []

        class _StopAfterLaunch(Exception):
            pass

        def fake_popen(args, **_kwargs):
            popen_args.extend(args)
            raise _StopAfterLaunch

        monkeypatch.setattr(token_factory, "get_chrome_path", lambda: "/bin/chrome")
        monkeypatch.setattr(chrome_manager, "check_daemon_health", lambda: (None, "stopped"))
        monkeypatch.setattr(token_factory, "find_existing_gemcli_chrome",
                            lambda profile_name: (None, None))
        monkeypatch.setattr(token_factory, "find_available_port", lambda start: 9300)
        monkeypatch.setattr(token_factory.TokenFactory, "_kill_stale_chrome",
                            staticmethod(lambda _dir: None))
        monkeypatch.setattr(token_factory.subprocess, "Popen", fake_popen)

        factory = token_factory.TokenFactory(
            chrome_profile_path=str(profile_dir), profile_name="gns"
        )
        atexit.unregister(factory.shutdown)

        with pytest.raises(token_factory.TokenFactoryError):
            factory.ensure_ready()

        assert f"--user-data-dir={profile_dir}" in popen_args
        assert not (tmp_path / "chrome-profiles" / "gns_tf").exists()

    def test_kill_stale_chrome_matches_exact_profile(self, monkeypatch):
        calls = []
        monkeypatch.setattr(
            token_factory.subprocess, "run",
            lambda args, **_k: calls.append(args) or SimpleNamespace(stdout=""),
        )

        token_factory.TokenFactory._kill_stale_chrome(Path("/p/chrome-profiles/mail4jbd"))

        pattern = calls[0][-1]
        assert pattern.endswith("( |$)")
        assert "mail4jbd" in pattern
