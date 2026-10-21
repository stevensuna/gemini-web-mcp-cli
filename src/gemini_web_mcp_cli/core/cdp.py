"""Chrome DevTools Protocol (CDP) utilities for cookie extraction and browser-driven chat.

Two capabilities:
1. Cookie extraction: Launch Chrome, navigate to Gemini, extract auth cookies.
2. Browser-driven chat: Use headless Chrome to send prompts with model switching.
   The browser handles BotGuard tokens automatically, enabling Pro/Thinking models.
"""

from __future__ import annotations

import json
import os
import platform
import re
import shutil
import signal
import socket
import subprocess
import time
from pathlib import Path
from typing import Any, NamedTuple

import httpx
from loguru import logger

from .constants import COOKIE_1PSID, EMAIL_PATTERN, TOKEN_PATTERNS
from .exceptions import AuthError, GeminiError
from .json_io import read_json_dict, write_json_file

GEMINI_URL = "https://gemini.google.com/app"
CDP_DEFAULT_PORT = 9222
CDP_PORT_RANGE = range(9222, 9232)


# =============================================================================
# Port-to-Profile Mapping
# =============================================================================
# Tracks which CDP port belongs to which gemcli profile so we never reuse
# a Chrome instance from a different profile (or from other tools like
# Antigravity browser). Adapted from notebooklm-mcp-cli's approach.


def _get_port_map_file() -> Path:
    """Get path to chrome-port-map.json."""
    from .constants import CONFIG_DIR_NAME

    return Path.home() / CONFIG_DIR_NAME / "chrome-port-map.json"


def _read_port_map() -> dict[str, dict]:
    """Read the port map, pruning entries whose PIDs are no longer alive.

    Returns:
        Dict mapping port (as string key) to {"profile": str, "pid": int}.
    """
    data = read_json_dict(_get_port_map_file())
    if not data:
        return {}

    alive: dict[str, dict] = {}
    changed = False
    for port_str, entry in data.items():
        pid = entry.get("pid")
        if pid is not None:
            try:
                os.kill(pid, 0)
                alive[port_str] = entry
            except OSError:
                changed = True
        else:
            alive[port_str] = entry

    if changed:
        _save_port_map(alive)

    return alive


def _save_port_map(data: dict[str, dict]) -> None:
    """Write port map to disk."""
    try:
        write_json_file(_get_port_map_file(), data, compact=True)
    except OSError as e:
        logger.debug(f"Failed to save port map: {e}")


def _write_port_map(port: int, profile_name: str, pid: int) -> None:
    """Record which profile owns which port."""
    data = _read_port_map()
    data[str(port)] = {"profile": profile_name, "pid": pid}
    _save_port_map(data)


def _clear_port_map(port: int) -> None:
    """Remove a port entry after Chrome terminates."""
    data = _read_port_map()
    if str(port) in data:
        del data[str(port)]
        _save_port_map(data)


# =============================================================================
# Chrome Health Validation
# =============================================================================
# A Chrome instance can be "alive" (PID exists, /json/version responds) but
# "unhealthy" (zero functional pages).  This happens when Chrome crashes
# internally or all tabs are closed — the CDP debugger keeps listening but
# there's nothing useful to interact with.  These zombies must be rejected
# at the discovery gate to prevent downstream failures.


_LOCK_FILES = ("SingletonLock", "SingletonSocket", "SingletonCookie")


def _clean_lock_files(profile_dir: Path) -> None:
    """Remove all Chrome lock files from a profile directory."""
    for name in _LOCK_FILES:
        try:
            (profile_dir / name).unlink(missing_ok=True)
        except OSError:
            pass


def is_chrome_healthy(port: int) -> bool:
    """Check if Chrome on the given port has at least one functional page.

    A Chrome that responds to /json/version but has zero pages in /json
    is a zombie — it will fail any attempt to interact with it.

    Args:
        port: CDP debugging port.

    Returns:
        True if at least one page exists, False otherwise.
    """
    try:
        # Generous timeout: a busy Chrome answers slowly, and callers treat
        # False as "zombie" and kill it.
        resp = httpx.get(f"http://127.0.0.1:{port}/json", timeout=10)
        if resp.status_code != 200:
            return False
        pages = resp.json()
        return isinstance(pages, list) and len(pages) > 0
    except Exception:
        return False


def cleanup_zombie_chrome(
    port: int,
    pid: int | None = None,
    profile_dir: Path | None = None,
) -> bool:
    """Kill a zombie Chrome process and clean up its artifacts.

    A zombie is a Chrome that responds to CDP (/json/version) but has
    zero functional pages.  This function:
    1. Sends SIGTERM, waits for graceful exit (up to 3s)
    2. Falls back to SIGKILL if the process survives
    3. Cleans up SingletonLock, SingletonSocket, SingletonCookie
    4. Removes the port map entry

    Args:
        port: The CDP port the zombie is listening on.
        pid: The PID to kill. If None, tries to find it from the port map.
        profile_dir: Chrome profile directory for lock file cleanup.

    Returns:
        True if a zombie was cleaned up, False if nothing to clean.
    """
    # Resolve PID from port map if not provided
    if pid is None:
        port_map = _read_port_map()
        entry = port_map.get(str(port))
        if entry:
            pid = entry.get("pid")

    cleaned = False

    if pid is not None:
        try:
            os.kill(pid, signal.SIGTERM)
            logger.debug(f"Zombie cleanup: sent SIGTERM to PID {pid} on port {port}")
            # Wait for graceful exit
            for _ in range(6):
                time.sleep(0.5)
                try:
                    os.kill(pid, 0)  # probe
                except OSError:
                    break  # process is dead
            else:
                # Still alive — force kill
                try:
                    os.kill(pid, signal.SIGKILL)
                    logger.debug(f"Zombie cleanup: force-killed PID {pid}")
                    time.sleep(0.5)
                except OSError:
                    pass
            cleaned = True
        except OSError:
            pass  # PID already dead

    # Clean port map entry
    _clear_port_map(port)

    # Clean lock files
    if profile_dir:
        _clean_lock_files(profile_dir)

    if cleaned:
        logger.info(
            f"Zombie cleanup: killed Chrome PID {pid} on port {port}"
        )

    return cleaned


def _user_data_dir_pgrep_pattern(profile_dir: Path) -> str:
    """Build a ``pgrep -f`` regex matching exactly this ``--user-data-dir``.

    pgrep matches substrings, so a bare ``--user-data-dir=.../mail4jbd`` would
    also match (and kill) ``.../mail4jbd2`` or ``.../mail4jbd_tf``. Escape the
    path and require a space or end-of-line after it.
    """
    escaped = re.sub(r"([.^$*+?()\[\]{}|\\])", r"\\\1", str(profile_dir))
    return f"--user-data-dir={escaped}( |$)"


