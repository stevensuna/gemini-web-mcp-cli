"""Session keep-alive for every gemcli profile.

Google web sessions stay alive when the browser that owns them keeps using
them.  They die when the same session is copied into several clients that
rotate cookies independently (see issue #3).  So the keep-alive never copies
or injects cookies.  For each profile it:

1. Opens **that profile's own** Chrome user-data-dir (never a ``_tf`` copy),
   loads Gemini, and lets Chrome renew the session the normal way.
2. Mirrors Chrome's fresh cookies into ``auth.json`` (read-only for Chrome).
3. For the profile held by the Chrome daemon, reads cookies from the daemon
   instead of launching a second Chrome on the same profile.

A profile counts as signed in only when Gemini exposes the account email
(``WIZ_global_data.oPEP7c``).  ``SNlM0e`` alone is not enough: the signed-out
Gemini page carries one too.

Optional recovery (``recover=True``) handles a naturally expired session: it
opens the profile's Chrome in an off-screen window, clicks "Sign in", and
only clicks through Google's account chooser for the matching account.  It
never types anything — a password, passkey, or "verify it's you" page means
a human must sign in, and the run reports that instead.
"""

from __future__ import annotations

import fcntl
import json
import subprocess
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path

import httpx
from loguru import logger

from .auth import AuthManager, AuthTokens, extract_email, extract_tokens
from .cdp import (
    _clean_lock_files,
    _filter_gemini_cookies,
    _user_data_dir_pgrep_pattern,
    execute_cdp_command,
    find_available_port,
    find_or_create_gemini_page,
    get_chrome_path,
    get_debugger_url,
    get_gemini_page_ws_url,
    get_page_cookies,
    get_page_html,
    navigate_to_url,
    run_js,
)
from .constants import (
    CHROME_USER_AGENT,
    CONFIG_DIR_NAME,
    COOKIE_1PSID,
    GEMINI_HEADERS,
    Endpoint,
)
from .locks import ProfileBusy, profile_lock
from .profiles import ProfileManager

ALIVE = "alive"
RECOVERED = "recovered"
DEAD = "dead"
# Saved auth.json copy rejected; the profile's own Chrome may still be signed in.
STALE = "stale"
SKIPPED = "skipped"
ERROR = "error"

GEMINI_APP_URL = "https://gemini.google.com/app"
# Ports for keep-alive Chrome; clear of login (9222+), Token Factory (9300+)
# and CDP recovery (9400+).
_KEEPALIVE_PORT_START = 9500
# How long to wait for Gemini to settle into signed-in / signed-out.
_PAGE_SETTLE_TIMEOUT = 30
# How long the recovery flow may take after clicking "Sign in".
_RECOVERY_TIMEOUT = 60
# Consecutive signed-out polls (1s apart) before we believe it.
_SIGNED_OUT_CONFIRMATIONS = 4

_EMAIL_JS = "window.WIZ_global_data && window.WIZ_global_data.oPEP7c || ''"
_SNLM0E_JS = "window.WIZ_global_data && window.WIZ_global_data.SNlM0e || ''"
_READY_JS = "document.readyState === 'complete' && !!window.WIZ_global_data"


@dataclass
class ProfileHealth:
    """Result of checking or refreshing one profile."""

    profile: str
    status: str
    email: str = ""
    method: str = ""
    detail: str = ""
    duration: float = 0.0
    steps: list[str] = field(default_factory=list)
    # BotGuard token capture, probed separately from "signed in" (issue #5):
    # "ok", "failed: <stage>", "skipped: <why>", or "" when not probed.
    capture: str = ""
    # Chat transport seen by a successful probe: "streamgenerate" or "processSession".
    transport: str = ""

    @property
    def ok(self) -> bool:
        return self.status in (ALIVE, RECOVERED)

    @property
    def capture_failed(self) -> bool:
        return self.capture.startswith("failed")


# ── Paths, logging, locking ─────────────────────────────────────────────────


def _config_dir() -> Path:
    return Path.home() / CONFIG_DIR_NAME


