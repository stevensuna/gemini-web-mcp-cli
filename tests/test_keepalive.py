"""Tests for the session keep-alive (issue #3)."""

from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path

import pytest

from gemini_web_mcp_cli.core import keepalive
from gemini_web_mcp_cli.core.keepalive import (
    ALIVE,
    DEAD,
    ERROR,
    RECOVERED,
    SKIPPED,
    KeepaliveLocked,
    ProfileHealth,
    build_keepalive_plist,
    classify_signin_page,
    eligible_profiles,
)
from gemini_web_mcp_cli.core.profiles import ProfileManager


@pytest.fixture
def pm(tmp_path, monkeypatch):
    monkeypatch.setattr(keepalive, "_config_dir", lambda: tmp_path / "gemcli")
    return ProfileManager(config_dir=tmp_path / "gemcli", nlm_config_dir=tmp_path / "nlm")


def _add_profile(pm, tmp_path, name, email="a@gmail.com", chrome=True, cookies=True):
    chrome_dir = tmp_path / "chrome" / name
    if chrome:
        chrome_dir.mkdir(parents=True)
    pm.save_auth(
        {
            "cookies": {"__Secure-1PSID": "psid"} if cookies else {},
            "email": email,
            "chrome_profile_path": str(chrome_dir) if chrome else None,
        },
        name,
    )


class TestEligibleProfiles:
    def test_skips_profiles_without_login_or_chrome(self, pm, tmp_path):
        _add_profile(pm, tmp_path, "good")
        _add_profile(pm, tmp_path, "stray", email="", chrome=False)  # like old "default"
        _add_profile(pm, tmp_path, "nochrome", chrome=False)

        result = dict(eligible_profiles(pm))

        assert result["good"] == ""
        assert "never logged in" in result["stray"]
        assert "no Chrome profile" in result["nochrome"]

    def test_only_limits_to_one_profile(self, pm, tmp_path):
        _add_profile(pm, tmp_path, "one")
        _add_profile(pm, tmp_path, "two")
        assert [n for n, _ in eligible_profiles(pm, only="two")] == ["two"]


class TestClassifySigninPage:
    @pytest.mark.parametrize(
        ("url", "text", "kind"),
        [
            ("https://accounts.google.com/v3/signin/challenge/pk", "", "passkey"),
            ("https://accounts.google.com/x", "Use your fingerprint or Touch ID", "passkey"),
            ("https://accounts.google.com/v3/signin/challenge/pwd", "", "password"),
            ("https://accounts.google.com/x", "Enter your password", "password"),
            ("https://accounts.google.com/v3/signin/challenge/ipp", "", "challenge"),
            ("https://accounts.google.com/x", "Verify it's you", "challenge"),
            ("https://accounts.google.com/AccountChooser", "", "account_chooser"),
            ("https://accounts.google.com/x", "Choose an account", "account_chooser"),
            ("https://accounts.google.com/v3/signin/identifier", "", "email_entry"),
            ("https://accounts.google.com/x", "Email or phone", "email_entry"),
        ],
    )
    def test_kinds(self, url, text, kind):
        assert classify_signin_page(url, text) == kind


class TestExitCodes:
    def test_dead_beats_error(self):
        from gemini_web_mcp_cli.cli import EXIT_AUTH_REQUIRED, _health_exit_code

        results = [ProfileHealth("a", ALIVE), ProfileHealth("b", ERROR),
                   ProfileHealth("c", DEAD)]
        assert _health_exit_code(results) == EXIT_AUTH_REQUIRED

    def test_error_is_one_and_ok_is_zero(self):
        from gemini_web_mcp_cli.cli import _health_exit_code

        assert _health_exit_code([ProfileHealth("a", ERROR)]) == 1
        assert _health_exit_code([ProfileHealth("a", ALIVE), ProfileHealth("b", RECOVERED),
                                  ProfileHealth("c", SKIPPED)]) == 0