def cleanup_orphaned_profile_chrome(profile_dir: Path) -> bool:
    """Kill Chrome processes that still hold a GemCLI profile without CDP reuse.

    If the port map is lost or cleared while Chrome is still alive, a later
    launch against the same ``--user-data-dir`` makes Chrome show a broken
    profile dialog.  This is intentionally scoped to the exact GemCLI profile
    directory, not generic Chrome processes.
    """
    if platform.system() == "Windows":
        return False

    pattern = _user_data_dir_pgrep_pattern(profile_dir)
    try:
        result = subprocess.run(
            ["pgrep", "-f", "--", pattern],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
    except Exception as e:
        logger.debug(f"Orphan cleanup: pgrep failed for {profile_dir}: {e}")
        return False

    pids: list[int] = []
    for line in result.stdout.splitlines():
        try:
            pid = int(line.strip())
        except ValueError:
            continue
        if pid != os.getpid():
            pids.append(pid)

    if not pids:
        return False

    cleaned = False
    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM)
            logger.debug(f"Orphan cleanup: sent SIGTERM to Chrome PID {pid}")
            cleaned = True
        except OSError:
            continue

    deadline = time.time() + 3
    while time.time() < deadline:
        alive = []
        for pid in pids:
            try:
                os.kill(pid, 0)
                alive.append(pid)
            except OSError:
                pass
        if not alive:
            break
        time.sleep(0.25)

    for pid in pids:
        try:
            os.kill(pid, 0)
        except OSError:
            continue
        try:
            os.kill(pid, signal.SIGKILL)
            logger.debug(f"Orphan cleanup: force-killed Chrome PID {pid}")
        except OSError:
            pass

    _clean_lock_files(profile_dir)
    if cleaned:
        logger.info(f"Orphan cleanup: released Chrome profile {profile_dir}")
    return cleaned


def find_existing_gemcli_chrome(
    port_range: range = CDP_PORT_RANGE, profile_name: str = "default"
) -> tuple[int | None, str | None]:
    """Find an existing gemcli Chrome instance for a specific profile.

    Uses the port-to-profile mapping to only reconnect to Chrome instances
    that belong to the requested profile, preventing cross-profile
    contamination (e.g., won't accidentally reuse Antigravity's browser).

    Health validation: after finding a responsive instance, verifies it
    has at least one functional page.  Zombies (responsive but no pages)
    are automatically killed and cleaned up.

    Args:
        port_range: Range of ports to scan.
        profile_name: Only reuse Chrome instances launched for this profile.

    Returns:
        (port, debugger_url) if found, (None, None) otherwise.
    """
    port_map = _read_port_map()

    # Check mapped ports for the target profile (fast path)
    for port_str, entry in port_map.items():
        if entry.get("profile") != profile_name:
            continue
        port = int(port_str)
        try:
            resp = httpx.get(f"http://127.0.0.1:{port}/json/version", timeout=10)
            if resp.status_code != 200:
                raise RuntimeError(f"CDP status {resp.status_code}")

            # Health check: verify the Chrome has functional pages
            if not is_chrome_healthy(port):
                logger.warning(
                    f"Chrome on port {port} for profile '{profile_name}' "
                    f"is a zombie (no pages) — cleaning up"
                )
                # Resolve profile dir for lock cleanup
                profile_dir = get_chrome_profile_dir(profile_name)
                cleanup_zombie_chrome(
                    port, pid=entry.get("pid"), profile_dir=profile_dir
                )
                continue

            debugger_url = resp.json().get("webSocketDebuggerUrl")
            logger.debug(
                f"Reusing mapped Chrome on port {port} "
                f"for profile '{profile_name}'"
            )
            return port, debugger_url
        except httpx.TimeoutException:
            # Slow, not dead (e.g. mid-generation under load). Killing it here
            # would break whoever is using it; skip it this time.
            logger.warning(
                f"Chrome on port {port} for profile '{profile_name}' is slow "
                f"to answer — not reusing it this time"
            )
            continue
        except Exception:
            logger.warning(
                f"Chrome on port {port} for profile '{profile_name}' "
                f"is not responding — cleaning up"
            )
            profile_dir = get_chrome_profile_dir(profile_name)
            cleanup_zombie_chrome(
                port, pid=entry.get("pid"), profile_dir=profile_dir
            )
            continue

    # No mapped instance found for this profile
    return None, None


# ── Multi-browser detection ──────────────────────────────────────────────────


class BrowserResult(NamedTuple):
    name: str
    path: str


_BROWSER_CONFIG_MAP: dict[str, list[str]] = {
    "chrome": ["Google Chrome"],
    "arc": ["Arc"],
    "brave": ["Brave Browser"],
    "edge": ["Microsoft Edge"],
    "chromium": ["Chromium"],
    "vivaldi": ["Vivaldi"],
    "opera": ["Opera", "Opera GX"],
    "comet": ["Comet"],
}

SUPPORTED_BROWSER_KEYS = list(_BROWSER_CONFIG_MAP.keys())

_detected_browser: BrowserResult | None = None
_detected_preference: str | None = None


def _macos_browser_candidates() -> list[tuple[str, str]]:
    """macOS: absolute .app bundle paths under /Applications and ~/Applications."""
    home_apps = Path.home() / "Applications"
    entries: list[tuple[str, str]] = [
        ("Google Chrome", "Google Chrome.app/Contents/MacOS/Google Chrome"),
        ("Google Chrome Canary", "Google Chrome Canary.app/Contents/MacOS/Google Chrome Canary"),
        ("Arc", "Arc.app/Contents/MacOS/Arc"),
        ("Brave Browser", "Brave Browser.app/Contents/MacOS/Brave Browser"),
        ("Microsoft Edge", "Microsoft Edge.app/Contents/MacOS/Microsoft Edge"),
        ("Chromium", "Chromium.app/Contents/MacOS/Chromium"),
        ("Vivaldi", "Vivaldi.app/Contents/MacOS/Vivaldi"),
        ("Opera", "Opera.app/Contents/MacOS/Opera"),
        ("Opera GX", "Opera GX.app/Contents/MacOS/Opera GX"),
        ("Comet", "Comet.app/Contents/MacOS/Comet"),
    ]
    candidates: list[tuple[str, str]] = []
    for name, rel in entries:
        candidates.append((name, str(Path("/Applications") / rel)))
        candidates.append((name, str(home_apps / rel)))
    return candidates