def log_path() -> Path:
    return _config_dir() / "logs" / "keepalive.jsonl"


def _append_log(result: ProfileHealth, run_id: str) -> None:
    path = log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    entry = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "run": run_id, **asdict(result)}
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def read_last_results() -> dict[str, dict]:
    """Return the most recent logged result for each profile."""
    path = log_path()
    if not path.exists():
        return {}
    latest: dict[str, dict] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        latest[entry.get("profile", "")] = entry
    return latest


class KeepaliveLocked(Exception):
    """Another keep-alive run holds the lock."""


class _RunLock:
    """Non-blocking file lock so scheduled and manual runs never overlap."""

    def __init__(self) -> None:
        self._path = _config_dir() / "keepalive.lock"
        self._fh = None

    def __enter__(self):
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = self._path.open("w")
        try:
            fcntl.flock(self._fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as e:
            self._fh.close()
            raise KeepaliveLocked("Another keep-alive run is in progress.") from e
        return self

    def __exit__(self, *exc):
        fcntl.flock(self._fh, fcntl.LOCK_UN)
        self._fh.close()


# ── Profile discovery ───────────────────────────────────────────────────────


def eligible_profiles(pm: ProfileManager, only: str | None = None) -> list[tuple[str, str]]:
    """Return (profile, skip_reason) pairs; skip_reason is "" for eligible ones.

    Only gemcli-native profiles that have been logged in (email + own Chrome
    profile) are eligible.  This excludes NotebookLM-only profiles and stray
    auth files with no Chrome profile behind them.
    """
    names = [only] if only else pm._list_gemcli_profiles()
    result = []
    for name in names:
        auth = pm.load_auth(name)
        chrome_path = pm.get_chrome_profile_path(name)
        if not auth.get("cookies", {}).get(COOKIE_1PSID) or not auth.get("email"):
            result.append((name, "never logged in (run `gemcli login --profile <name>`)"))
        elif not chrome_path or not Path(chrome_path).is_dir():
            result.append((name, "no Chrome profile on disk"))
        else:
            result.append((name, ""))
    return result


def _daemon_port_for(pm: ProfileManager, name: str) -> int | None:
    """Port of the running Chrome daemon if it holds this profile."""
    from .chrome_manager import check_daemon_health, same_chrome_profile_path

    info, status = check_daemon_health()
    if not info or status != "running":
        return None
    if info.profile_name == name or same_chrome_profile_path(
        info.chrome_profile_path, pm.get_chrome_profile_path(name)
    ):
        return info.port
    return None


def _profile_in_use(chrome_path: str) -> bool:
    """True if any Chrome already runs on exactly this user-data-dir."""
    try:
        out = subprocess.run(
            ["pgrep", "-f", "--", _user_data_dir_pgrep_pattern(Path(chrome_path))],
            capture_output=True, text=True, timeout=3, check=False,
        )
        return bool(out.stdout.strip())
    except Exception:
        return False


# ── Saving auth ─────────────────────────────────────────────────────────────


def _save_auth(
    pm: ProfileManager,
    name: str,
    cookies: dict[str, str],
    email: str,
    tokens: AuthTokens | None,
) -> None:
    am = AuthManager(pm, profile_name=name)
    am.load()
    am.state.cookies = cookies
    if tokens and tokens.snlm0e:
        am.state.tokens = tokens
    if email:
        am.state.email = email
    am.state.last_refreshed = time.time()
    am.save()


def _http_signed_in_email(cookies: dict[str, str]) -> tuple[str, AuthTokens | None]:
    """Fetch Gemini with these cookies; return (email, tokens) if signed in."""
    with httpx.Client(http2=True, headers=GEMINI_HEADERS, follow_redirects=True) as client:
        response = client.get(Endpoint.INIT, cookies=cookies, timeout=30)
    email = extract_email(response.text)
    if not email:
        return "", None
    try:
        return email, extract_tokens(response.text)
    except Exception:
        return email, None


# ── Check-only (no Chrome launched) ─────────────────────────────────────────


def check_profile(pm: ProfileManager, name: str) -> ProfileHealth:
    """Read-only health check: daemon cookies for the daemon profile, else auth.json.

    A rejected auth.json does not prove the account is signed out — Chrome may
    have rotated its cookies since they were saved.  ``refresh_profile`` gives
    the authoritative answer.
    """
    start = time.time()
    port = _daemon_port_for(pm, name)
    try:
        if port:
            ws = get_gemini_page_ws_url(port)
            cookies = _filter_gemini_cookies(get_page_cookies(ws)) if ws else {}
            method = "daemon cookies"
        else:
            cookies = pm.load_auth(name).get("cookies", {})
            method = "saved cookies"
        email, _ = _http_signed_in_email(cookies)
    except Exception as e:
        return ProfileHealth(name, ERROR, detail=str(e), duration=time.time() - start)

    if email:
        return ProfileHealth(name, ALIVE, email=email, method=method,
                             duration=time.time() - start)
    if port:
        return ProfileHealth(name, DEAD, method=method, detail="daemon session is signed out",
                             duration=time.time() - start)
    # Chrome renews short-lived cookies, so a rejected saved copy does not mean
    # the account is signed out — only the profile's own Chrome can tell.
    return ProfileHealth(
        name, STALE, method=method,
        detail="saved copy is out of date — `gemcli keepalive run` refreshes it "
               "(no sign-in needed if the profile's Chrome is still signed in)",
        duration=time.time() - start,
    )


# ── Chrome session helpers ──────────────────────────────────────────────────


class _ProfileChrome:
    """A short-lived Chrome on a profile's own user-data-dir."""

    def __init__(self, chrome_path: str, visible: bool = False):
        self.profile_dir = Path(chrome_path)
        self.visible = visible
        self.port: int | None = None
        self.ws: str | None = None
        self._process: subprocess.Popen | None = None

    def __enter__(self):
        binary = get_chrome_path()
        if not binary:
            raise RuntimeError("No Chromium browser found.")
        self.port = find_available_port(start=_KEEPALIVE_PORT_START, attempts=20)
        args = [
            binary,
            f"--remote-debugging-port={self.port}",
            f"--user-data-dir={self.profile_dir}",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-extensions",
            "--remote-allow-origins=*",
            f"--user-agent={CHROME_USER_AGENT}",
            "--disable-blink-features=AutomationControlled",
        ]
        if self.visible:
            # Real window (Google treats it like a normal browser) kept off-screen.
            args += ["--window-position=-2400,-2400", "--window-size=1100,900"]
        else:
            args.append("--headless")
        self._process = subprocess.Popen(
            args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        for _ in range(40):
            if get_debugger_url(self.port):
                break
            time.sleep(0.25)
        else:
            raise RuntimeError("Chrome did not start in time.")
        page = find_or_create_gemini_page(self.port)
        if not page or not page.get("webSocketDebuggerUrl"):
            raise RuntimeError("Could not open a Gemini page.")
        self.ws = page["webSocketDebuggerUrl"]
        return self

    def __exit__(self, *exc):
        # Browser.close shuts Chrome down cleanly so it flushes renewed
        # cookies to disk; SIGTERM/SIGKILL are fallbacks.
        try:
            browser_ws = get_debugger_url(self.port) if self.port else None
            if browser_ws:
                execute_cdp_command(browser_ws, "Browser.close")
        except Exception:
            pass
        if self._process:
            try:
                self._process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self._process.terminate()
                try:
                    self._process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self._process.kill()
        _clean_lock_files(self.profile_dir)


def _js(ws: str, expression: str, default=""):
    try:
        value = run_js(ws, expression)
        return default if value is None else value
    except Exception:
        return default


def _wait_for_gemini_state(ws: str, timeout: float = _PAGE_SETTLE_TIMEOUT) -> tuple[str, str]:
    """Poll until Gemini is signed in, signed out, or redirected to Google sign-in.

    Returns (state, value): ("signed_in", email), ("signed_out", ""),
    ("google_signin", url), or ("timeout", url).
    """
    signed_out_polls = 0
    deadline = time.time() + timeout
    url = ""
    while time.time() < deadline:
        url = _js(ws, "window.location.href")
        if "accounts.google.com" in url:
            return "google_signin", url
        email = _js(ws, _EMAIL_JS)
        if email:
            return "signed_in", email
        if "gemini.google.com" in url and _js(ws, _READY_JS, False):
            signed_out_polls += 1
            if signed_out_polls >= _SIGNED_OUT_CONFIRMATIONS:
                return "signed_out", ""
        else:
            signed_out_polls = 0
        time.sleep(1)
    return "timeout", url


def _harvest(pm: ProfileManager, name: str, ws: str, email: str) -> None:
    """Copy Chrome's live cookies and tokens into auth.json."""
    cookies = _filter_gemini_cookies(get_page_cookies(ws))
    tokens = None
    try:
        tokens = extract_tokens(get_page_html(ws))
    except Exception:
        snlm0e = _js(ws, _SNLM0E_JS)
        tokens = AuthTokens(snlm0e=snlm0e) if snlm0e else None
    _save_auth(pm, name, cookies, email, tokens)


def classify_signin_page(url: str, text: str) -> str:
    """Name the Google sign-in step shown, for logs and the stop decision."""
    t = text.lower()
    if "challenge/pk" in url or "passkey" in t or "touch id" in t or "fingerprint" in t:
        return "passkey"
    if "challenge/pwd" in url or "enter your password" in t:
        return "password"
    if "/challenge/" in url or "verify it" in t or "2-step" in t:
        return "challenge"
    if "choose an account" in t or "accountchooser" in url.lower():
        return "account_chooser"
    if "signin/identifier" in url or "email or phone" in t:
        return "email_entry"
    return "other"


_CLICK_ACCOUNT_JS = """
((email) => {
    const target = email.toLowerCase();
    for (const el of document.querySelectorAll('[data-identifier], [data-email]')) {
        const id = (el.getAttribute('data-identifier') || el.getAttribute('data-email') || '');
        if (id.toLowerCase() === target) { el.click(); return 'account'; }
    }
    for (const btn of document.querySelectorAll('button, div[role="button"]')) {
        const label = btn.textContent.trim().toLowerCase();
        if (label.startsWith('continue') && btn.textContent.toLowerCase().includes(target)) {
            btn.click(); return 'continue';
        }
    }
    return '';
})(%s)
"""

_CLICK_SIGN_IN_JS = """
(() => {
    for (const el of document.querySelectorAll('button, a')) {
        if (el.textContent.trim() === 'Sign in') { el.click(); return true; }
    }
    return false;
})()
"""


def _try_one_click_recovery(ws: str, expected_email: str, steps: list[str]) -> str:
    """Click "Sign in" and the matching account; never type anything.

    Returns the signed-in email on success, or "" (with the reason in steps).
    """
    if not _js(ws, _CLICK_SIGN_IN_JS, False):
        steps.append("no 'Sign in' button on Gemini")
        return ""
    steps.append("clicked Gemini 'Sign in'")

    clicked_account = False
    deadline = time.time() + _RECOVERY_TIMEOUT
    while time.time() < deadline:
        time.sleep(2)
        url = _js(ws, "window.location.href")
        if "gemini.google.com" in url:
            email = _js(ws, _EMAIL_JS)
            if email:
                steps.append(f"back on Gemini as {email}")
                return email
            continue
        if "accounts.google.com" not in url:
            continue
        text = _js(ws, "document.body ? document.body.innerText.substring(0, 600) : ''")
        kind = classify_signin_page(url, text)
        if kind in ("passkey", "password", "challenge", "email_entry"):
            steps.append(f"Google asked for {kind} — needs a human")
            return ""
        if not clicked_account:
            how = _js(ws, _CLICK_ACCOUNT_JS % json.dumps(expected_email))
            if how:
                clicked_account = True
                steps.append(f"{kind}: clicked {how} for {expected_email}")
            elif kind == "account_chooser":
                steps.append(f"account chooser without {expected_email} — not clicking")
                return ""
    steps.append("timed out waiting for sign-in to finish")
    return ""


# ── Refresh (authoritative, launches the profile's own Chrome) ──────────────


def refresh_profile(pm: ProfileManager, name: str, recover: bool = False) -> ProfileHealth:
    """Renew one profile's session through its own Chrome and mirror the cookies."""
    start = time.time()
    auth = pm.load_auth(name)
    expected_email = auth.get("email", "")
    chrome_path = pm.get_chrome_profile_path(name)
    steps: list[str] = []

    def done(status: str, email: str = "", method: str = "", detail: str = "") -> ProfileHealth:
        return ProfileHealth(name, status, email=email, method=method, detail=detail,
                             duration=round(time.time() - start, 1), steps=steps)

    try:
        port = _daemon_port_for(pm, name)
        if port:
            # Never launch a second Chrome on the daemon's profile, and never
            # navigate its page (a generation may be mid-flight).
            ws = get_gemini_page_ws_url(port)
            cookies = _filter_gemini_cookies(get_page_cookies(ws)) if ws else {}
            email, tokens = _http_signed_in_email(cookies)
            if email:
                _save_auth(pm, name, cookies, email, tokens)
                return done(ALIVE, email, "daemon")
            return done(DEAD, method="daemon", detail="daemon session is signed out — "
                        f"run `gemcli login --profile {name}`")

        try:
            with profile_lock(name, timeout=0):
                return _refresh_own_chrome(name, chrome_path, expected_email, recover,
                                           steps, done, pm)
        except ProfileBusy:
            return done(SKIPPED, detail="profile is busy with a gemcli request")
    except Exception as e:
        logger.debug(f"keepalive: {name} failed: {e}")
        return done(ERROR, detail=str(e))


def _refresh_own_chrome(name, chrome_path, expected_email, recover, steps, done, pm):
    """Load Gemini in the profile's own Chrome; caller holds the profile lock."""
    if _profile_in_use(chrome_path):
        return done(SKIPPED, detail="profile's Chrome is in use (login or another tool)")

    with _ProfileChrome(chrome_path) as chrome:
        navigate_to_url(chrome.ws, GEMINI_APP_URL)
        state, value = _wait_for_gemini_state(chrome.ws)
        steps.append(f"headless load: {state}")
        if state == "signed_in":
            _harvest(pm, name, chrome.ws, value)
            return done(ALIVE, value, "own Chrome")

    if not recover:
        return done(DEAD, method="own Chrome",
                    detail=f"signed out — run `gemcli login --profile {name}`")

    with _ProfileChrome(chrome_path, visible=True) as chrome:
        navigate_to_url(chrome.ws, GEMINI_APP_URL)
        state, value = _wait_for_gemini_state(chrome.ws)
        steps.append(f"window load: {state}")
        email = value if state == "signed_in" else ""
        if not email and state in ("signed_out", "google_signin"):
            email = _try_one_click_recovery(chrome.ws, expected_email, steps)
        if email:
            _harvest(pm, name, chrome.ws, email)
            return done(RECOVERED, email, "one-click sign-in")
    return done(DEAD, method="one-click sign-in",
                detail=f"needs a human — run `gemcli login --profile {name}`")


# ── Runs ────────────────────────────────────────────────────────────────────


# How long a keep-alive probe waits for a profile busy with real requests.
_PROBE_LOCK_WAIT = 60


def probe_capture(pm: ProfileManager, name: str) -> tuple[str, str]:
    """Probe BotGuard token capture; return the ``capture`` and ``transport`` fields."""
    from .probe import probe_token_capture

    probe = probe_token_capture(
        name, pm.get_chrome_profile_path(name), lock_timeout=_PROBE_LOCK_WAIT
    )
    if not probe.ok and probe.detail == "busy":
        return "skipped: profile busy with requests", ""
    return probe.summary(), probe.transport


def run_keepalive(
    only: str | None = None,
    recover: bool = False,
    check_only: bool = False,
    on_result: Callable[[ProfileHealth], None] | None = None,
    probe: bool = True,
) -> list[ProfileHealth]:
    """Check or refresh every eligible profile; log each result.

    With ``probe`` (default), each signed-in profile also gets a BotGuard
    token-capture probe, recorded in ``ProfileHealth.capture``. The probe
    sends nothing to Gemini.

    Raises KeepaliveLocked if another run is in progress.
    """
    pm = ProfileManager()
    run_id = time.strftime("%Y%m%d-%H%M%S")
    results: list[ProfileHealth] = []
    with _RunLock():
        for name, skip_reason in eligible_profiles(pm, only):
            if skip_reason:
                result = ProfileHealth(name, SKIPPED, detail=skip_reason)
            elif check_only:
                result = check_profile(pm, name)
            else:
                result = refresh_profile(pm, name, recover=recover)
                if probe and result.ok:
                    result.capture, result.transport = probe_capture(pm, name)
            if not check_only:
                _append_log(result, run_id)
            results.append(result)
            if on_result:
                on_result(result)
    return results


# ── Scheduled runs (macOS LaunchAgent) ──────────────────────────────────────

KEEPALIVE_AGENT_LABEL = "com.gemcli.keepalive"


def keepalive_plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{KEEPALIVE_AGENT_LABEL}.plist"


def build_keepalive_plist(gemcli_path: str, every_hours: float, recover: bool,
                          path_env: str, log_dir: Path) -> str:
    """Render the LaunchAgent plist that runs `gemcli keepalive run` periodically."""
    args = [gemcli_path, "keepalive", "run"] + (["--recover"] if recover else [])
    args_xml = "\n".join(f"        <string>{a}</string>" for a in args)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{KEEPALIVE_AGENT_LABEL}</string>

    <key>ProgramArguments</key>
    <array>
{args_xml}
    </array>

    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>{path_env}</string>
    </dict>

    <key>StartInterval</key>
    <integer>{int(every_hours * 3600)}</integer>

    <key>RunAtLoad</key>
    <true/>

    <key>LimitLoadToSessionType</key>
    <string>Aqua</string>

    <key>StandardOutPath</key>
    <string>{log_dir}/keepalive-agent.log</string>
    <key>StandardErrorPath</key>
    <string>{log_dir}/keepalive-agent.err</string>
</dict>
</plist>
"""


def install_keepalive_agent(every_hours: float = 4, recover: bool = False) -> Path:
    """Write and load the keep-alive LaunchAgent. macOS only."""
    import os
    import platform

    from .chrome_manager import _find_gemcli_path, load_launch_agent

    if platform.system() != "Darwin":
        raise RuntimeError("The keep-alive agent is macOS-only; schedule "
                           "`gemcli keepalive run` with cron or systemd instead.")
    if every_hours < 1:
        raise ValueError("Run the keep-alive at most once an hour.")

    home = Path.home()
    path_env = ":".join([
        str(home / ".local" / "bin"), str(home / ".cargo" / "bin"),
        "/usr/local/bin", "/opt/homebrew/bin",
        os.environ.get("PATH", "/usr/bin:/bin:/usr/sbin:/sbin"),
    ])
    log_dir = _config_dir() / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    plist = keepalive_plist_path()
    plist.parent.mkdir(parents=True, exist_ok=True)
    uninstall_keepalive_agent()  # reload cleanly if the interval changed
    plist.write_text(
        build_keepalive_plist(_find_gemcli_path(), every_hours, recover, path_env, log_dir),
        encoding="utf-8",
    )
    load_launch_agent(plist)
    return plist


def uninstall_keepalive_agent() -> bool:
    """Unload and remove the keep-alive LaunchAgent. Returns True if one existed."""
    from .chrome_manager import unload_launch_agent

    plist = keepalive_plist_path()
    unload_launch_agent(KEEPALIVE_AGENT_LABEL, plist)
    if plist.exists():
        plist.unlink()
        return True
    return False
