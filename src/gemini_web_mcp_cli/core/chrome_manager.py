"""Chrome daemon manager: persistent Chrome for Token Factory.

Manages a persistent Chrome instance that background processes (e.g., OpenClaw
LaunchAgent) can use for BotGuard token generation. The Token Factory's
find_existing_chrome() will discover it automatically.

Usage:
    gemcli chrome start    # Launch persistent Chrome (from interactive terminal)
    gemcli chrome stop     # Kill the persistent Chrome
    gemcli chrome status   # Check health and auth status
"""

from __future__ import annotations

import os
import signal
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

import httpx
from loguru import logger

from .browser_auth import get_browser_auth_status_for_port
from .cdp import (
    _chrome_base_args,
    _clean_lock_files,
    _clear_port_map,
    _find_browser_binary,
    _read_port_map,
    _write_port_map,
    cleanup_zombie_chrome,
    find_available_port,
    find_existing_gemcli_chrome,
    get_chrome_profile_dir,
    get_supported_browsers,
    is_chrome_healthy,
)
from .constants import CHROME_USER_AGENT, CONFIG_DIR_NAME
from .exceptions import GeminiError, TokenFactoryError
from .json_io import read_json_dict, write_json_file
from .locks import profile_lock

DAEMON_FILE = "chrome-daemon.json"
GEMINI_APP_URL = "https://gemini.google.com/app"

_DAEMON_MAX_AGE_SECONDS = 12 * 3600
_DAEMON_MAX_RSS_MB = 1500

# How long a freshly launched Chrome gets to answer CDP. Cold starts under
# load (and sibling Chrome-driving tools) regularly take longer than a few
# seconds (issue #4). Override with GEMCLI_CHROME_START_TIMEOUT (seconds).
_START_TIMEOUT_DEFAULT = 30.0


class DaemonAlreadyRunning(TokenFactoryError):
    """A healthy daemon is already running; starting another is a no-op."""


def _start_timeout() -> float:
    try:
        return float(os.environ.get("GEMCLI_CHROME_START_TIMEOUT", _START_TIMEOUT_DEFAULT))
    except ValueError:
        return _START_TIMEOUT_DEFAULT


def _singleton_lock_owner(profile_dir: Path) -> str | None:
    """Return "host-pid" from the profile's SingletonLock symlink, if any."""
    try:
        return os.readlink(profile_dir / "SingletonLock")
    except OSError:
        return None


def _kill_process_group(process: subprocess.Popen) -> None:
    """Kill a launched Chrome and its helpers (it runs in its own session)."""
    try:
        os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=5)
    except Exception:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except Exception:
            try:
                process.kill()
            except Exception:
                pass


@dataclass
class ChromeDaemonInfo:
    """State of the persistent Chrome daemon."""

    pid: int
    port: int
    profile_name: str
    started_at: float
    headless: bool
    chrome_profile_path: str

    def to_dict(self) -> dict:
        return {
            "pid": self.pid,
            "port": self.port,
            "profile_name": self.profile_name,
            "started_at": self.started_at,
            "headless": self.headless,
            "chrome_profile_path": self.chrome_profile_path,
        }

    @classmethod
    def from_dict(cls, data: dict) -> ChromeDaemonInfo:
        return cls(
            pid=data["pid"],
            port=data["port"],
            profile_name=data["profile_name"],
            started_at=data["started_at"],
            headless=data["headless"],
            chrome_profile_path=data["chrome_profile_path"],
        )


def same_chrome_profile_path(left: str | None, right: str | None) -> bool:
    """Return True when both paths point to the same Chrome profile directory."""
    if not left or not right:
        return False
    try:
        return Path(left).expanduser().resolve() == Path(right).expanduser().resolve()
    except OSError:
        return Path(left).expanduser() == Path(right).expanduser()


def _daemon_file_path() -> Path:
    """Return path to the daemon state file."""
    return Path.home() / CONFIG_DIR_NAME / DAEMON_FILE


def load_daemon_info() -> ChromeDaemonInfo | None:
    """Load daemon info from disk. Returns None if file doesn't exist."""
    data = read_json_dict(_daemon_file_path())
    if not data:
        return None
    try:
        return ChromeDaemonInfo.from_dict(data)
    except (KeyError, TypeError, ValueError) as e:
        logger.debug(f"Failed to load daemon info: {e}")
        return None