_LINUX_BROWSER_CANDIDATES: list[tuple[str, str]] = [
    ("Google Chrome", "google-chrome"),
    ("Google Chrome", "google-chrome-stable"),
    ("Chromium", "chromium"),
    ("Chromium", "chromium-browser"),
    ("Brave Browser", "brave-browser"),
    ("Microsoft Edge", "microsoft-edge-stable"),
    ("Microsoft Edge", "microsoft-edge"),
    ("Vivaldi", "vivaldi-stable"),
    ("Vivaldi", "vivaldi"),
    ("Opera", "opera"),
    ("Comet", "comet-browser"),
    ("Comet", "comet"),
]


def _windows_browser_candidates() -> list[tuple[str, str]]:
    """Windows: absolute paths for all common Chromium-based browsers."""
    local = Path.home() / "AppData" / "Local"
    roaming = Path.home() / "AppData" / "Roaming"
    pf = Path(r"C:\Program Files")
    pf86 = Path(r"C:\Program Files (x86)")
    return [
        ("Google Chrome", str(pf / r"Google\Chrome\Application\chrome.exe")),
        ("Google Chrome", str(pf86 / r"Google\Chrome\Application\chrome.exe")),
        ("Google Chrome", str(local / r"Google\Chrome\Application\chrome.exe")),
        ("Microsoft Edge", str(pf86 / r"Microsoft\Edge\Application\msedge.exe")),
        ("Microsoft Edge", str(pf / r"Microsoft\Edge\Application\msedge.exe")),
        ("Microsoft Edge", str(local / r"Microsoft\Edge\Application\msedge.exe")),
        ("Brave Browser", str(pf / r"BraveSoftware\Brave-Browser\Application\brave.exe")),
        ("Brave Browser", str(local / r"BraveSoftware\Brave-Browser\Application\brave.exe")),
        ("Vivaldi", str(local / r"Vivaldi\Application\vivaldi.exe")),
        ("Opera", str(roaming / r"Opera Software\Opera Stable\launcher.exe")),
        ("Opera GX", str(roaming / r"Opera Software\Opera GX Stable\launcher.exe")),
        ("Comet", str(local / r"CometBrowser\Application\comet.exe")),
        ("Comet", str(pf / r"CometBrowser\Application\comet.exe")),
    ]


def _resolve_candidate(path_or_exe: str) -> bool:
    """Check if a candidate browser exists (absolute path) or is on PATH."""
    p = Path(path_or_exe)
    if p.is_absolute():
        return p.exists()
    return bool(shutil.which(path_or_exe))


def _is_browser_path(value: str) -> bool:
    """True if a browser preference is a binary path rather than a name."""
    return "/" in value or "\\" in value or value.startswith("~")


def _get_preferred_browser() -> str:
    """Read browser preference from GEMCLI_BROWSER env > config.json > 'auto'.

    The value is a browser name (see SUPPORTED_BROWSER_KEYS) or a path to a
    Chromium binary, e.g. a dedicated Chrome for Testing install (issue #7).
    Paths keep their case.
    """
    value = os.environ.get("GEMCLI_BROWSER")
    if not value:
        from .constants import CONFIG_DIR_NAME, CONFIG_FILE

        config_path = Path.home() / CONFIG_DIR_NAME / CONFIG_FILE
        value = str(read_json_dict(config_path).get("browser", "auto"))
    value = value.strip()
    return value if _is_browser_path(value) else value.lower()


def _search_candidates(
    candidates: list[tuple[str, str]], preferred_names: list[str]
) -> BrowserResult | None:
    """Walk candidates, trying preferred display names first, then the full list."""
    if preferred_names:
        for name, path in candidates:
            if name in preferred_names and _resolve_candidate(path):
                return BrowserResult(name, path)

    for name, path in candidates:
        if _resolve_candidate(path):
            return BrowserResult(name, path)
    return None


def _find_browser_binary() -> BrowserResult | None:
    """Locate a Chromium-based browser binary.

    Caches the result for the lifetime of the process (keyed by preference).
    Respects GEMCLI_BROWSER env var and config.json 'browser' key.
    Valid values: auto, chrome, arc, brave, edge, chromium, vivaldi, opera, comet.
    """
    global _detected_browser, _detected_preference

    preferred = _get_preferred_browser()
    if _is_browser_path(preferred):
        path = Path(preferred).expanduser()
        if path.is_file() and os.access(path, os.X_OK):
            result = BrowserResult(path.name, str(path))
            _detected_browser, _detected_preference = result, preferred
            return result
        logger.warning(f"Browser path '{preferred}' is not an executable file, using auto")
        preferred = "auto"
    if preferred not in {"auto", *_BROWSER_CONFIG_MAP}:
        logger.warning(f"Unknown GEMCLI_BROWSER value '{preferred}', using auto")
        preferred = "auto"

    if _detected_browser and _detected_preference == preferred:
        return _detected_browser

    preferred_names = _BROWSER_CONFIG_MAP.get(preferred, [])
    system = platform.system()

    if system == "Darwin":
        candidates = _macos_browser_candidates()
    elif system == "Linux":
        candidates = _LINUX_BROWSER_CANDIDATES
    elif system == "Windows":
        candidates = _windows_browser_candidates()
    else:
        return None

    result = _search_candidates(candidates, preferred_names)
    _detected_preference = preferred
    if result:
        _detected_browser = result
        logger.debug(f"Browser detected: {result.name} at {result.path}")
    else:
        _detected_browser = None
    return result


def get_chrome_path() -> str | None:
    """Get a Chromium-based browser path for the current platform.

    Supports Chrome, Brave, Edge, Arc, Chromium, Vivaldi, Opera, Comet.
    Set preference via GEMCLI_BROWSER env var or config.json 'browser' key.
    """
    result = _find_browser_binary()
    return result.path if result else None


def get_browser_display_name() -> str:
    """Return the display name of the detected browser, or 'Chrome' as default."""
    result = _find_browser_binary()
    return result.name if result else "Chrome"


def get_supported_browsers() -> list[str]:
    """Return deduplicated, ordered list of browser display names for the platform."""
    system = platform.system()
    if system == "Darwin":
        pairs = _macos_browser_candidates()
    elif system == "Linux":
        pairs = _LINUX_BROWSER_CANDIDATES
    elif system == "Windows":
        pairs = _windows_browser_candidates()
    else:
        return []
    seen: set[str] = set()
    names: list[str] = []
    for name, _ in pairs:
        if name not in seen:
            seen.add(name)
            names.append(name)
    return names


def get_chrome_profile_dir(profile_name: str = "default") -> Path:
    """Get the Chrome user-data-dir for a profile."""
    from .constants import CONFIG_DIR_NAME
    return Path.home() / CONFIG_DIR_NAME / "chrome-profiles" / profile_name


def _is_ssh_session() -> bool:
    """Return True when running in SSH — macOS denies WindowServer access to SSH processes."""
    return bool(os.environ.get("SSH_CONNECTION") or os.environ.get("SSH_TTY"))