class TestPlist:
    def test_runs_periodically_in_gui_session(self, tmp_path):
        plist = build_keepalive_plist("/bin/gemcli", 4, recover=True,
                                      path_env="/bin", log_dir=tmp_path)
        assert "<string>com.gemcli.keepalive</string>" in plist
        assert "<integer>14400</integer>" in plist
        assert "<string>Aqua</string>" in plist
        assert "<string>--recover</string>" in plist
        # A periodic job must not be relaunched by KeepAlive after each run.
        assert "<key>KeepAlive</key>" not in plist

    def test_recover_flag_omitted_by_default(self, tmp_path):
        plist = build_keepalive_plist("/bin/gemcli", 6, recover=False,
                                      path_env="/bin", log_dir=tmp_path)
        assert "--recover" not in plist
        assert "<integer>21600</integer>" in plist


class TestRunLock:
    def test_second_run_is_rejected_while_first_holds_lock(self, pm):
        with keepalive._RunLock():
            with pytest.raises(KeepaliveLocked):
                with keepalive._RunLock():
                    pass
        with keepalive._RunLock():  # released afterwards
            pass


class TestRefreshProfile:
    def test_daemon_profile_uses_daemon_cookies_and_saves(self, pm, tmp_path, monkeypatch):
        _add_profile(pm, tmp_path, "main")
        monkeypatch.setattr(keepalive, "_daemon_port_for", lambda _pm, _n: 9223)
        monkeypatch.setattr(keepalive, "get_gemini_page_ws_url", lambda _p: "ws://daemon")
        monkeypatch.setattr(keepalive, "get_page_cookies", lambda _ws: [
            {"domain": ".google.com", "name": "__Secure-1PSID", "value": "live"},
        ])
        monkeypatch.setattr(keepalive, "_http_signed_in_email",
                            lambda cookies: ("a@gmail.com", None))

        def no_launch(*_a, **_k):
            raise AssertionError("must not launch a second Chrome on the daemon profile")

        monkeypatch.setattr(keepalive, "_ProfileChrome", no_launch)

        result = keepalive.refresh_profile(pm, "main")

        assert result.status == ALIVE and result.method == "daemon"
        assert pm.load_auth("main")["cookies"]["__Secure-1PSID"] == "live"

    def test_signed_out_without_recover_is_dead_and_no_window(self, pm, tmp_path, monkeypatch):
        _add_profile(pm, tmp_path, "idle")
        monkeypatch.setattr(keepalive, "_daemon_port_for", lambda _pm, _n: None)
        monkeypatch.setattr(keepalive, "_profile_in_use", lambda _p: False)
        launches = []

        @contextmanager
        def fake_chrome(path, visible=False):
            launches.append(visible)
            yield type("C", (), {"ws": "ws://own"})()

        monkeypatch.setattr(keepalive, "_ProfileChrome", fake_chrome)
        monkeypatch.setattr(keepalive, "navigate_to_url", lambda _ws, _url: None)
        monkeypatch.setattr(keepalive, "_wait_for_gemini_state",
                            lambda _ws: ("signed_out", ""))

        result = keepalive.refresh_profile(pm, "idle", recover=False)

        assert result.status == DEAD
        assert launches == [False]  # headless only, no visible recovery window

    def test_skips_profile_already_open_elsewhere(self, pm, tmp_path, monkeypatch):
        _add_profile(pm, tmp_path, "busy")
        monkeypatch.setattr(keepalive, "_daemon_port_for", lambda _pm, _n: None)
        monkeypatch.setattr(keepalive, "_profile_in_use", lambda _p: True)
        assert keepalive.refresh_profile(pm, "busy").status == SKIPPED