def save_daemon_info(info: ChromeDaemonInfo) -> None:
    """Save daemon info to disk."""
    write_json_file(_daemon_file_path(), info.to_dict())


def clear_daemon_info() -> None:
    """Remove the daemon file."""
    path = _daemon_file_path()
    if path.exists():
        path.unlink()


def is_process_alive(pid: int) -> bool:
    """Check if a process with the given PID is running.

    Uses os.kill(pid, 0) to check existence, then verifies the process
    is actually Chrome (not a recycled PID) via ps on macOS/Linux.
    """
    try:
        os.kill(pid, 0)
    except OSError:
        return False

    # Verify it's actually Chrome (prevent killing a recycled PID)
    try:
        result = subprocess.run(
            ["ps", "-p", str(pid), "-o", "comm="],
            capture_output=True, text=True, timeout=5,
        )
        comm = result.stdout.strip().lower()
        return "chrome" in comm or "chromium" in comm
    except Exception:
        # If ps fails, trust os.kill result
        return True


def is_chrome_responsive(port: int) -> bool:
    """Check if Chrome is responding to CDP on the given port."""
    try:
        resp = httpx.get(f"http://localhost:{port}/json/version", timeout=2)
        return resp.status_code == 200
    except Exception:
        return False


def get_gemini_auth_status(port: int, profile_name: str | None = None):
    """Return verified Gemini browser auth status for a Chrome instance."""
    try:
        # Report only; never inject saved cookies into the daemon (issue #3).
        return get_browser_auth_status_for_port(port)
    except Exception as e:
        logger.debug(f"Auth check failed: {e}")
        from .browser_auth import BrowserAuthStatus

        return BrowserAuthStatus(error=str(e))


def is_gemini_authenticated(port: int) -> bool:
    """Check if Chrome has verified Gemini auth, including live SNlM0e."""
    return get_gemini_auth_status(port).is_authenticated


def _get_process_rss_mb(pid: int) -> float:
    """Return the resident set size of a process in MB, or 0.0 on failure.

    Guards against pid <= 0 because start_chrome_daemon() records pid=0
    when it reuses an existing Chrome instance and has no PID to track.
    """
    if pid <= 0:
        return 0.0
    try:
        result = subprocess.run(
            ["ps", "-o", "rss=", "-p", str(pid)],
            capture_output=True, text=True, timeout=5,
        )
        return int(result.stdout.strip()) / 1024
    except Exception:
        return 0.0


def check_daemon_health() -> tuple[ChromeDaemonInfo | None, str]:
    """Full health check of the persistent Chrome daemon.

    Returns:
        (info, status) where status is one of:
        - "running": PID alive AND CDP responding AND has functional pages
        - "zombie": PID alive AND CDP responding BUT no functional pages
        - "stale": PID file exists but process is dead (auto-cleaned)
        - "unresponsive": PID alive but CDP not responding
        - "not_running": no daemon file OR daemon was auto-cleaned because
          its age exceeded _DAEMON_MAX_AGE_SECONDS or its RSS exceeded
          _DAEMON_MAX_RSS_MB (prevents long-session memory leaks)
    """
    info = load_daemon_info()
    if info is None:
        return None, "not_running"

    if not is_process_alive(info.pid):
        logger.debug(f"Chrome daemon PID {info.pid} is dead, cleaning up")
        clear_daemon_info()
        # Clean lock files too
        profile_dir = get_chrome_profile_dir(info.profile_name)
        _clean_lock_files(profile_dir)
        return info, "stale"

    age = time.time() - info.started_at
    rss_mb = _get_process_rss_mb(info.pid)
    reason = None
    if age > _DAEMON_MAX_AGE_SECONDS:
        reason = (
            f"age {age / 3600:.1f}h exceeds {_DAEMON_MAX_AGE_SECONDS / 3600:.0f}h limit"
        )
    elif rss_mb > _DAEMON_MAX_RSS_MB:
        reason = f"RSS {rss_mb:.0f} MB exceeds {_DAEMON_MAX_RSS_MB} MB limit"
    if reason:
        # Restart only while no other process is driving this Chrome;
        # otherwise a restart kills its in-flight request. A later check
        # (next request or keep-alive run) will restart it.
        try:
            with profile_lock(info.profile_name, timeout=0):
                logger.info(f"Chrome daemon {reason} — restarting")
                return _restart_daemon(info)
        except GeminiError:
            logger.debug(f"Chrome daemon {reason}, but it is in use — restart deferred")

    if not is_chrome_responsive(info.port):
        return info, "unresponsive"

    # Zombie detection: responsive but no functional pages
    if not is_chrome_healthy(info.port):
        return info, "zombie"

    return info, "running"