def find_available_port(start: int = 9222, attempts: int = 10) -> int:
    """Find an available port for Chrome debugging."""
    for offset in range(attempts):
        port = start + offset
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(("127.0.0.1", port))
                return port
        except OSError:
            continue
    raise RuntimeError(f"No available ports in range {start}-{start + attempts - 1}")


def find_existing_chrome(port_range: range = CDP_PORT_RANGE) -> int | None:
    """Find an existing Chrome instance with debugging enabled.

    .. deprecated::
        Prefer ``find_existing_gemcli_chrome()`` which is profile-aware
        and includes health validation.  This function is retained for
        backward compatibility but now includes zombie detection.
    """
    for port in port_range:
        try:
            resp = httpx.get(f"http://127.0.0.1:{port}/json/version", timeout=2)
            if resp.status_code == 200:
                # Health check: reject zombies (responsive but no pages)
                if not is_chrome_healthy(port):
                    logger.debug(
                        f"find_existing_chrome: port {port} is a zombie "
                        f"(responsive but no pages), skipping"
                    )
                    continue
                return port
        except Exception:
            continue
    return None


def get_debugger_url(port: int) -> str | None:
    """Get the WebSocket debugger URL from Chrome."""
    try:
        resp = httpx.get(f"http://127.0.0.1:{port}/json/version", timeout=5)
        return resp.json().get("webSocketDebuggerUrl")
    except Exception:
        return None


def get_pages(port: int) -> list[dict]:
    """Get list of open pages in Chrome."""
    try:
        resp = httpx.get(f"http://127.0.0.1:{port}/json", timeout=5)
        return resp.json()
    except Exception:
        return []


class StaleTargetError(GeminiError):
    """Raised when a CDP WebSocket target ID is stale (Chrome restarted)."""
    pass


def _create_cdp_websocket(ws_url: str, timeout: int = 30):
    """Open a CDP WebSocket with IPv4 normalisation and StaleTargetError detection."""
    try:
        import websocket
    except ImportError:
        raise AuthError("websocket-client not installed. Run: pip install websocket-client")

    # macOS may resolve `localhost` to ::1 (IPv6) but Chrome only listens on
    # 127.0.0.1 (IPv4), causing ConnectionRefusedError.  Normalise to IPv4.
    ws_url = ws_url.replace("ws://localhost:", "ws://127.0.0.1:")

    try:
        try:
            return websocket.create_connection(ws_url, timeout=timeout, suppress_origin=True)
        except TypeError:
            return websocket.create_connection(ws_url, timeout=timeout)
    except Exception as e:
        err_str = str(e).lower()
        if "no such target" in err_str or "500" in err_str:
            raise StaleTargetError(
                f"Stale CDP target ID — Chrome was likely restarted. "
                f"Run 'gemcli login' to refresh the connection. ({e})"
            )
        raise


def execute_cdp_command(ws_url: str, method: str, params: dict | None = None) -> dict:
    """Execute a CDP command via WebSocket."""
    ws = _create_cdp_websocket(ws_url)
    try:
        command = {"id": 1, "method": method, "params": params or {}}
        ws.send(json.dumps(command))
        while True:
            response = json.loads(ws.recv())
            if response.get("id") == 1:
                return response.get("result", {})
    finally:
        ws.close()


def get_page_cookies(ws_url: str) -> list[dict]:
    """Get all cookies via CDP Network.getAllCookies."""
    result = execute_cdp_command(ws_url, "Network.getAllCookies")
    return result.get("cookies", [])


def get_gemini_page_ws_url(port: int, retries: int = 3, delay: float = 0.5) -> str | None:
    """Find a Gemini page's WebSocket URL from Chrome on the given port.

    Searches open tabs for one on gemini.google.com and returns its
    page-level WebSocket URL. Page-level (not browser-level) is required
    because only page-level WS gives access to the full cookie jar
    including partitioned cookies.

    Retries with backoff to handle transient failures when Chrome is
    mid-navigation (e.g., after Token Factory navigates back to /app).
    """
    for attempt in range(retries):
        pages = get_pages(port)
        for page in pages:
            if "gemini.google.com" in page.get("url", ""):
                ws_url = page.get("webSocketDebuggerUrl")
                if ws_url:
                    return ws_url
        if attempt < retries - 1:
            time.sleep(delay)
    return None


def download_via_page_fetch(ws_url: str, url: str, timeout: int = 120) -> bytes:
    """Download a URL using fetch() from a Chrome page context.

    Bypasses partitioned-cookie issues by leveraging the Gemini page's
    full cookie jar. Required for downloading from
    contribution.usercontent.google.com, where CDP's
    Network.getAllCookies is missing critical cookies (AEC,
    GOOGLE_ABUSE_EXEMPTION) that exist only in Chrome's partitioned
    cookie store.

    Args:
        ws_url: Page-level WebSocket debugger URL.
        url: The URL to download.
        timeout: Max seconds to wait for the download to complete.

    Returns:
        Downloaded file content as bytes.

    Raises:
        GeminiError: If the download fails (HTTP error, timeout, etc.).
        AuthError: If websocket-client is not installed.
    """
    import base64 as b64_module  # noqa: PLC0415

    import websocket  # noqa: PLC0415

    escaped_url = json.dumps(url)
    js_expression = f"""
    (async () => {{
        const resp = await fetch({escaped_url}, {{
            credentials: 'include',
            mode: 'cors',
        }});
        if (!resp.ok) {{
            throw new Error('HTTP ' + resp.status + ': ' + resp.statusText);
        }}
        const blob = await resp.blob();
        const reader = new FileReader();
        const base64 = await new Promise((resolve, reject) => {{
            reader.onload = () => resolve(reader.result);
            reader.onerror = reject;
            reader.readAsDataURL(blob);
        }});
        return {{ success: true, size: blob.size, type: blob.type, data: base64 }};
    }})()
    """

    logger.debug(f"CDP page fetch: {url[:80]}...")

    ws = _create_cdp_websocket(ws_url, timeout=timeout)

    try:
        # Enable Runtime
        ws.send(json.dumps({"id": 1, "method": "Runtime.enable", "params": {}}))
        while True:
            resp = json.loads(ws.recv())
            if resp.get("id") == 1:
                break

        # Execute fetch + base64 conversion in page context
        ws.send(json.dumps({
            "id": 2,
            "method": "Runtime.evaluate",
            "params": {
                "expression": js_expression,
                "awaitPromise": True,
                "returnByValue": True,
            },
        }))

        while True:
            resp = json.loads(ws.recv())
            if resp.get("id") == 2:
                result = resp.get("result", {})

                # Check for JS exceptions
                if "exceptionDetails" in result:
                    exc = result["exceptionDetails"]
                    msg = exc.get("text", "Unknown error")
                    if "exception" in exc:
                        msg = exc["exception"].get("description", msg)
                    raise GeminiError(f"Browser download failed: {msg}")

                value = result.get("result", {}).get("value")
                if not value or not value.get("success"):
                    raise GeminiError("Browser download returned no data")

                file_size = value.get("size", 0)
                file_type = value.get("type", "unknown")
                logger.debug(f"CDP page fetch complete: {file_size} bytes, {file_type}")

                # Extract base64 data from data URL (strip "data:type;base64," prefix)
                data_url = value["data"]
                _, _, b64_data = data_url.partition(",")
                return b64_module.b64decode(b64_data)
    except websocket.WebSocketTimeoutException:
        raise GeminiError(f"Browser download timed out after {timeout}s")
    finally:
        ws.close()


