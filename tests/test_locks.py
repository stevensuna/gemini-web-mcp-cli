"""Tests for the per-profile browser lock (heavy-use stability)."""

import subprocess
import sys
import threading
import time
from unittest.mock import patch

import pytest

from gemini_web_mcp_cli.core import locks
from gemini_web_mcp_cli.core.locks import ProfileBusy, profile_lock


class TestProfileLock:
    def test_second_holder_times_out(self):
        held = threading.Event()
        release = threading.Event()

        def holder():
            with profile_lock("p1"):
                held.set()
                release.wait(5)

        t = threading.Thread(target=holder)
        t.start()
        held.wait(5)
        try:
            with pytest.raises(ProfileBusy, match="p1"):
                with profile_lock("p1", timeout=0.3):
                    pass
        finally:
            release.set()
            t.join()

    def test_waiter_gets_lock_after_release(self):
        order = []
        held = threading.Event()

        def holder():
            with profile_lock("p1"):
                held.set()
                time.sleep(0.4)
                order.append("first")

        t = threading.Thread(target=holder)
        t.start()
        held.wait(5)
        with profile_lock("p1", timeout=5):
            order.append("second")
        t.join()
        assert order == ["first", "second"]

    def test_other_profiles_are_independent(self):
        with profile_lock("p1"):
            with profile_lock("p2", timeout=0):
                pass

    def test_reentrant_on_same_thread(self):
        with profile_lock("p1"):
            with profile_lock("p1", timeout=0):
                pass
        # Fully released afterwards
        done = []
        t = threading.Thread(target=lambda: _acquire_once("p1", done))
        t.start()
        t.join()
        assert done == [True]

    def test_excludes_other_processes(self, tmp_path):
        path = locks._lock_path("p1")
        path.parent.mkdir(parents=True, exist_ok=True)
        code = (
            "import fcntl, sys, time\n"
            f"fh = open({str(path)!r}, 'a')\n"
            "fcntl.flock(fh, fcntl.LOCK_EX)\n"
            "print('held', flush=True)\n"
            "time.sleep(3)\n"
        )
        proc = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, text=True)
        try:
            assert proc.stdout.readline().strip() == "held"
            with pytest.raises(ProfileBusy):
                with profile_lock("p1", timeout=0.2):
                    pass
        finally:
            proc.kill()
            proc.wait()

    def test_busy_is_not_a_token_factory_error(self):
        """The client falls back to plain HTTP on TokenFactoryError; busy must surface."""
        from gemini_web_mcp_cli.core.exceptions import TokenFactoryError

        assert not issubclass(ProfileBusy, TokenFactoryError)


def _acquire_once(name, out):
    with profile_lock(name, timeout=0):
        out.append(True)


class TestTokenFactoryUsesLock:
    def _factory(self):
        from gemini_web_mcp_cli.core.token_factory import TokenFactory

        factory = TokenFactory.__new__(TokenFactory)
        factory._profile_name = "busy"
        factory._idle_timer = None
        factory._idle_generation = 0
        factory._idle_lock = threading.Lock()
        factory._idle_timeout = 0
        factory._we_launched = False
        factory._process = None
        factory._ready = False
        factory._port = None
        factory._ws_url = None
        factory._chrome_profile_path = None
        return factory

    def test_capture_waits_for_other_holder(self, monkeypatch):
        monkeypatch.setenv("GEMCLI_PROFILE_LOCK_TIMEOUT", "0.3")
        factory = self._factory()
        monkeypatch.setattr(
            factory, "_capture_locked", lambda *a, **k: pytest.fail("ran without lock")
        )
        held = threading.Event()
        release = threading.Event()

        def holder():
            with profile_lock("busy"):
                held.set()
                release.wait(5)

        t = threading.Thread(target=holder)
        t.start()
        held.wait(5)
        try:
            with pytest.raises(ProfileBusy):
                factory.capture("hi", None)
        finally:
            release.set()
            t.join()

    def test_ready_factory_reconnects_when_chrome_is_gone(self, monkeypatch):
        factory = self._factory()
        factory._ready = True
        factory._port = 9300
        factory._ws_url = "ws://old"
        monkeypatch.setattr(factory, "_chrome_still_up", lambda: False)
        with patch("gemini_web_mcp_cli.core.token_factory.get_chrome_path", return_value=None):
            # Not ready any more -> goes through launch path, which fails here
            with pytest.raises(Exception, match="No Chromium browser"):
                factory.ensure_ready()
        assert factory._ready is False
        assert factory._ws_url is None

    def test_shutdown_leaves_chrome_running_when_profile_busy(self, monkeypatch):
        from gemini_web_mcp_cli.core import token_factory

        monkeypatch.setattr(token_factory, "_SHUTDOWN_LOCK_WAIT", 0.2)
        factory = self._factory()
        factory._we_launched = True
        factory._port = 9300
        factory._chrome_profile_path = "/tmp/should-not-be-cleaned"

        class _Proc:
            killed = False

            def terminate(self):
                _Proc.killed = True

            kill = terminate

            def wait(self, timeout=None):
                return 0

        factory._process = _Proc()
        held = threading.Event()
        release = threading.Event()

        def holder():
            with profile_lock("busy"):
                held.set()
                release.wait(5)

        t = threading.Thread(target=holder)
        t.start()
        held.wait(5)
        try:
            with (
                patch.object(token_factory, "_clear_port_map") as clear_map,
                patch.object(token_factory, "_clean_lock_files") as clean_locks,
            ):
                factory.shutdown()
        finally:
            release.set()
            t.join()
        assert _Proc.killed is False
        clear_map.assert_not_called()
        clean_locks.assert_not_called()


class TestCliWaitsForRunningJobs:
    def _hold(self, name):
        held, release = threading.Event(), threading.Event()

        def holder():
            with profile_lock(name):
                held.set()
                release.wait(5)

        t = threading.Thread(target=holder)
        t.start()
        held.wait(5)
        return t, release

    def test_chrome_stop_waits_then_fails_busy(self, monkeypatch):
        from click.testing import CliRunner

        from gemini_web_mcp_cli import cli
        from gemini_web_mcp_cli.core import chrome_manager

        monkeypatch.setenv("GEMCLI_PROFILE_LOCK_TIMEOUT", "0.2")
        info = chrome_manager.ChromeDaemonInfo(1, 9222, "busy", 0.0, True, "/x")
        monkeypatch.setattr(chrome_manager, "load_daemon_info", lambda: info)
        stopped = []
        monkeypatch.setattr(chrome_manager, "stop_chrome_daemon",
                            lambda: stopped.append(1) or True)
        t, release = self._hold("busy")
        try:
            result = CliRunner().invoke(cli.cli, ["chrome", "stop"])
            assert result.exit_code == 1
            assert stopped == []
            now = CliRunner().invoke(cli.cli, ["chrome", "stop", "--now"])
            assert now.exit_code == 0
            assert stopped == [1]
        finally:
            release.set()
            t.join()