class TestRunKeepalive:
    def test_logs_each_result(self, pm, tmp_path, monkeypatch):
        _add_profile(pm, tmp_path, "p1")
        monkeypatch.setattr(keepalive, "ProfileManager", lambda: pm)
        monkeypatch.setattr(keepalive, "refresh_profile",
                            lambda _pm, name, recover=False: ProfileHealth(name, ALIVE, "a@x"))
        monkeypatch.setattr(keepalive, "probe_capture",
                            lambda _pm, _name: ("ok", "processSession"))

        results = keepalive.run_keepalive()

        assert [r.status for r in results] == [ALIVE]
        lines = Path(keepalive.log_path()).read_text().splitlines()
        assert json.loads(lines[-1])["profile"] == "p1"
        assert keepalive.read_last_results()["p1"]["status"] == ALIVE
        assert keepalive.read_last_results()["p1"]["capture"] == "ok"
        assert keepalive.read_last_results()["p1"]["transport"] == "processSession"

    def test_capture_failure_recorded_separately_from_alive(self, pm, tmp_path, monkeypatch):
        """Issue #5: a signed-in profile whose token capture fails must not look healthy."""
        from gemini_web_mcp_cli.cli import _health_exit_code

        _add_profile(pm, tmp_path, "p1")
        monkeypatch.setattr(keepalive, "ProfileManager", lambda: pm)
        monkeypatch.setattr(keepalive, "refresh_profile",
                            lambda _pm, name, recover=False: ProfileHealth(name, ALIVE, "a@x"))
        monkeypatch.setattr(keepalive, "probe_capture",
                            lambda _pm, _name: ("failed: TokenFactoryError: no token", ""))

        [result] = keepalive.run_keepalive()

        assert result.status == ALIVE
        assert result.capture_failed
        assert _health_exit_code([result]) == 1

    def test_no_probe_for_dead_profiles_or_when_disabled(self, pm, tmp_path, monkeypatch):
        _add_profile(pm, tmp_path, "p1")
        _add_profile(pm, tmp_path, "p2")
        monkeypatch.setattr(keepalive, "ProfileManager", lambda: pm)
        statuses = {"p1": ALIVE, "p2": DEAD}
        monkeypatch.setattr(keepalive, "refresh_profile",
                            lambda _pm, name, recover=False: ProfileHealth(name, statuses[name]))
        probed = []
        monkeypatch.setattr(keepalive, "probe_capture",
                            lambda _pm, name: probed.append(name) or ("ok", ""))

        keepalive.run_keepalive()
        assert probed == ["p1"]

        probed.clear()
        keepalive.run_keepalive(probe=False)
        assert probed == []

    def test_busy_probe_is_skipped_not_failed(self, pm, tmp_path, monkeypatch):
        from gemini_web_mcp_cli.core import probe

        _add_profile(pm, tmp_path, "p1")
        monkeypatch.setattr(
            probe, "probe_token_capture",
            lambda *a, **k: probe.ProbeResult("token_capture", False, "busy"),
        )
        capture, _ = keepalive.probe_capture(pm, "p1")
        assert capture.startswith("skipped")
        assert not ProfileHealth("p1", ALIVE, capture=capture).capture_failed

    def test_check_only_does_not_log(self, pm, tmp_path, monkeypatch):
        _add_profile(pm, tmp_path, "p1")
        monkeypatch.setattr(keepalive, "ProfileManager", lambda: pm)
        monkeypatch.setattr(keepalive, "check_profile",
                            lambda _pm, name: ProfileHealth(name, ALIVE))

        keepalive.run_keepalive(check_only=True)

        assert not Path(keepalive.log_path()).exists()


class TestCheckProfile:
    def test_rejected_saved_copy_is_stale_not_dead(self, pm, tmp_path, monkeypatch):
        """A stale auth.json doesn't prove the account is signed out."""
        _add_profile(pm, tmp_path, "idle")
        monkeypatch.setattr(keepalive, "_daemon_port_for", lambda _pm, _n: None)
        monkeypatch.setattr(keepalive, "_http_signed_in_email", lambda _c: ("", None))

        result = keepalive.check_profile(pm, "idle")

        assert result.status == keepalive.STALE
        assert "keepalive run" in result.detail

    def test_signed_out_daemon_is_dead(self, pm, tmp_path, monkeypatch):
        _add_profile(pm, tmp_path, "main")
        monkeypatch.setattr(keepalive, "_daemon_port_for", lambda _pm, _n: 9222)
        monkeypatch.setattr(keepalive, "get_gemini_page_ws_url", lambda _p: "ws://d")
        monkeypatch.setattr(keepalive, "get_page_cookies", lambda _ws: [])
        monkeypatch.setattr(keepalive, "_http_signed_in_email", lambda _c: ("", None))

        assert keepalive.check_profile(pm, "main").status == DEAD

    def test_stale_does_not_exit_auth_required(self):
        from gemini_web_mcp_cli.cli import _health_exit_code

        assert _health_exit_code([ProfileHealth("idle", keepalive.STALE)]) == 0