def get_page_html(ws_url: str) -> str:
    """Get page HTML to extract tokens."""
    execute_cdp_command(ws_url, "Runtime.enable")
    result = execute_cdp_command(
        ws_url, "Runtime.evaluate",
        {"expression": "document.documentElement.outerHTML"},
    )
    return result.get("result", {}).get("value", "")


def extract_page_tokens_and_email(ws_url: str, retries: int = 10) -> tuple[dict[str, str], str]:
    """Extract Gemini page tokens from live JS state, then static HTML.

    Gemini does not always leave SNlM0e in the page HTML after a browser login.
    The live WIZ_global_data object is the source the rest of the codebase uses
    for Token Factory and headless auth recovery, so login should prefer it too.
    """
    tokens: dict[str, str] = {}
    email = ""

    for attempt in range(retries):
        try:
            snlm0e = run_js(ws_url, "window.WIZ_global_data?.SNlM0e || ''")
            if snlm0e:
                tokens["snlm0e"] = snlm0e
                break
        except Exception as e:
            logger.debug(f"Login: JS SNlM0e extraction failed: {e}")

        if attempt < retries - 1:
            time.sleep(0.5)

    try:
        html = get_page_html(ws_url)
        for name, pattern in TOKEN_PATTERNS.items():
            if tokens.get(name):
                continue
            match = re.search(pattern, html)
            if match:
                tokens[name] = match.group(1)
        email_match = re.search(EMAIL_PATTERN, html)
        if email_match:
            email = email_match.group(1)
    except Exception as e:
        logger.debug(f"Login: HTML token extraction failed: {e}")

    return tokens, email


def get_current_url(ws_url: str) -> str:
    """Get the current page URL."""
    execute_cdp_command(ws_url, "Runtime.enable")
    result = execute_cdp_command(
        ws_url, "Runtime.evaluate",
        {"expression": "window.location.href"},
    )
    return result.get("result", {}).get("value", "")


def navigate_to_url(ws_url: str, url: str) -> None:
    """Navigate the page to a URL."""
    execute_cdp_command(ws_url, "Page.enable")
    execute_cdp_command(ws_url, "Page.navigate", {"url": url})
    time.sleep(3)


def _navigate_with_stale_recovery(port: int, ws_url: str, url: str) -> str:
    """Navigate to url, recovering from a stale CDP target by re-discovering the page.

    Returns the (possibly refreshed) ws_url for subsequent calls.
    """
    try:
        navigate_to_url(ws_url, url)
        return ws_url
    except StaleTargetError:
        page = find_or_create_gemini_page(port)
        if not page:
            raise AuthError("Failed to re-open Gemini page after stale target.")
        ws_url = page.get("webSocketDebuggerUrl") or ws_url
        if url not in page.get("url", ""):
            navigate_to_url(ws_url, url)
        return ws_url


def is_logged_in(url: str) -> bool:
    """Check if the user is logged into Gemini (not redirected to accounts.google.com)."""
    if "accounts.google.com" in url:
        return False
    if "gemini.google.com" in url:
        return True
    return False


def find_or_create_gemini_page(port: int) -> dict | None:
    """Find an existing Gemini page or create a new one.

    Polls for an existing Gemini tab for up to 3 seconds before creating
    a new one. This handles the race condition where Chrome is mid-navigation
    (e.g., Token Factory just navigated back to /app) and the tab's URL
    is transiently not gemini.google.com.
    """
    from urllib.parse import quote

    # Poll for existing Gemini tab (handles mid-navigation race)
    for _ in range(6):  # up to 3 seconds
        pages = get_pages(port)
        for page in pages:
            if "gemini.google.com" in page.get("url", ""):
                return page
        time.sleep(0.5)

    # No existing Gemini tab found — create a new one
    try:
        encoded = quote(GEMINI_URL, safe="")
        resp = httpx.put(f"http://127.0.0.1:{port}/json/new?{encoded}", timeout=15)
        if resp.status_code == 200 and resp.text.strip():
            return resp.json()

        resp = httpx.put(f"http://127.0.0.1:{port}/json/new", timeout=10)
        if resp.status_code == 200 and resp.text.strip():
            page = resp.json()
            ws_url = page.get("webSocketDebuggerUrl")
            if ws_url:
                navigate_to_url(ws_url, GEMINI_URL)
            return page
    except Exception:
        pass
    return None


def _chrome_base_args(chrome_path: str, port: int, profile_dir: Path | str) -> list[str]:
    """Return the common CDP launch flags shared by all Chrome invocations."""
    return [
        chrome_path,
        f"--remote-debugging-port={port}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-extensions",
        f"--user-data-dir={profile_dir}",
        "--remote-allow-origins=*",
    ]


def launch_chrome(
    port: int,
    profile_name: str = "default",
    headless: bool = False,
) -> subprocess.Popen | None:
    """Launch Chrome with remote debugging enabled."""
    chrome_path = get_chrome_path()
    if not chrome_path:
        return None

    profile_dir = get_chrome_profile_dir(profile_name)
    profile_dir.mkdir(parents=True, exist_ok=True)

    args = _chrome_base_args(chrome_path, port, profile_dir)
    if headless:
        args.append("--headless")

    try:
        # DEVNULL: unread PIPEs fill up and block a long-lived Chrome.
        process = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(3)
        return process
    except Exception:
        return None


def _filter_gemini_cookies(cookies_list: list[dict]) -> dict[str, str]:
    """Filter CDP cookies to only those relevant to gemini.google.com.

    Network.getAllCookies returns cookies from ALL domains (youtube.com,
    accounts.google.com, etc.). Cookies with the same name from different
    domains collide in a flat dict — e.g. NID, SID, HSID exist on multiple
    Google properties. Sending the wrong domain's cookie value to Gemini
    causes token extraction to fail (the page serves a consent/redirect
    page instead of the app page with SNlM0e).
    """
    cookies = {}
    for c in cookies_list:
        domain = c.get("domain", "")
        if "google.com" in domain:
            cookies[c["name"]] = c["value"]
    return cookies


