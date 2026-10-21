"""Tests for the Chrome daemon manager."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from gemini_web_mcp_cli.cli import (
    _pause_chrome_daemon_for_login,
    _restart_chrome_daemon_after_login,
)
from gemini_web_mcp_cli.core.cdp import BrowserResult, cleanup_orphaned_profile_chrome
from gemini_web_mcp_cli.core.chrome_manager import (
    ChromeDaemonInfo,
    check_daemon_health,
    clear_daemon_info,
    get_gemini_auth_status,
    is_process_alive,
    load_daemon_info,
    save_daemon_info,
    start_chrome_daemon,
    stop_chrome_daemon,
)
from gemini_web_mcp_cli.core.constants import CHROME_USER_AGENT
from gemini_web_mcp_cli.core.exceptions import TokenFactoryError


class TestChromeDaemonInfo:
    """Tests for ChromeDaemonInfo dataclass."""

    def test_construction(self):
        info = ChromeDaemonInfo(
            pid=12345,
            port=9222,
            profile_name="personal",
            started_at=1708300000.0,
            headless=True,
            chrome_profile_path="/path/to/profile",
        )
        assert info.pid == 12345
        assert info.port == 9222
        assert info.profile_name == "personal"
        assert info.headless is True
        assert info.chrome_profile_path == "/path/to/profile"

    def test_to_dict(self):
        info = ChromeDaemonInfo(
            pid=42,
            port=9225,
            profile_name="work",
            started_at=1708300000.0,
            headless=False,
            chrome_profile_path="/test/path",
        )
        d = info.to_dict()
        assert d["pid"] == 42
        assert d["port"] == 9225
        assert d["profile_name"] == "work"
        assert d["headless"] is False
        assert d["chrome_profile_path"] == "/test/path"

    def test_from_dict(self):
        data = {
            "pid": 99,
            "port": 9223,
            "profile_name": "test",
            "started_at": 1708300000.0,
            "headless": True,
            "chrome_profile_path": "/some/path",
        }
        info = ChromeDaemonInfo.from_dict(data)
        assert info.pid == 99
        assert info.port == 9223
        assert info.profile_name == "test"

    def test_roundtrip(self):
        original = ChromeDaemonInfo(
            pid=777,
            port=9224,
            profile_name="roundtrip",
            started_at=time.time(),
            headless=True,
            chrome_profile_path="/round/trip",
        )
        d = original.to_dict()
        restored = ChromeDaemonInfo.from_dict(d)
        assert restored.pid == original.pid
        assert restored.port == original.port
        assert restored.profile_name == original.profile_name
        assert restored.headless == original.headless
        assert restored.started_at == original.started_at
        assert restored.chrome_profile_path == original.chrome_profile_path


class TestDaemonFilePersistence:
    """Tests for load/save/clear daemon info."""

    def test_load_nonexistent_returns_none(self, tmp_path):
        with patch(
            "gemini_web_mcp_cli.core.chrome_manager._daemon_file_path",
            return_value=tmp_path / "chrome-daemon.json",
        ):
            assert load_daemon_info() is None

    def test_save_and_load_roundtrip(self, tmp_path):
        daemon_path = tmp_path / "chrome-daemon.json"
        with patch(
            "gemini_web_mcp_cli.core.chrome_manager._daemon_file_path",
            return_value=daemon_path,
        ):
            info = ChromeDaemonInfo(
                pid=42,
                port=9222,
                profile_name="test",
                started_at=time.time(),
                headless=True,
                chrome_profile_path="/test",
            )
            save_daemon_info(info)
            assert daemon_path.exists()

            loaded = load_daemon_info()
            assert loaded is not None
            assert loaded.pid == 42
            assert loaded.port == 9222
            assert loaded.profile_name == "test"

    def test_load_corrupt_json_returns_none(self, tmp_path):
        daemon_path = tmp_path / "chrome-daemon.json"
        daemon_path.write_text("not valid json{{{", encoding="utf-8")
        with patch(
            "gemini_web_mcp_cli.core.chrome_manager._daemon_file_path",
            return_value=daemon_path,
        ):
            assert load_daemon_info() is None

    def test_load_missing_fields_returns_none(self, tmp_path):
        daemon_path = tmp_path / "chrome-daemon.json"
        daemon_path.write_text(json.dumps({"pid": 1}), encoding="utf-8")
        with patch(
            "gemini_web_mcp_cli.core.chrome_manager._daemon_file_path",
            return_value=daemon_path,
        ):
            assert load_daemon_info() is None

    def test_clear_removes_file(self, tmp_path):
        daemon_path = tmp_path / "chrome-daemon.json"
        daemon_path.write_text("{}", encoding="utf-8")
        with patch(
            "gemini_web_mcp_cli.core.chrome_manager._daemon_file_path",
            return_value=daemon_path,
        ):
            clear_daemon_info()
            assert not daemon_path.exists()

    def test_clear_nonexistent_is_noop(self, tmp_path):
        with patch(
            "gemini_web_mcp_cli.core.chrome_manager._daemon_file_path",
            return_value=tmp_path / "chrome-daemon.json",
        ):
            # Should not raise
            clear_daemon_info()

    def test_save_creates_parent_dirs(self, tmp_path):
        daemon_path = tmp_path / "nested" / "dir" / "chrome-daemon.json"
        with patch(
            "gemini_web_mcp_cli.core.chrome_manager._daemon_file_path",
            return_value=daemon_path,
        ):
            info = ChromeDaemonInfo(
                pid=1,
                port=9222,
                profile_name="test",
                started_at=time.time(),
                headless=True,
                chrome_profile_path="/test",
            )
            save_daemon_info(info)
            assert daemon_path.exists()


class TestIsProcessAlive:
    """Tests for process liveness checking."""

    def test_current_process_is_alive(self):
        # Our own PID is always alive, but won't have "chrome" in comm.
        # is_process_alive checks for "chrome" in ps output, so this will
        # return False for a python process. That's correct behavior.
        # We test the os.kill(pid, 0) path separately.
        pid = os.getpid()
        # os.kill should not raise for our own process
        try:
            os.kill(pid, 0)
            alive = True
        except OSError:
            alive = False
        assert alive is True

    def test_nonexistent_pid_is_not_alive(self):
        # PID 99999999 should not exist on any system
        assert is_process_alive(99999999) is False

    def test_chrome_process_detected(self):
        """Verify that a process with 'chrome' in comm is detected."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.stdout = "Google Chrome"
            with patch("os.kill"):  # Don't actually send signals
                assert is_process_alive(12345) is True

    def test_non_chrome_process_rejected(self):
        """Verify that a non-Chrome process is rejected (recycled PID protection)."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.stdout = "python3"
            with patch("os.kill"):
                assert is_process_alive(12345) is False


class TestCheckDaemonHealth:
    """Tests for the health check logic."""

    def test_no_daemon_file(self, tmp_path):
        with patch(
            "gemini_web_mcp_cli.core.chrome_manager._daemon_file_path",
            return_value=tmp_path / "chrome-daemon.json",
        ):
            info, status = check_daemon_health()
            assert info is None
            assert status == "not_running"

    def test_stale_daemon_auto_cleans(self, tmp_path):
        daemon_path = tmp_path / "chrome-daemon.json"
        stale_info = ChromeDaemonInfo(
            pid=99999999,
            port=9222,
            profile_name="test",
            started_at=time.time(),
            headless=True,
            chrome_profile_path="/test",
        )
        daemon_path.write_text(json.dumps(stale_info.to_dict()), encoding="utf-8")

        with patch(
            "gemini_web_mcp_cli.core.chrome_manager._daemon_file_path",
            return_value=daemon_path,
        ):
            info, status = check_daemon_health()
            assert status == "stale"
            assert info is not None
            assert info.pid == 99999999
            # Daemon file should be auto-cleaned
            assert not daemon_path.exists()

    def test_running_daemon(self, tmp_path):
        daemon_path = tmp_path / "chrome-daemon.json"
        info = ChromeDaemonInfo(
            pid=12345,
            port=9222,
            profile_name="test",
            started_at=time.time(),
            headless=True,
            chrome_profile_path="/test",
        )
        daemon_path.write_text(json.dumps(info.to_dict()), encoding="utf-8")

        with (
            patch(
                "gemini_web_mcp_cli.core.chrome_manager._daemon_file_path",
                return_value=daemon_path,
            ),
            patch(
                "gemini_web_mcp_cli.core.chrome_manager.is_process_alive",
                return_value=True,
            ),
            patch(
                "gemini_web_mcp_cli.core.chrome_manager.is_chrome_responsive",
                return_value=True,
            ),
            patch(
                "gemini_web_mcp_cli.core.chrome_manager.is_chrome_healthy",
                return_value=True,
            ),
        ):
            loaded, status = check_daemon_health()
            assert status == "running"
            assert loaded.pid == 12345

    def test_unresponsive_daemon(self, tmp_path):
        daemon_path = tmp_path / "chrome-daemon.json"
        info = ChromeDaemonInfo(
            pid=12345,
            port=9222,
            profile_name="test",
            started_at=time.time(),
            headless=True,
            chrome_profile_path="/test",
        )
        daemon_path.write_text(json.dumps(info.to_dict()), encoding="utf-8")

        with (
            patch(
                "gemini_web_mcp_cli.core.chrome_manager._daemon_file_path",
                return_value=daemon_path,
            ),
            patch(
                "gemini_web_mcp_cli.core.chrome_manager.is_process_alive",
                return_value=True,
            ),
            patch(
                "gemini_web_mcp_cli.core.chrome_manager.is_chrome_responsive",
                return_value=False,
            ),
        ):
            loaded, status = check_daemon_health()
            assert status == "unresponsive"
            assert loaded.pid == 12345

    def test_old_daemon_is_restarted(self, tmp_path):
        from gemini_web_mcp_cli.core.chrome_manager import (
            _DAEMON_MAX_AGE_SECONDS,
        )

        daemon_path = tmp_path / "chrome-daemon.json"
        info = ChromeDaemonInfo(
            pid=12345,
            port=9222,
            profile_name="test",
            started_at=time.time() - _DAEMON_MAX_AGE_SECONDS - 1,
            headless=True,
            chrome_profile_path="/test",
        )
        daemon_path.write_text(json.dumps(info.to_dict()), encoding="utf-8")
        fresh = ChromeDaemonInfo(
            pid=999, port=9222, profile_name="test", started_at=time.time(),
            headless=True, chrome_profile_path="/test",
        )

        with (
            patch(
                "gemini_web_mcp_cli.core.chrome_manager._daemon_file_path",
                return_value=daemon_path,
            ),
            patch(
                "gemini_web_mcp_cli.core.chrome_manager.is_process_alive",
                return_value=True,
            ),
            patch(
                "gemini_web_mcp_cli.core.chrome_manager.is_chrome_responsive",
                return_value=True,
            ),
            patch(
                "gemini_web_mcp_cli.core.chrome_manager.is_chrome_healthy",
                return_value=True,
            ),
            patch(
                "gemini_web_mcp_cli.core.chrome_manager._get_process_rss_mb",
                return_value=500.0,
            ),
            patch(
                "gemini_web_mcp_cli.core.chrome_manager.stop_chrome_daemon",
            ) as stop,
            patch(
                "gemini_web_mcp_cli.core.chrome_manager.start_chrome_daemon",
                return_value=fresh,
            ) as start,
        ):
            loaded, status = check_daemon_health()
            assert status == "running"
            assert loaded is fresh
            stop.assert_called_once()
            start.assert_called_once_with(
                profile_name="test", chrome_profile_path="/test", headless=True, port=9222,
            )

    def test_oversized_daemon_is_restarted(self, tmp_path):
        from gemini_web_mcp_cli.core.chrome_manager import (
            _DAEMON_MAX_RSS_MB,
        )

        daemon_path = tmp_path / "chrome-daemon.json"
        info = ChromeDaemonInfo(
            pid=12345,
            port=9222,
            profile_name="test",
            started_at=time.time(),
            headless=True,
            chrome_profile_path="/test",
        )
        daemon_path.write_text(json.dumps(info.to_dict()), encoding="utf-8")
        fresh = ChromeDaemonInfo(
            pid=999, port=9222, profile_name="test", started_at=time.time(),
            headless=True, chrome_profile_path="/test",
        )

        with (
            patch(
                "gemini_web_mcp_cli.core.chrome_manager._daemon_file_path",
                return_value=daemon_path,
            ),
            patch(
                "gemini_web_mcp_cli.core.chrome_manager.is_process_alive",
                return_value=True,
            ),
            patch(
                "gemini_web_mcp_cli.core.chrome_manager.is_chrome_responsive",
                return_value=True,
            ),
            patch(
                "gemini_web_mcp_cli.core.chrome_manager.is_chrome_healthy",
                return_value=True,
            ),
            patch(
                "gemini_web_mcp_cli.core.chrome_manager._get_process_rss_mb",
                return_value=float(_DAEMON_MAX_RSS_MB + 1),
            ),
            patch(
                "gemini_web_mcp_cli.core.chrome_manager.stop_chrome_daemon",
            ) as stop,
            patch(
                "gemini_web_mcp_cli.core.chrome_manager.start_chrome_daemon",
                return_value=fresh,
            ) as start,
        ):
            loaded, status = check_daemon_health()
            assert status == "running"
            assert loaded is fresh
            stop.assert_called_once()
            start.assert_called_once_with(
                profile_name="test", chrome_profile_path="/test", headless=True, port=9222,
            )

    def test_fresh_small_daemon_running(self, tmp_path):
        daemon_path = tmp_path / "chrome-daemon.json"
        info = ChromeDaemonInfo(
            pid=12345,
            port=9222,
            profile_name="test",
            started_at=time.time(),
            headless=True,
            chrome_profile_path="/test",
        )
        daemon_path.write_text(json.dumps(info.to_dict()), encoding="utf-8")

        with (
            patch(
                "gemini_web_mcp_cli.core.chrome_manager._daemon_file_path",
                return_value=daemon_path,
            ),
            patch(
                "gemini_web_mcp_cli.core.chrome_manager.is_process_alive",
                return_value=True,
            ),
            patch(
                "gemini_web_mcp_cli.core.chrome_manager.is_chrome_responsive",
                return_value=True,
            ),
            patch(
                "gemini_web_mcp_cli.core.chrome_manager.is_chrome_healthy",
                return_value=True,
            ),
            patch(
                "gemini_web_mcp_cli.core.chrome_manager._get_process_rss_mb",
                return_value=500.0,
            ),
        ):
            loaded, status = check_daemon_health()
            assert status == "running"
            assert loaded.pid == 12345

    def test_get_process_rss_mb_invalid_pid_returns_zero(self):
        from gemini_web_mcp_cli.core.chrome_manager import _get_process_rss_mb

        assert _get_process_rss_mb(0) == 0.0
        assert _get_process_rss_mb(-1) == 0.0


class TestGeminiAuthStatus:
    def test_delegates_read_only_and_never_syncs(self):
        """chrome status must not inject saved cookies into the daemon (issue #3)."""
        from gemini_web_mcp_cli.core.browser_auth import BrowserAuthStatus

        expected = BrowserAuthStatus(
            ws_url="ws://test",
            cookies={"__Secure-1PSID": "psid-cookie"},
            access_token="fresh-snlm0e",
        )

        with patch(
            "gemini_web_mcp_cli.core.chrome_manager.get_browser_auth_status_for_port",
            return_value=expected,
        ) as get_status:
            status = get_gemini_auth_status(9222, "default")

        assert status is expected
        get_status.assert_called_once_with(9222)


def _login_daemon_info(
    profile_name: str = "default",
    path: str = "/tmp/gemcli-profile",
):
    return ChromeDaemonInfo(
        pid=12345,
        port=9223,
        profile_name=profile_name,
        started_at=1708300000.0,
        headless=True,
        chrome_profile_path=path,
    )


class TestLoginChromeDaemonHandling:
    def test_login_pauses_matching_chrome_daemon(self):
        info = _login_daemon_info()

        with (
            patch(
                "gemini_web_mcp_cli.core.chrome_manager.check_daemon_health",
                return_value=(info, "running"),
            ),
            patch(
                "gemini_web_mcp_cli.core.chrome_manager.stop_chrome_daemon",
                return_value=True,
            ) as stop,
        ):
            paused = _pause_chrome_daemon_for_login("default", "/tmp/gemcli-profile")

        assert paused is info
        stop.assert_called_once_with()

    def test_login_does_not_pause_different_profile_daemon(self):
        info = _login_daemon_info(profile_name="work", path="/tmp/work-profile")

        with (
            patch(
                "gemini_web_mcp_cli.core.chrome_manager.check_daemon_health",
                return_value=(info, "running"),
            ),
            patch("gemini_web_mcp_cli.core.chrome_manager.stop_chrome_daemon") as stop,
        ):
            paused = _pause_chrome_daemon_for_login("default", "/tmp/default-profile")

        assert paused is None
        stop.assert_not_called()

    def test_login_restarts_paused_chrome_daemon(self):
        info = _login_daemon_info()

        with patch(
            "gemini_web_mcp_cli.core.chrome_manager.start_chrome_daemon"
        ) as start:
            _restart_chrome_daemon_after_login(info)

        start.assert_called_once_with(
            profile_name="default",
            chrome_profile_path="/tmp/gemcli-profile",
            headless=True,
            port=9223,
        )

    def test_login_restart_warning_does_not_raise(self):
        info = _login_daemon_info()

        with patch(
            "gemini_web_mcp_cli.core.chrome_manager.start_chrome_daemon",
            side_effect=TokenFactoryError("port busy"),
        ):
            _restart_chrome_daemon_after_login(info)

    def test_login_restart_falls_back_to_available_port(self):
        info = _login_daemon_info()

        with patch(
            "gemini_web_mcp_cli.core.chrome_manager.start_chrome_daemon",
            side_effect=[
                TokenFactoryError("Port 9223 is already in use."),
                SimpleNamespace(port=9228),
            ],
        ) as start:
            _restart_chrome_daemon_after_login(info)

        assert start.call_count == 2
        assert start.call_args_list[1].kwargs == {
            "profile_name": "default",
            "chrome_profile_path": "/tmp/gemcli-profile",
            "headless": True,
            "port": None,
        }


class TestCleanupOrphanedProfileChrome:
    def test_pgrep_pattern_starting_with_dash_is_not_treated_as_option(self):
        with (
            patch("gemini_web_mcp_cli.core.cdp.platform.system", return_value="Darwin"),
            patch(
                "gemini_web_mcp_cli.core.cdp.subprocess.run",
                return_value=SimpleNamespace(stdout="", returncode=1),
            ) as run,
        ):
            cleaned = cleanup_orphaned_profile_chrome(Path("/tmp/gemcli-profile"))

        assert cleaned is False
        assert run.call_args.args[0] == [
            "pgrep",
            "-f",
            "--",
            "--user-data-dir=/tmp/gemcli-profile( |$)",
        ]


class TestRestartDaemon:
    def test_reports_not_running_when_chrome_cannot_start(self):
        from gemini_web_mcp_cli.core.chrome_manager import _restart_daemon

        old = ChromeDaemonInfo(
            pid=1, port=9222, profile_name="test", started_at=0.0,
            headless=True, chrome_profile_path="/test",
        )
        with (
            patch("gemini_web_mcp_cli.core.chrome_manager.stop_chrome_daemon"),
            patch(
                "gemini_web_mcp_cli.core.chrome_manager.start_chrome_daemon",
                side_effect=TokenFactoryError("no GUI session"),
            ) as start,
        ):
            assert _restart_daemon(old) == (None, "not_running")
        # tried the same port, then any free port
        assert [c.kwargs["port"] for c in start.call_args_list] == [9222, None]


class TestStopChromeDaemon:
    def test_pid_zero_cleans_recorded_port_without_killing_process_group(self, tmp_path):
        daemon_path = tmp_path / "chrome-daemon.json"
        profile_path = tmp_path / "chrome-profile"
        info = ChromeDaemonInfo(
            pid=0,
            port=9223,
            profile_name="default",
            started_at=time.time(),
            headless=True,
            chrome_profile_path=str(profile_path),
        )
        daemon_path.write_text(json.dumps(info.to_dict()), encoding="utf-8")

        with (
            patch(
                "gemini_web_mcp_cli.core.chrome_manager._daemon_file_path",
                return_value=daemon_path,
            ),
            patch(
                "gemini_web_mcp_cli.core.chrome_manager.cleanup_zombie_chrome"
            ) as cleanup,
            patch("gemini_web_mcp_cli.core.chrome_manager._clear_port_map"),
            patch("gemini_web_mcp_cli.core.chrome_manager._clean_lock_files"),
            patch("gemini_web_mcp_cli.core.chrome_manager.is_process_alive") as alive,
        ):
            assert stop_chrome_daemon() is True

        alive.assert_not_called()
        cleanup.assert_called_once_with(9223, profile_dir=Path(profile_path))

    def test_dead_daemon_cleans_recorded_chrome_profile_path(self, tmp_path):
        daemon_path = tmp_path / "chrome-daemon.json"
        profile_path = tmp_path / "custom-profile"
        info = ChromeDaemonInfo(
            pid=99999999,
            port=9224,
            profile_name="default",
            started_at=time.time(),
            headless=True,
            chrome_profile_path=str(profile_path),
        )
        daemon_path.write_text(json.dumps(info.to_dict()), encoding="utf-8")

        with (
            patch(
                "gemini_web_mcp_cli.core.chrome_manager._daemon_file_path",
                return_value=daemon_path,
            ),
            patch(
                "gemini_web_mcp_cli.core.chrome_manager.is_process_alive",
                return_value=False,
            ),
            patch("gemini_web_mcp_cli.core.chrome_manager._clear_port_map"),
            patch("gemini_web_mcp_cli.core.chrome_manager._clean_lock_files") as clean,
        ):
            assert stop_chrome_daemon() is True

        clean.assert_called_once_with(Path(profile_path))


class TestStartChromeDaemon:
    def test_launch_args_match_token_factory_browser_flags(self, tmp_path):
        class FakeProcess:
            pid = 12345

        with (
            patch(
                "gemini_web_mcp_cli.core.chrome_manager.check_daemon_health",
                return_value=(None, "not_running"),
            ),
            patch(
                "gemini_web_mcp_cli.core.chrome_manager.find_existing_gemcli_chrome",
                return_value=(None, None),
            ),
            patch(
                "gemini_web_mcp_cli.core.cdp._find_browser_binary",
                return_value=BrowserResult(
                    "Google Chrome",
                    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                ),
            ),
            patch(
                "gemini_web_mcp_cli.core.chrome_manager.find_available_port",
                return_value=9333,
            ),
            patch(
                "gemini_web_mcp_cli.core.chrome_manager.is_chrome_responsive",
                return_value=True,
            ),
            patch(
                "gemini_web_mcp_cli.core.chrome_manager.save_daemon_info",
            ),
            patch(
                "gemini_web_mcp_cli.core.chrome_manager._write_port_map",
            ),
            patch("subprocess.Popen", return_value=FakeProcess()) as popen,
        ):
            info = start_chrome_daemon(
                profile_name="default",
                chrome_profile_path=str(tmp_path / "chrome-profile"),
                headless=True,
            )

        args = popen.call_args.args[0]
        assert info.port == 9333
        assert "--headless" in args
        assert f"--user-agent={CHROME_USER_AGENT}" in args
        assert "--disable-blink-features=AutomationControlled" in args


class TestHeavyUseStability:
    """Daemon behaviour under concurrent use (issues #4, #7)."""

    def test_restart_deferred_while_profile_busy(self, tmp_path):
        import threading

        from gemini_web_mcp_cli.core.chrome_manager import _DAEMON_MAX_AGE_SECONDS
        from gemini_web_mcp_cli.core.locks import profile_lock

        daemon_path = tmp_path / "chrome-daemon.json"
        info = ChromeDaemonInfo(
            pid=12345, port=9222, profile_name="busy",
            started_at=time.time() - _DAEMON_MAX_AGE_SECONDS - 1,
            headless=True, chrome_profile_path="/test",
        )
        daemon_path.write_text(json.dumps(info.to_dict()), encoding="utf-8")
        held, release = threading.Event(), threading.Event()

        def holder():
            with profile_lock("busy"):
                held.set()
                release.wait(5)

        t = threading.Thread(target=holder)
        t.start()
        held.wait(5)
        try:
            with (
                patch("gemini_web_mcp_cli.core.chrome_manager._daemon_file_path",
                      return_value=daemon_path),
                patch("gemini_web_mcp_cli.core.chrome_manager.is_process_alive",
                      return_value=True),
                patch("gemini_web_mcp_cli.core.chrome_manager.is_chrome_responsive",
                      return_value=True),
                patch("gemini_web_mcp_cli.core.chrome_manager.is_chrome_healthy",
                      return_value=True),
                patch("gemini_web_mcp_cli.core.chrome_manager._get_process_rss_mb",
                      return_value=100.0),
                patch("gemini_web_mcp_cli.core.chrome_manager._restart_daemon") as restart,
            ):
                _, status = check_daemon_health()
        finally:
            release.set()
            t.join()
        assert status == "running"
        restart.assert_not_called()

    def test_start_reports_early_exit_and_lock_owner(self, tmp_path, monkeypatch):
        from gemini_web_mcp_cli.core import chrome_manager

        profile_dir = tmp_path / "prof"
        profile_dir.mkdir()
        os.symlink("myhost-4242", profile_dir / "SingletonLock")

        class _Proc:
            pid = 777

            def poll(self):
                return 0

        monkeypatch.setattr(chrome_manager, "check_daemon_health",
                            lambda: (None, "not_running"))
        monkeypatch.setattr(chrome_manager, "find_existing_gemcli_chrome",
                            lambda profile_name: (None, None))
        monkeypatch.setattr(chrome_manager, "_find_browser_binary",
                            lambda: type("B", (), {"name": "Chrome", "path": "/x"})())
        monkeypatch.setattr(chrome_manager, "find_available_port", lambda: 9555)
        monkeypatch.setattr(chrome_manager.subprocess, "Popen", lambda *a, **k: _Proc())
        monkeypatch.setattr(chrome_manager, "is_chrome_responsive", lambda port: False)
        monkeypatch.setattr(chrome_manager.time, "sleep", lambda s: None)

        with pytest.raises(TokenFactoryError) as exc:
            chrome_manager.start_chrome_daemon("prof", str(profile_dir))
        assert "exited with code 0" in str(exc.value)
        assert "myhost-4242" in str(exc.value)

    def test_start_timeout_is_configurable(self, monkeypatch):
        from gemini_web_mcp_cli.core import chrome_manager

        monkeypatch.setenv("GEMCLI_CHROME_START_TIMEOUT", "45")
        assert chrome_manager._start_timeout() == 45.0
        monkeypatch.setenv("GEMCLI_CHROME_START_TIMEOUT", "junk")
        assert chrome_manager._start_timeout() == chrome_manager._START_TIMEOUT_DEFAULT

    def test_slow_chrome_is_not_killed(self, monkeypatch):
        import httpx

        from gemini_web_mcp_cli.core import cdp

        monkeypatch.setattr(cdp, "_read_port_map",
                            lambda: {"9223": {"profile": "p", "pid": 4818}})

        def slow_get(*a, **k):
            raise httpx.ReadTimeout("slow")

        monkeypatch.setattr(cdp.httpx, "get", slow_get)
        with patch.object(cdp, "cleanup_zombie_chrome") as cleanup:
            assert cdp.find_existing_gemcli_chrome(profile_name="p") == (None, None)
        cleanup.assert_not_called()