def _restart_daemon(info: ChromeDaemonInfo) -> tuple[ChromeDaemonInfo | None, str]:
    """Replace an aged/oversized daemon with a fresh one on the same profile.

    Background jobs rely on the daemon, so stopping it without a replacement
    leaves them without Chrome. Falls back to any free port if the old one is
    still taken. Returns (None, "not_running") if Chrome cannot be started
    (e.g. from a context without a GUI session).
    """
    stop_chrome_daemon()
    for port in (info.port, None):
        try:
            fresh = start_chrome_daemon(
                profile_name=info.profile_name,
                chrome_profile_path=info.chrome_profile_path,
                headless=info.headless,
                port=port,
            )
            logger.info(f"Chrome daemon restarted (PID {fresh.pid}, port {fresh.port})")
            return fresh, "running"
        except TokenFactoryError as e:
            logger.debug(f"Chrome daemon restart on port {port} failed: {e}")
    logger.warning(
        "Chrome daemon was stopped (age/memory limit) and could not be restarted "
        "from this process — run `gemcli chrome start` from a terminal."
    )
    return None, "not_running"


def cleanup_all_zombies() -> list[dict]:
    """Scan the port map and kill any zombie Chrome instances.

    A zombie is a Chrome that is alive and responds to CDP but has
    zero functional pages. These are useless and will cause failures
    if any component tries to reuse them.

    Returns:
        List of dicts describing each cleaned-up zombie:
        [{"port": int, "pid": int, "profile": str}]
    """
    port_map = _read_port_map()
    cleaned = []

    for port_str, entry in list(port_map.items()):
        port = int(port_str)
        pid = entry.get("pid")
        profile = entry.get("profile", "unknown")

        # Check if responsive first
        if not is_chrome_responsive(port):
            # Not responsive — stale port map entry, just clean it
            _clear_port_map(port)
            continue

        # If responsive but has no pages → zombie
        if not is_chrome_healthy(port):
            profile_dir = get_chrome_profile_dir(profile)
            cleanup_zombie_chrome(port, pid=pid, profile_dir=profile_dir)
            cleaned.append({"port": port, "pid": pid, "profile": profile})
            logger.info(
                f"Cleaned zombie: PID {pid} on port {port} "
                f"(profile: {profile})"
            )

    # Also check the daemon file
    info = load_daemon_info()
    if info and not is_chrome_healthy(info.port):
        if is_chrome_responsive(info.port):
            profile_dir = get_chrome_profile_dir(info.profile_name)
            cleanup_zombie_chrome(
                info.port, pid=info.pid, profile_dir=profile_dir
            )
            clear_daemon_info()
            cleaned.append({
                "port": info.port,
                "pid": info.pid,
                "profile": info.profile_name,
            })

    return cleaned