def _has_auth_cookies(cookies: dict[str, str]) -> bool:
    """Check if the required auth cookies are present."""
    return bool(cookies.get(COOKIE_1PSID))


def _wait_for_auth_cookies(
    ws_url: str,
    timeout: int = 300,
    poll_interval: int = 3,
    on_waiting: callable | None = None,
) -> dict[str, str] | None:
    """Poll for auth cookies until they appear or timeout.

    This handles both cases:
    - User is already logged in (cookies appear immediately)
    - User needs to log in (wait for them to complete the login flow)

    Returns cookies dict if found, None if timeout.
    """
    start = time.time()
    notified = False

    while time.time() - start < timeout:
        try:
            cookies_list = get_page_cookies(ws_url)
            cookies = _filter_gemini_cookies(cookies_list)

            if _has_auth_cookies(cookies):
                return cookies
        except Exception:
            pass

        if not notified and on_waiting:
            on_waiting()
            notified = True

        time.sleep(poll_interval)

    return None


def extract_cookies_via_cdp(
    port: int = CDP_DEFAULT_PORT,
    auto_launch: bool = True,
    login_timeout: int = 300,
    profile_name: str = "default",
    chrome_profile_path: str | None = None,
    on_waiting_for_login: callable | None = None,
    force_new_session: bool = False,
) -> dict[str, Any]:
    """Extract cookies and tokens from Chrome via CDP.

    This is the main entry point for automated authentication.

    Flow:
    1. Find or launch Chrome with remote debugging
    2. Navigate to gemini.google.com
    3. Poll for auth cookies (handles both logged-in and needs-login cases)
    4. Once cookies found, extract tokens from page HTML
    5. Only terminate Chrome if WE launched it

    The browser stays open until auth completes -- the user gets time to
    log in if needed. Chrome is only killed if we launched it ourselves
    (not if we connected to an existing instance).

    Args:
        port: Chrome DevTools port
        auto_launch: Launch Chrome if not running
        login_timeout: Max seconds to wait for auth cookies (default 5 min)
        profile_name: Profile name for Chrome user-data-dir
        chrome_profile_path: Override Chrome profile path (e.g., from NLM)
        on_waiting_for_login: Callback when waiting for user to log in
        force_new_session: If True, skip existing Chrome and launch a visible
            Chrome with a fresh profile-specific directory. Used for new profiles
            so the user can sign into a different Google account.
    """
    chrome_process = None
    we_launched_chrome = False
    used_profile_dir = None

    try:
        # Check for existing Chrome with debugging — skip if forcing new session
        debugger_url = None
        if not force_new_session:
            # Use profile-aware discovery to avoid hijacking other tools' Chrome
            existing_port, existing_debugger = find_existing_gemcli_chrome(
                profile_name=profile_name
            )
            if existing_port:
                port = existing_port
                debugger_url = existing_debugger or get_debugger_url(port)
                logger.debug(f"Found existing Chrome on port {port} for profile '{profile_name}'")

        if not debugger_url and auto_launch:
            chrome_path = get_chrome_path()
            if not chrome_path:
                supported = ", ".join(get_supported_browsers())
                raise AuthError(
                    f"No Chromium browser found. Supported: {supported}\n"
                    "Set GEMCLI_BROWSER=<name> or: gemcli config set browser <name>"
                )

            in_ssh = _is_ssh_session()
            if in_ssh and force_new_session:
                raise AuthError(
                    "Running over SSH — cannot open a browser window for a new login.\n"
                    "Options:\n"
                    "  • gemcli login --manual   (paste cookies from Chrome DevTools)\n"
                    "  • Use Screen Sharing / VNC to access this Mac's desktop, then "
                    "run gemcli login there"
                )

            port = find_available_port()

            # For new sessions, always use a fresh profile-specific Chrome dir
            # so we don't inherit cookies from another account.
            if force_new_session:
                profile_dir = get_chrome_profile_dir(profile_name)
            elif chrome_profile_path:
                profile_dir = Path(chrome_profile_path)
            else:
                profile_dir = get_chrome_profile_dir(profile_name)
            profile_dir.mkdir(parents=True, exist_ok=True)
            used_profile_dir = str(profile_dir)

            cleanup_orphaned_profile_chrome(profile_dir)

            logger.debug(f"Launching browser on port {port} with profile: {profile_dir}")

            is_windows = platform.system() == "Windows"

            # On Windows, Chromium browsers ignore --remote-debugging-port if an
            # existing instance of the same browser is running (the new process
            # becomes a child of the existing one). Remove the SingletonLock to
            # allow a separate instance with our custom user-data-dir.
            if is_windows:
                singleton_lock = profile_dir / "SingletonLock"
                if singleton_lock.exists():
                    try:
                        singleton_lock.unlink()
                    except OSError:
                        pass

            args = _chrome_base_args(chrome_path, port, profile_dir)
            if is_windows:
                args.append("--disable-gpu")
            if in_ssh:
                # Keychain blocked from SSH; headless avoids the invisible window.
                args.extend(["--headless", "--password-store=basic"])
            args.append(GEMINI_URL)

            popen_kwargs: dict[str, Any] = {
                "stdout": subprocess.PIPE,
                "stderr": subprocess.PIPE,
            }
            if is_windows:
                popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
            chrome_process = subprocess.Popen(args, **popen_kwargs)
            we_launched_chrome = True

            # Poll for the debugger URL (heavy profiles may take longer to start)
            start_wait = time.time()
            timeout = 25 if is_windows else 15
            while time.time() - start_wait < timeout:
                debugger_url = get_debugger_url(port)
                if debugger_url:
                    break
                time.sleep(0.5)

        if not debugger_url:
            browser_name = get_browser_display_name()
            raise AuthError(
                f"Cannot connect to {browser_name} on port {port}. "
                f"Make sure {browser_name} isn't already running with a different "
                "debug port, or close all instances and retry."
            )

        # Find or create Gemini page
        page = find_or_create_gemini_page(port)
        if not page:
            raise AuthError("Failed to open Gemini page in Chrome.")

        ws_url = page.get("webSocketDebuggerUrl")
        if not ws_url:
            raise AuthError("No WebSocket URL for Gemini page.")

        # Navigate to Gemini if needed
        current = page.get("url", "")
        if "gemini.google.com" not in current:
            ws_url = _navigate_with_stale_recovery(port, ws_url, GEMINI_URL)
            time.sleep(2)

        # Poll for auth cookies -- this is the main wait loop.
        # Handles both "already logged in" and "user needs to log in" cases.
        cookies = _wait_for_auth_cookies(
            ws_url,
            timeout=login_timeout,
            poll_interval=3,
            on_waiting=on_waiting_for_login,
        )

        if not cookies:
            raise AuthError(
                f"Login timeout ({login_timeout}s). "
                "Please log in to your Google account in the Chrome window."
            )

        # Wait a moment for page to fully load after login
        time.sleep(2)

        # Navigate to Gemini app page to extract tokens (may have been on login page)
        try:
            current = get_current_url(ws_url)
            if "gemini.google.com/app" not in current:
                navigate_to_url(ws_url, GEMINI_URL)
                time.sleep(3)
        except Exception:
            pass

        # Extract tokens and email from the live app page.
        tokens, email = extract_page_tokens_and_email(ws_url)

        # ── Stale cookie detection ──────────────────────────────────────
        # If we found cookies but no SNlM0e token, the session is expired.
        # Google keeps __Secure-1PSID in the Chrome profile even after it
        # expires, so _has_auth_cookies returns True for dead sessions.
        # Saved auth.json cookies are never injected into Chrome to "revive"
        # it — mixing session copies gets sessions revoked (issue #3).
        if not tokens.get("snlm0e"):
            logger.debug(
                "Login: cookies found but no SNlM0e token — "
                "falling back to interactive re-login"
            )

            # Delete the stale auth cookies from Chrome so the next
            # cookie poll won't be fooled by them again.
            try:
                execute_cdp_command(ws_url, "Network.enable")
                for cookie_name in [COOKIE_1PSID, "__Secure-1PSIDTS"]:
                    execute_cdp_command(
                        ws_url, "Network.deleteCookies",
                        {"name": cookie_name, "domain": ".google.com"},
                    )
                logger.debug("Login: cleared stale auth cookies from Chrome")
            except Exception as e:
                logger.debug(f"Login: failed to clear stale cookies: {e}")

            # Navigate to Gemini to trigger login redirect
            ws_url = _navigate_with_stale_recovery(port, ws_url, GEMINI_URL)
            time.sleep(2)

            if on_waiting_for_login:
                on_waiting_for_login()

            # Wait for fresh login
            cookies = _wait_for_auth_cookies(
                ws_url,
                timeout=login_timeout,
                poll_interval=3,
                on_waiting=on_waiting_for_login,
            )

            if not cookies:
                raise AuthError(
                    f"Login timeout ({login_timeout}s). "
                    "Please log in to your Google account in the Chrome window."
                )

            time.sleep(2)

            # Navigate to app and re-extract tokens
            try:
                current = get_current_url(ws_url)
                if "gemini.google.com/app" not in current:
                    navigate_to_url(ws_url, GEMINI_URL)
                    time.sleep(3)
            except Exception:
                pass

            tokens, email = extract_page_tokens_and_email(ws_url)

            if not tokens.get("snlm0e"):
                raise AuthError(
                    "Google login completed, but Gemini did not expose a live "
                    "SNlM0e token. Open https://gemini.google.com/app in the "
                    "GemCLI Chrome window and make sure the Gemini app itself "
                    "loads, not just the Google account page."
                )

        return {
            "cookies": cookies,
            "tokens": tokens,
            "email": email,
            "chrome_profile_path": used_profile_dir or chrome_profile_path,
        }

    finally:
        # Only terminate Chrome if WE launched it.
        # If we connected to an existing instance, leave it running.
        if chrome_process and we_launched_chrome:
            logger.debug("Giving Chrome 3 seconds to flush cookies to disk...")
            time.sleep(3)
            try:
                chrome_process.terminate()
                chrome_process.wait(timeout=10)
            except Exception:
                try:
                    chrome_process.kill()
                except Exception:
                    pass
            # Clean up all lock files from the profile we used
            if used_profile_dir:
                _clean_lock_files(Path(used_profile_dir))


# =============================================================================
# Browser-driven chat via CDP (for model switching)
# =============================================================================

def run_js(ws_url: str, expression: str) -> Any:
    """Execute JavaScript in the page using a single WebSocket for enable + evaluate."""
    ws = _create_cdp_websocket(ws_url)
    try:
        ws.send(json.dumps({"id": 1, "method": "Runtime.enable", "params": {}}))
        while True:
            if json.loads(ws.recv()).get("id") == 1:
                break

        ws.send(json.dumps({
            "id": 2,
            "method": "Runtime.evaluate",
            "params": {"expression": expression, "awaitPromise": True, "returnByValue": True},
        }))
        while True:
            resp = json.loads(ws.recv())
            if resp.get("id") == 2:
                return resp.get("result", {}).get("result", {}).get("value")
    finally:
        ws.close()


# Model selectors (from social-browser-agents, confirmed working via CDP test)
MODEL_PICKER_SELECTOR = '[data-test-id="bard-mode-menu-button"]'
MODEL_OPTION_SELECTORS = {
    "fast": '[data-test-id="bard-mode-option-fast"]',
    "thinking": '[data-test-id="bard-mode-option-thinking"]',
    "pro": '[data-test-id="bard-mode-option-pro"]',
}


class BrowserTransport:
    """Browser-driven chat transport using CDP.

    Uses headless Chrome to interact with the Gemini web UI.
    The browser handles BotGuard tokens automatically, enabling
    Pro and Thinking model selection that direct HTTP cannot do.

    Usage:
        transport = BrowserTransport(
            chrome_profile_path="~/.notebooklm-mcp-cli/chrome-profiles/personal"
        )
        transport.start()
        response = transport.send("What is 2+2?", model="pro")
        transport.stop()
    """

    def __init__(self, chrome_profile_path: str | None = None, profile_name: str = "default"):
        self.chrome_profile_path = chrome_profile_path
        self.profile_name = profile_name
        self._process: subprocess.Popen | None = None
        self._port: int | None = None
        self._ws_url: str | None = None
        self._current_model: str | None = None
        self._started = False
        self._we_launched = False
        self._profile_dir: Path | None = None

    def start(self, headless: bool = True) -> None:
        """Start a headless Chrome instance and navigate to Gemini."""
        # Use profile-aware discovery to avoid hijacking other tools' Chrome
        existing_port, _ = find_existing_gemcli_chrome(
            profile_name=self.profile_name
        )
        if existing_port:
            self._port = existing_port
            logger.debug(f"Reusing existing Chrome on port {existing_port}")
        else:
            self._port = find_available_port()
            profile_dir = (
                Path(self.chrome_profile_path)
                if self.chrome_profile_path
                else get_chrome_profile_dir(self.profile_name)
            )
            profile_dir.mkdir(parents=True, exist_ok=True)
            self._profile_dir = profile_dir

            chrome_path = get_chrome_path()
            if not chrome_path:
                raise AuthError(
                    "No Chromium browser found. "
                    "Set GEMCLI_BROWSER=<name> or install Chrome/Brave/Edge."
                )

            args = _chrome_base_args(chrome_path, self._port, profile_dir)
            in_ssh = _is_ssh_session()
            if headless or in_ssh:
                args.append("--headless")
            if in_ssh:
                args.append("--password-store=basic")

            self._process = subprocess.Popen(
                args, stdout=subprocess.PIPE, stderr=subprocess.PIPE
            )
            self._we_launched = True
            time.sleep(4)
            # Register in port map so other components can discover us
            _write_port_map(self._port, self.profile_name, self._process.pid)
            logger.debug(f"Launched Chrome on port {self._port} (headless={headless})")

        # Find or create Gemini page
        page = find_or_create_gemini_page(self._port)
        if not page:
            raise AuthError("Failed to open Gemini page.")

        self._ws_url = page.get("webSocketDebuggerUrl")
        if not self._ws_url:
            raise AuthError("No WebSocket URL for Gemini page.")

        # Wait for page to be ready
        for _ in range(10):
            try:
                url = get_current_url(self._ws_url)
                if "gemini.google.com" in url:
                    break
            except Exception:
                pass
            time.sleep(1)

        # Wait for the input field to appear (page fully loaded)
        for _ in range(15):
            ready = run_js(self._ws_url, """
                !!(document.querySelector('div[contenteditable="true"]')
                   || document.querySelector('textarea'))
            """)
            if ready:
                break
            time.sleep(1)

        self._started = True
        logger.debug("BrowserTransport ready.")

    def stop(self) -> None:
        """Stop the Chrome instance if we started it."""
        if self._process and self._we_launched:
            try:
                self._process.terminate()
                self._process.wait(timeout=5)
            except Exception:
                try:
                    self._process.kill()
                except Exception:
                    pass
            self._process = None
            # Clean up port map and lock files
            if self._port:
                _clear_port_map(self._port)
            if self._profile_dir:
                _clean_lock_files(self._profile_dir)
        self._started = False

    def select_model(self, model: str) -> bool:
        """Select a model in the Gemini UI (fast, thinking, pro)."""
        if not self._ws_url:
            return False

        model_lower = model.lower()
        if model_lower == self._current_model:
            return True  # Already selected

        selector = MODEL_OPTION_SELECTORS.get(model_lower)
        if not selector:
            logger.warning(f"Unknown model for browser transport: {model}")
            return False

        # Click the model picker button
        picker_found = run_js(self._ws_url, f"""
            (() => {{
                const btn = document.querySelector('{MODEL_PICKER_SELECTOR}');
                if (btn) {{ btn.click(); return true; }}
                return false;
            }})()
        """)

        if not picker_found:
            logger.warning("Model picker button not found")
            return False

        # Wait for dropdown to render
        time.sleep(1.0)

        # Click the model option
        option_found = run_js(self._ws_url, f"""
            (() => {{
                const opt = document.querySelector('{selector}');
                if (opt) {{ opt.click(); return true; }}
                return false;
            }})()
        """)

        time.sleep(0.5)

        if option_found:
            self._current_model = model_lower
            logger.debug(f"Model switched to: {model_lower}")
            return True

        logger.warning(f"Model option not found: {selector}")
        return False

    def send(self, prompt: str, model: str | None = None, timeout: int = 120) -> str:
        """Send a prompt via the browser and return the response text.

        Args:
            prompt: The text to send
            model: Model to use (fast, thinking, pro). Switches if different from current.
            timeout: Max seconds to wait for response

        Returns:
            The response text from Gemini.
        """
        if not self._started or not self._ws_url:
            raise AuthError("BrowserTransport not started. Call start() first.")

        # Switch model if needed
        if model:
            self.select_model(model)

        # Clear any existing input and type the prompt
        escaped = prompt.replace("\\", "\\\\").replace("'", "\\'").replace("\n", "\\n")
        run_js(self._ws_url, f"""
            const input = document.querySelector('div[contenteditable="true"]')
                || document.querySelector('textarea');
            if (input) {{
                input.focus();
                input.click();
                // Clear existing text
                document.execCommand('selectAll');
                document.execCommand('delete');
                // Type new prompt
                document.execCommand('insertText', false, '{escaped}');
            }}
        """)
        time.sleep(0.3)

        # Submit by clicking the Send button (more reliable than Enter key)
        run_js(self._ws_url, """
            (() => {
                // Try Send button first
                const sendBtn = document.querySelector('button[aria-label="Send message"]')
                    || document.querySelector('button[data-test-id="send-button"]');
                if (sendBtn) { sendBtn.click(); return; }
                // Fallback: press Enter via the page's keyboard handling
                const input = document.querySelector('div[contenteditable="true"]')
                    || document.querySelector('textarea');
                if (input) {
                    const ev = new KeyboardEvent('keydown', {
                        key: 'Enter', code: 'Enter', keyCode: 13,
                        which: 13, bubbles: true, cancelable: true
                    });
                    input.dispatchEvent(ev);
                }
            })()
        """)

        # Poll for response text stability
        last_text = ""
        stable_count = 0
        start_time = time.time()

        while time.time() - start_time < timeout:
            time.sleep(1)

            current_text = run_js(self._ws_url, """
                (() => {
                    // Find all "Gemini said" headings and get the text after the last one
                    const headings = document.querySelectorAll('h6');
                    let lastResponse = '';
                    for (const h of headings) {
                        if (h.textContent.includes('Gemini said')) {
                            let sibling = h.nextElementSibling;
                            while (sibling) {
                                const text = sibling.innerText || sibling.textContent;
                                if (text && text.trim().length > 0) {
                                    lastResponse = text.trim();
                                    break;
                                }
                                sibling = sibling.nextElementSibling;
                            }
                        }
                    }
                    return lastResponse;
                })()
            """) or ""

            if current_text and current_text == last_text:
                stable_count += 1
                if stable_count >= 3:  # Stable for 3 seconds
                    return current_text
            else:
                last_text = current_text
                stable_count = 0

        # Timeout -- return whatever we have
        return last_text or ""

    def new_chat(self) -> None:
        """Start a new chat (navigate to /app)."""
        if self._ws_url:
            navigate_to_url(self._ws_url, GEMINI_URL)
            time.sleep(2)

    def get_model_button_text(self) -> str:
        """Get the current model from the model picker button."""
        if not self._ws_url:
            return "unknown"
        return run_js(self._ws_url, f"""
            const btn = document.querySelector('{MODEL_PICKER_SELECTOR}');
            btn ? btn.innerText : 'unknown';
        """) or "unknown"