def start_chrome_daemon(
    profile_name: str,
    chrome_profile_path: str,
    headless: bool = True,
    port: int | None = None,
) -> ChromeDaemonInfo:
    """Start Chrome as a persistent background daemon.

    Must be run from an interactive terminal (macOS security requirement).
    Chrome is detached from the terminal and survives terminal close.

    Uses dynamic port selection and port-to-profile mapping to coexist
    with other CDP consumers (e.g., Antigravity browser, NLM CLI).

    Args:
        profile_name: Auth profile name.
        chrome_profile_path: Chrome user-data-dir path.
        headless: If True (default), run headless. If False, show Chrome window.
        port: Specific CDP port. If None, auto-selects an available port.

    Returns:
        ChromeDaemonInfo with PID, port, etc.

    Raises:
        TokenFactoryError: If Chrome can't be started.
    """
    # Check if our daemon is already running
    existing_info, status = check_daemon_health()
    if status == "running":
        raise DaemonAlreadyRunning(
            f"Chrome daemon is already running (PID {existing_info.pid}, "
            f"port {existing_info.port}). Stop it first: gemcli chrome stop"
        )

    # Try to reuse an existing gemcli Chrome instance for this profile
    existing_port, debugger_url = find_existing_gemcli_chrome(
        profile_name=profile_name
    )
    if existing_port and debugger_url:
        logger.info(
            f"Reusing existing Chrome on port {existing_port} "
            f"for profile '{profile_name}'"
        )
        # We didn't launch it, but track it as our daemon
        info = ChromeDaemonInfo(
            pid=0,  # Unknown PID for reused instance
            port=existing_port,
            profile_name=profile_name,
            started_at=time.time(),
            headless=headless,
            chrome_profile_path=chrome_profile_path,
        )
        save_daemon_info(info)
        return info

    browser = _find_browser_binary()
    if not browser:
        supported = ", ".join(get_supported_browsers())
        raise TokenFactoryError(
            f"No Chromium browser found. Install one of: {supported}\n"
            "Or set GEMCLI_BROWSER=<name> (e.g. brave, edge, chromium)."
        )
    chrome_path = browser.path
    logger.info(f"Using browser: {browser.name} ({browser.path})")

    # Find available port — dynamic selection, no global blocking
    if port is not None:
        # Verify the specified port is available
        import socket
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(("127.0.0.1", port))
        except OSError:
            raise TokenFactoryError(f"Port {port} is already in use.")
    else:
        port = find_available_port()

    # Ensure chrome profile directory exists
    profile_dir = Path(chrome_profile_path)
    profile_dir.mkdir(parents=True, exist_ok=True)

    args = _chrome_base_args(chrome_path, port, profile_dir)
    args += [f"--user-agent={CHROME_USER_AGENT}", "--disable-blink-features=AutomationControlled"]
    if headless:
        args.append("--headless")
    args.append(GEMINI_APP_URL)

    # Launch Chrome detached from terminal
    try:
        process = subprocess.Popen(
            args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        )
    except Exception as e:
        raise TokenFactoryError(f"Failed to launch Chrome: {e}")

    # Wait for Chrome to start responding
    timeout = _start_timeout()
    logger.debug(
        f"Chrome launched (PID {process.pid}), waiting up to {timeout:.0f}s "
        f"for CDP on port {port}"
    )
    started = time.monotonic()
    responsive = False
    exit_code = None
    while time.monotonic() - started < timeout:
        time.sleep(0.5)
        if is_chrome_responsive(port):
            responsive = True
            break
        exit_code = process.poll()
        if exit_code is not None:
            break  # Chrome quit (e.g. handed off to a Chrome already on this profile)

    if not responsive:
        owner = _singleton_lock_owner(profile_dir)
        if exit_code is None:
            _kill_process_group(process)
            detail = f"did not answer on port {port} within {timeout:.0f}s"
        else:
            detail = f"exited with code {exit_code} before answering on port {port}"
        hint = f" The profile is locked by another Chrome ({owner})." if owner else ""
        raise TokenFactoryError(
            f"Chrome (PID {process.pid}, profile '{profile_name}') {detail}.{hint}"
        )
    logger.debug(f"Chrome answered CDP after {time.monotonic() - started:.1f}s")

    # Save daemon info and register in port map
    info = ChromeDaemonInfo(
        pid=process.pid,
        port=port,
        profile_name=profile_name,
        started_at=time.time(),
        headless=headless,
        chrome_profile_path=chrome_profile_path,
    )
    save_daemon_info(info)
    _write_port_map(port, profile_name, process.pid)

    logger.info(f"Chrome daemon started: PID {info.pid}, port {info.port}")
    return info


def stop_chrome_daemon() -> bool:
    """Stop the persistent Chrome daemon.

    Only kills the exact PID from our daemon file. Never scans for
    random Chrome processes.

    Returns:
        True if a daemon was stopped, False if none was running.
    """
    info = load_daemon_info()
    if info is None:
        return False

    pid = info.pid
    profile_dir = Path(info.chrome_profile_path) if info.chrome_profile_path else (
        get_chrome_profile_dir(info.profile_name)
    )

    if pid <= 0:
        logger.debug(
            f"Chrome daemon has no tracked PID; cleaning port {info.port} "
            f"for profile '{info.profile_name}'"
        )
        cleanup_zombie_chrome(info.port, profile_dir=profile_dir)
        clear_daemon_info()
        _clear_port_map(info.port)
        _clean_lock_files(profile_dir)
        return True

    if not is_process_alive(pid):
        logger.debug(f"Chrome daemon PID {pid} already dead, cleaning up")
        clear_daemon_info()
        _clear_port_map(info.port)
        _clean_lock_files(profile_dir)
        return True

    # Graceful shutdown
    logger.debug(f"Sending SIGTERM to Chrome daemon PID {pid}")
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError as e:
        logger.debug(f"SIGTERM failed: {e}")
        clear_daemon_info()
        _clear_port_map(info.port)
        _clean_lock_files(profile_dir)
        return False

    # Wait for process to exit
    for _ in range(10):  # up to 5 seconds
        time.sleep(0.5)
        if not is_process_alive(pid):
            clear_daemon_info()
            _clear_port_map(info.port)
            _clean_lock_files(profile_dir)
            logger.info(f"Chrome daemon PID {pid} stopped gracefully")
            return True

    # Force kill
    logger.debug(f"Chrome daemon PID {pid} did not exit, sending SIGKILL")
    try:
        os.kill(pid, signal.SIGKILL)
        time.sleep(0.5)
    except OSError:
        pass

    clear_daemon_info()
    _clear_port_map(info.port)
    _clean_lock_files(profile_dir)
    logger.info(f"Chrome daemon PID {pid} force-killed")
    return True


# =============================================================================
# LaunchAgent for GUI session Chrome (Bug 1 fix)
# =============================================================================
# On macOS, Chrome requires WindowServer/CoreGraphics access, which is only
# available in an interactive user session (Aqua).  Background daemons (e.g.,
# AI agent slots via launchd) lack this.  A LaunchAgent auto-starts Chrome
# at login in the correct GUI session context.

LAUNCH_AGENT_LABEL = "com.gemcli.chrome"
LAUNCH_AGENT_PLIST_NAME = f"{LAUNCH_AGENT_LABEL}.plist"


def _get_launch_agents_dir() -> Path:
    """Get ~/Library/LaunchAgents/."""
    return Path.home() / "Library" / "LaunchAgents"


def _get_plist_path() -> Path:
    """Get full path to our LaunchAgent plist."""
    return _get_launch_agents_dir() / LAUNCH_AGENT_PLIST_NAME


def _find_gemcli_path() -> str:
    """Find the gemcli binary path, checking common locations."""
    import shutil

    # Check PATH first
    path = shutil.which("gemcli")
    if path:
        return path

    # Check common uv/pip install locations
    candidates = [
        Path.home() / ".local" / "bin" / "gemcli",
        Path.home() / ".cargo" / "bin" / "gemcli",  # uv-installed
        Path("/usr/local/bin/gemcli"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)

    return "gemcli"  # Fallback — user will need to fix PATH in plist


def install_launch_agent(
    profile_name: str,
    chrome_profile_path: str,
    headless: bool = True,
    port: int | None = None,
) -> Path:
    """Install a macOS LaunchAgent that starts the Chrome daemon at login.

    The LaunchAgent runs in the Aqua session (GUI) so Chrome has access to
    WindowServer and CoreGraphics — required on macOS.  This solves the
    issue where `gemcli chrome start` fails from background processes
    (e.g., AI agent slots) that lack a GUI session.

    Note: if upgrading from a version with ThrottleInterval=30, the new
    300-second throttle only takes effect after this function is re-run
    (the existing plist is overwritten).

    Args:
        profile_name: Auth profile name.
        chrome_profile_path: Chrome user-data-dir path.
        headless: If True, run Chrome headless (default).
        port: Optional specific CDP port.

    Returns:
        Path to the installed plist file.

    Raises:
        TokenFactoryError: If not on macOS or plist can't be written.
    """
    import platform

    if platform.system() != "Darwin":
        raise TokenFactoryError(
            "LaunchAgent is macOS-only. On Linux, use systemd --user instead."
        )

    gemcli_path = _find_gemcli_path()
    launch_agents_dir = _get_launch_agents_dir()
    launch_agents_dir.mkdir(parents=True, exist_ok=True)

    # Build the gemcli chrome start command args
    program_args = [gemcli_path, "chrome", "start"]
    if not headless:
        program_args.append("--visible")
    if port:
        program_args.extend(["-p", str(port)])
    if profile_name and profile_name != "default":
        program_args = [gemcli_path, "--profile", profile_name, "chrome", "start"]
        if not headless:
            program_args.append("--visible")
        if port:
            program_args.extend(["-p", str(port)])

    # Build the plist XML
    args_xml = "\n".join(f"        <string>{arg}</string>" for arg in program_args)

    # Include user's PATH plus common bin dirs so gemcli is found
    user_path = os.environ.get("PATH", "/usr/bin:/bin:/usr/sbin:/sbin")
    extra_paths = [
        str(Path.home() / ".local" / "bin"),
        str(Path.home() / ".cargo" / "bin"),
        "/usr/local/bin",
        "/opt/homebrew/bin",
    ]
    full_path = ":".join(extra_paths + [user_path])

    log_dir = Path.home() / CONFIG_DIR_NAME / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    plist_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{LAUNCH_AGENT_LABEL}</string>

    <key>ProgramArguments</key>
    <array>
{args_xml}
    </array>

    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>{full_path}</string>
    </dict>

    <key>RunAtLoad</key>
    <true/>

    <key>KeepAlive</key>
    <dict>
        <key>SuccessfulExit</key>
        <false/>
    </dict>

    <key>LimitLoadToSessionType</key>
    <string>Aqua</string>

    <key>StandardOutPath</key>
    <string>{log_dir}/chrome-agent.log</string>
    <key>StandardErrorPath</key>
    <string>{log_dir}/chrome-agent.err</string>

    <key>ThrottleInterval</key>
    <integer>300</integer>
</dict>
</plist>
"""

    plist_path = _get_plist_path()
    plist_path.write_text(plist_content, encoding="utf-8")
    logger.info(f"LaunchAgent plist written to {plist_path}")

    return plist_path


def load_launch_agent(plist_path: Path | None = None) -> bool:
    """Load (activate) a LaunchAgent via launchctl (default: the Chrome agent).

    Returns:
        True if load succeeded, False otherwise.
    """
    plist_path = plist_path or _get_plist_path()
    if not plist_path.exists():
        return False

    # Try modern `launchctl bootstrap` first (macOS 10.10+),
    # fall back to legacy `launchctl load`
    try:
        uid = os.getuid()
        result = subprocess.run(
            ["launchctl", "bootstrap", f"gui/{uid}", str(plist_path)],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            logger.info("LaunchAgent loaded via launchctl bootstrap")
            return True
        # Error 37 = "already loaded" — that's fine
        if "37" in result.stderr or "already loaded" in result.stderr.lower():
            logger.info("LaunchAgent already loaded")
            return True
        logger.debug(f"launchctl bootstrap failed: {result.stderr}")
    except Exception as e:
        logger.debug(f"launchctl bootstrap error: {e}")

    # Fallback to legacy load
    try:
        result = subprocess.run(
            ["launchctl", "load", str(plist_path)],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            logger.info("LaunchAgent loaded via launchctl load")
            return True
        logger.debug(f"launchctl load failed: {result.stderr}")
    except Exception as e:
        logger.debug(f"launchctl load error: {e}")

    return False


def unload_launch_agent(
    label: str = LAUNCH_AGENT_LABEL, plist_path: Path | None = None
) -> bool:
    """Unload (deactivate) a LaunchAgent via launchctl (default: the Chrome agent).

    Returns:
        True if unload succeeded or agent wasn't loaded, False on error.
    """
    plist_path = plist_path or _get_plist_path()

    # Try modern `launchctl bootout` first
    try:
        uid = os.getuid()
        result = subprocess.run(
            ["launchctl", "bootout", f"gui/{uid}/{label}"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            logger.info("LaunchAgent unloaded via launchctl bootout")
            return True
        # Error 3 = "couldn't find service" — already unloaded
        if "3:" in result.stderr or "could not find" in result.stderr.lower():
            return True
        logger.debug(f"launchctl bootout failed: {result.stderr}")
    except Exception as e:
        logger.debug(f"launchctl bootout error: {e}")

    # Fallback to legacy unload
    if plist_path.exists():
        try:
            result = subprocess.run(
                ["launchctl", "unload", str(plist_path)],
                capture_output=True, text=True, timeout=10,
            )
            return result.returncode == 0
        except Exception:
            pass

    return True  # Not loaded, that's fine


def uninstall_launch_agent() -> bool:
    """Unload and remove the LaunchAgent plist.

    Returns:
        True if successfully uninstalled, False otherwise.
    """
    unload_launch_agent()

    plist_path = _get_plist_path()
    if plist_path.exists():
        plist_path.unlink()
        logger.info(f"LaunchAgent plist removed: {plist_path}")
        return True

    return False  # Nothing to remove
