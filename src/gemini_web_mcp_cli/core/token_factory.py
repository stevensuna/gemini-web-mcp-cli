"""Token Factory: capture BotGuard tokens from Chrome for Pro/Thinking model switching.

Chrome generates BotGuard tokens that validate model selection headers.
The Token Factory intercepts the XHR request before it's sent, captures the
token, and lets Python replay the request with the desired model header.

All methods are sync (CDP uses sync websocket library). Called from async
client via run_in_executor.
"""

from __future__ import annotations

import atexit
import json
import os
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urljoin

from loguru import logger

from .cdp import (
    StaleTargetError,
    _clean_lock_files,
    _clear_port_map,
    _user_data_dir_pgrep_pattern,
    _write_port_map,
    execute_cdp_command,
    find_available_port,
    find_existing_gemcli_chrome,
    find_or_create_gemini_page,
    get_chrome_path,
    get_current_url,
    get_debugger_url,
    get_page_cookies,
    is_chrome_healthy,
    navigate_to_url,
    run_js,
)
from .constants import (
    CHROME_HEADERS,
    CHROME_USER_AGENT,
    IMAGE_TOOL_ID,
    MODEL_HEADER_KEY,
    MUSIC_TOOL_ID,
    VIDEO_ORIENTATION_LABELS,
    VIDEO_TOOL_ID,
    compute_xbv,
    rewrite_captured_model_header,
)
from .exceptions import (
    AuthError,
    GeminiError,
    PromptEscaped,
    TokenFactoryError,
    ToolActivationError,
    UsageLimitExceeded,
)
from .locks import profile_lock
from .webchannel import TRANSPORT_PROCESS_SESSION, TRANSPORT_STREAMGENERATE

GEMINI_APP_URL = "https://gemini.google.com/app"

# Force a full page reload every N captures to refresh stale SNlM0e tokens.
# WIZ_global_data tokens can go stale server-side after many generations.
_GENERATIONS_BEFORE_REFRESH = 5

# Shut down Chrome after this many seconds of inactivity to free resources.
# Override with GEMCLI_CHROME_IDLE_TIMEOUT env var. Set to 0 to disable.
_CHROME_IDLE_TIMEOUT_DEFAULT = 120

# How long shutdown() waits for another process's capture before leaving the
# Chrome it launched running for that process.
_SHUTDOWN_LOCK_WAIT = 30

# Chat interceptor JS — hooks XMLHttpRequest and fetch to capture the chat request.
# Captures the URL, headers (including BotGuard token set by JS), and body,
# then aborts the original request so Chrome doesn't send it.
#
# Two transports (Google picks one per account):
# - StreamGenerate: one POST; captured as-is.
# - processSession (WebChannel, core/webchannel.py): the channel-open POST
#   (URL carries $httpHeaders: auth + model header) is let through and
#   recorded; the first data POST (setup message with the BotGuard token) is
#   captured and aborted, and so is every later data POST, so the prompt
#   never leaves Chrome.
XHR_INTERCEPTOR_JS = """
(() => {
    window.__cap = null;
    window.__psOpen = null;
    const origOpen = XMLHttpRequest.prototype.open;
    const origSend = XMLHttpRequest.prototype.send;
    const origSetHeader = XMLHttpRequest.prototype.setRequestHeader;

    XMLHttpRequest.prototype.open = function(m, u, ...r) {
        this.__u = String(u); this.__m = m; this.__h = {};
        return origOpen.call(this, m, u, ...r);
    };
    XMLHttpRequest.prototype.setRequestHeader = function(n, v) {
        if (this.__h) this.__h[n] = v;
        return origSetHeader.call(this, n, v);
    };
    XMLHttpRequest.prototype.send = function(body) {
        const u = this.__u || '';
        if (u.includes('StreamGenerate')) {
            // Capture the first; abort every one, so Chrome never sends a prompt.
            if (!window.__cap) {
                window.__cap = {transport: 'streamgenerate', url: u, headers: this.__h,
                                body: body};
            }
            this.abort();
            return;
        }
        if (u.includes('/processSession') && this.__m === 'POST') {
            if (u.includes('X-HTTP-Session-Id')) {
                window.__psOpen = u;
            } else if (typeof body === 'string' && body.includes('___data__')) {
                if (!window.__cap) {
                    window.__cap = {transport: 'processSession', url: window.__psOpen,
                                    headers: this.__h, body: body};
                }
                this.abort();
                return;
            }
        }
        return origSend.call(this, body);
    };

    // Some accounts now use fetch for the same chat endpoints.
    const origFetch = window.fetch;
    window.fetch = async function(input, init) {
        const request = input instanceof Request ? input : null;
        const u = request ? request.url : String(input);
        const method = String(init?.method || request?.method || 'GET').toUpperCase();
        const stream = u.includes('StreamGenerate');
        const session = u.includes('/processSession') && method === 'POST';
        if (!stream && !session) return origFetch.call(this, input, init);

        let body = init?.body;
        if (body === undefined && request) body = await request.clone().text();
        if (body instanceof URLSearchParams) body = body.toString();
        if (session && u.includes('X-HTTP-Session-Id')) {
            window.__psOpen = u;
            return origFetch.call(this, input, init);
        }
        if (stream || (typeof body === 'string' && body.includes('___data__'))) {
            if (!window.__cap) {
                const headers = Object.fromEntries(new Headers(init?.headers ?? request?.headers));
                window.__cap = {transport: stream ? 'streamgenerate' : 'processSession',
                                url: stream ? u : window.__psOpen, headers: headers, body: body};
            }
            throw new DOMException('Token Factory captured the chat request', 'AbortError');
        }
        return origFetch.call(this, input, init);
    };
})()
"""

# JS to type a prompt into the Gemini input field
TYPE_PROMPT_JS = """
(() => {{
    const input = document.querySelector('div[contenteditable="true"]');
    if (input) {{
        input.focus(); input.click();
        document.execCommand('selectAll');
        document.execCommand('delete');
        document.execCommand('insertText', false, {prompt!r});
    }}
}})()
"""

# JS to click the send button
CLICK_SEND_JS = """
(() => {
    const btn = document.querySelector('button[aria-label="Send message"]')
        || document.querySelector('button[data-test-id="send-button"]');
    if (btn) btn.click();
})()
"""

# JS to check if the input field is ready
INPUT_READY_JS = '!!document.querySelector(\'div[contenteditable="true"]\')'

# Map tool_id integers to their names in Chrome's Tools drawer UI.
# These must match the text labels in Gemini's .toolbox-drawer-item-list-button elements.
TOOL_ID_TO_NAME = {
    14: "Images",   # IMAGE_TOOL_ID
    11: "Videos",   # VIDEO_TOOL_ID
    21: "Music",    # MUSIC_TOOL_ID
}

# The drawer has two layouts depending on page state:
#   zero-state:  "Images" / "Videos" / "Music"
#   conversation: "Create image" / "Create video" / "Create music"
# Matching any alias keeps tool activation working in both layouts.
TOOL_ID_UI_ALIASES = {
    14: ("Images", "Create image"),
    11: ("Videos", "Create video"),
    21: ("Music", "Create music"),
}

# JS to activate a specific tool in Chrome's Tools drawer.
# Opens the drawer, finds the button matching one of the UI aliases, and clicks
# it if not already checked. Returns 'already_active', 'activated', or 'not_found'.
ACTIVATE_TOOL_JS = """
((toolNames) => {{
    const names = toolNames.map(n => n.toLowerCase());

    // Dismiss any overlay (drawer/menu) left open from a previous interaction
    document.body.click();

    // Check if tool is already active (deselect chip visible in chat bar)
    const activeLabels = Array.from(document.querySelectorAll('button'))
        .map(b => b.getAttribute('aria-label') || '');
    for (const name of names) {{
        if (activeLabels.some(l => l.toLowerCase() === `close ${{name}}`)) return 'already_active';
        const deselect = `deselect ${{name}}`;
        if (activeLabels.some(l => l.toLowerCase() === deselect)) return 'already_active';
    }}

    const oldDeselect = document.querySelector('button.toolbox-drawer-item-deselect-button');
    if (oldDeselect && names.some(n => oldDeselect.textContent.toLowerCase().includes(n))) {{
        return 'already_active';
    }}

    // Open the drawer
    const drawerBtn = Array.from(document.querySelectorAll('button')).find(
        b => b.getAttribute('aria-label') === 'Upload & tools' ||
             b.textContent.trim().includes('Upload') ||
             b.getAttribute('aria-label') === 'Tools' ||
             b.className.includes('toolbox-drawer-button')
    );
    if (!drawerBtn) return 'no_drawer';
    drawerBtn.click();

    // Wait for the drawer to render, then find and click the tool. Poll for a
    // few seconds because the drawer/items can take a moment to appear.
    return new Promise(resolve => {{
        const isDisabled = (el) => el.disabled === true ||
            el.getAttribute('aria-disabled') === 'true' ||
            !!el.querySelector('[disabled], [aria-disabled="true"]');
        const findMatches = () => Array.from(
            document.querySelectorAll('mat-list-item, button, a')
        ).filter(el => {{
            const text = el.textContent.trim().toLowerCase();
            const matches = (n) => text.startsWith(n) || (text.length < 80 && text.includes(n));
            return names.some(matches);
        }});
        const legacyItems = () => document.querySelectorAll(
            'button.toolbox-drawer-item-list-button'
        );
        const activate = (toolItem) => {{
            toolItem.click();
            // Check for onboarding modal with a "Try it" button
            setTimeout(() => {{
                const tryItBtn = Array.from(document.querySelectorAll('button')).find(
                    b => b.textContent.includes('Try it')
                );
                if (tryItBtn) {{
                    tryItBtn.click();
                }}
                resolve('activated');
            }}, 500);
        }};
        const start = Date.now();
        const tick = () => {{
            const listItems = findMatches();
            const toolItem = listItems.find(el => !isDisabled(el));
            if (toolItem) {{ activate(toolItem); return; }}

            const disabledMatch = listItems.find(isDisabled);
            if (disabledMatch) {{
                document.body.click();
                resolve('disabled');
                return;
            }}

            if (Date.now() - start > 3500) {{
                for (const item of legacyItems()) {{
                    const text = item.textContent.toLowerCase();
                    if (names.some(n => text.includes(n))) {{
                        const checked = item.getAttribute('aria-checked');
                        if (checked === 'true') {{
                            document.body.click();
                            resolve('already_active');
                            return;
                        }}
                        activate(item);
                        return;
                    }}
                }}
                document.body.click();
                resolve('not_found');
                return;
            }}
            setTimeout(tick, 300);
        }};
        setTimeout(tick, 500);
    }});
}})({tool_names_json})
"""

# JS to pick an option from a composer dropdown (aspect ratio, music length /
# vocals / genre). Chrome encodes these picks in inner[55] and inner[0][9], so
# driving the UI keeps the BotGuard-signed body consistent.
#   mode 'aspect': match the control whose aria-label starts with "Aspect ratio"
#   mode 'named':  match the control whose aria-label equals `control` or whose
#                  text starts with it (e.g. Length, Vocals, Genre)
# Resolves to 'already_active', 'selected', 'not_found', or 'no_control'.
SELECT_COMPANION_OPTION_JS = """
((mode, control, label) => {{
    return new Promise(resolve => {{
        const findBtn = () => {{
            if (mode === 'aspect') {{
                return Array.from(document.querySelectorAll('button')).find(
                    b => (b.getAttribute('aria-label') || '').startsWith('Aspect ratio')
                );
            }}
            // Named controls rename after a pick (e.g. "Length" -> "Length, Short"),
            // so match the bare label, the "<label>, <value>" form, or button text.
            return Array.from(document.querySelectorAll('button')).find(
                b => {{
                    const aria = (b.getAttribute('aria-label') || '').trim();
                    return aria === control || aria.startsWith(control + ',');
                }}
            ) || Array.from(document.querySelectorAll('button')).find(
                b => (b.textContent || '').trim().startsWith(control)
            );
        }};
        const norm = (s) => (s || '').trim().replace(/\\s+/g, ' ').toLowerCase();
        const want = norm(label);
        const optionNodes = () => document.querySelectorAll(
            'input-companion-item, [role="menuitem"], [role="menuitemradio"], '
            + 'gem-menu-item, .mat-mdc-menu-item'
        );
        const findOption = () => {{
            let exact = null;
            let prefix = null;
            optionNodes().forEach(el => {{
                const text = norm(el.getAttribute('aria-label') || el.textContent);
                if (text === want) exact = exact || el;
                else if (prefix === null && text.startsWith(want)) prefix = el;
            }});
            return exact || prefix;
        }};
        const findChecked = () => {{
            let found = null;
            optionNodes().forEach(el => {{
                const text = norm(el.getAttribute('aria-label') || el.textContent);
                const matches = text === want || text.startsWith(want);
                if (matches && el.getAttribute('aria-checked') === 'true') found = el;
            }});
            return found;
        }};
        const buttonLabel = () => {{
            const b = findBtn();
            return b ? norm(b.getAttribute('aria-label')) : '';
        }};
        const waitFor = (fn, timeout, done) => {{
            const start = Date.now();
            const tick = () => {{
                const value = fn();
                if (value) {{ done(value); return; }}
                if (Date.now() - start > timeout) {{ done(null); return; }}
                setTimeout(tick, 150);
            }};
            tick();
        }};
        const verify = (done) => {{
            waitFor(() => buttonLabel() && buttonLabel().includes(want) ? 'ok' : null,
                2000, (viaLabel) => {{
                    if (viaLabel) {{ done(true); return; }}
                    document.body.click();
                    const btn = findBtn();
                    if (btn) btn.click();
                    waitFor(findChecked, 2000, (checked) => {{
                        document.body.click();
                        done(!!checked);
                    }});
                }});
        }};
        const attempt = (n) => {{
            document.body.click();
            const btn = findBtn();
            if (!btn) {{
                if (n < 3) {{ setTimeout(() => attempt(n + 1), 900); return; }}
                resolve('no_control');
                return;
            }}
            const current = buttonLabel();
            if (current && current.includes(want)) {{ resolve('already_active'); return; }}
            btn.click();
            waitFor(findOption, 2500, (target) => {{
                if (!target) {{
                    if (n < 2) {{ attempt(n + 1); return; }}
                    resolve('not_found');
                    return;
                }}
                target.click();
                verify((ok) => resolve(ok ? 'selected' : 'not_selected'));
            }});
        }};
        attempt(0);
    }});
}})('{mode}', '{control}', '{label}')
"""

# JS to select a template card on the Create videos / Create music page.
# Templates prefill the composer (custom prompt and options still apply) and
# add a template descriptor to the captured body at inner[0][9].
SELECT_TEMPLATE_JS = """
((templateName) => {
    return new Promise(resolve => {
        const want = templateName.trim().toLowerCase();
        const waitFor = (fn, timeout, done) => {
            const start = Date.now();
            const tick = () => {
                const value = fn();
                if (value) { done(value); return; }
                if (Date.now() - start > timeout) { done(null); return; }
                setTimeout(tick, 250);
            };
            tick();
        };
        const findCard = () => {
            let target = null;
            document.querySelectorAll('*').forEach(el => {
                if (target) return;
                if (el.children.length !== 0) return;
                const text = (el.textContent || '').trim();
                if (text.toLowerCase() === want) target = el;
            });
            if (!target) return null;
            return target.closest('button, [role="button"], a, [tabindex]') || target;
        };
        const wasOnTemplatesPage = document.body.innerText.includes('Create videos')
            || document.body.innerText.includes('Create music');
        waitFor(findCard, 8000, (card) => {
            if (!card) { resolve('not_found'); return; }
            card.click();
            waitFor(() => {
                if (!wasOnTemplatesPage) return 'ok';
                const pageGone = !document.body.innerText.includes('Create videos')
                    && !document.body.innerText.includes('Create music');
                const placeholder = (document.querySelector('div[contenteditable="true"]') || {})
                    .getAttribute('data-placeholder') || '';
                const placeholderChanged = placeholder && placeholder !== 'Describe your video'
                    && placeholder !== 'Describe your track';
                return pageGone || placeholderChanged ? 'ok' : null;
            }, 4000, (ok) => resolve(ok ? 'selected' : 'clicked'));
        });
    });
})('{template_name}')
"""

# JS to set the model picker (Flash / Pro / Flash-Lite / Argon / Thinking level).
# The base model is selected by hash through data-test-id, which is stable
# across UI label changes. Thinking level is the Low / Medium / High submenu
# (value="thinking_level"). High is the old Extended thinking toggle.
SET_MODEL_PICKER_JS = """
((hash, level) => {
    return new Promise(resolve => {
        const findBtn = () => Array.from(document.querySelectorAll('button')).find(
            b => (b.getAttribute('aria-label') || '').includes('Open mode picker')
        );
        const openPicker = () => {
            const b = findBtn();
            if (b) b.click();
        };
        const optionEl = () => document.querySelector(
            '[data-test-id="bard-mode-option-' + hash + '"]'
        );
        const selectedEl = () => {
            const option = optionEl();
            return option && option.className.includes('selected') ? option : null;
        };
        const waitFor = (fn, timeout, done) => {
            const start = Date.now();
            const tick = () => {
                const value = fn();
                if (value) { done(value); return; }
                if (Date.now() - start > timeout) { done(null); return; }
                setTimeout(tick, 150);
            };
            tick();
        };
        const levelItem = () => {
            let item = null;
            document.querySelectorAll('[role="menuitem"]').forEach(el => {
                if (item) return;
                const text = (el.innerText || '').trim();
                const isLevel = text.startsWith(level)
                    && (el.getAttribute('value') || '') !== 'thinking_level';
                if (isLevel) {
                    item = el;
                }
            });
            return item;
        };

        const selectBase = (attempt) => {
            document.body.click();
            openPicker();
            waitFor(optionEl, 3000, (option) => {
                if (!option) {
                    if (attempt < 2) { selectBase(attempt + 1); return; }
                    resolve('no_picker');
                    return;
                }
                if (!option.className.includes('selected')) option.click();
                openPicker();
                waitFor(selectedEl, 3000, (ok) => {
                    document.body.click();
                    if (ok) { reconcileLevel(0); return; }
                    if (attempt < 2) { selectBase(attempt + 1); return; }
                    resolve('base_failed');
                });
            });
        };

        const reconcileLevel = (attempt) => {
            document.body.click();
            openPicker();
            waitFor(() => {
                let row = null;
                document.querySelectorAll('[role="menuitem"]').forEach(el => {
                    if (row) return;
                    if ((el.getAttribute('value') || '') === 'thinking_level') row = el;
                });
                return row;
            }, 3000, (row) => {
                if (!row) {
                    if (attempt < 2) { reconcileLevel(attempt + 1); return; }
                    resolve('level_not_found');
                    return;
                }
                if (row.getAttribute('aria-expanded') !== 'true') row.click();
                waitFor(levelItem, 2500, (item) => {
                    if (!item) {
                        if (attempt < 2) { reconcileLevel(attempt + 1); return; }
                        resolve('level_not_found');
                        return;
                    }
                    if (!item.className.includes('selected')) item.click();
                    document.body.click();
                    resolve('set');
                });
            });
        };

        selectBase(0);
    });
})('{hash}', '{level}')
"""

# JS to choose the Chat / Task segmented control under the prompt.
# Task is the agent mode previously called Spark. The selected class sits on
# the parent .gem-segmented-button, not on the button itself.
SET_COMPOSER_MODE_JS = """
((want) => {
    const btn = Array.from(document.querySelectorAll('button')).find(
        b => (b.innerText || '').trim() === want
    );
    if (!btn) return 'missing';
    const host = btn.closest('.gem-segmented-button');
    if (host && host.className.includes('gem-segmented-button-selected')) return 'already';
    btn.click();
    return 'set';
})('{mode}')
"""

# JS to deactivate any active tool (click the × on the chip in the chat bar)
DEACTIVATE_TOOL_JS = """
(() => {
    const newDeselect = Array.from(document.querySelectorAll('button')).find(
        b => {
            const label = b.getAttribute('aria-label') || '';
            return label.startsWith('close ') &&
                   label !== 'close sidebar' &&
                   label !== 'close sidenav';
        }
    );
    if (newDeselect) {
        newDeselect.click();
        return true;
    }
    const oldDeselect = document.querySelector('button.toolbox-drawer-item-deselect-button');
    if (oldDeselect) {
        oldDeselect.click();
        return true;
    }
    return false;
})()
"""


@dataclass
class CapturedRequest:
    """A captured chat request from Chrome, ready for Python replay.

    For ``transport == "processSession"``, ``url`` is the WebChannel open URL
    (carries auth and the model header) and ``body`` is the aborted data POST
    holding the setup message; see core/webchannel.py.
    """

    url: str
    body: str
    headers: dict[str, str]
    cookies: dict[str, str]
    access_token: str | None = None  # Chrome's live SNlM0e token (WIZ_global_data)
    transport: str = TRANSPORT_STREAMGENERATE


class TokenFactory:
    """Captures BotGuard tokens from Chrome for Python HTTP replay.

    Usage:
        factory = TokenFactory(chrome_profile_path="/path/to/profile", profile_name="default")
        factory.ensure_ready()
        captured = factory.capture(prompt="Hello", model=some_model, metadata=None)
        # Use captured.url, captured.body, captured.headers, captured.cookies
        # to send via httpx
        factory.shutdown()
    """

    def __init__(
        self,
        chrome_profile_path: str | None = None,
        profile_name: str = "default",
    ):
        self._chrome_profile_path = chrome_profile_path
        self._profile_name = profile_name
        self._port: int | None = None
        self._ws_url: str | None = None
        self._process = None
        self._we_launched: bool = False
        self._ready: bool = False
        self._raw_cookies: list[dict] = []
        self._generation_count: int = 0
        try:
            self._idle_timeout: int = int(
                os.environ.get("GEMCLI_CHROME_IDLE_TIMEOUT", _CHROME_IDLE_TIMEOUT_DEFAULT)
            )
        except ValueError:
            logger.warning(
                "GEMCLI_CHROME_IDLE_TIMEOUT is not a valid integer, "
                f"using default ({_CHROME_IDLE_TIMEOUT_DEFAULT}s)"
            )
            self._idle_timeout = _CHROME_IDLE_TIMEOUT_DEFAULT
        self._idle_timer: threading.Timer | None = None
        self._idle_lock = threading.Lock()
        self._idle_generation: int = 0
        atexit.register(self.shutdown)
        # Handle SIGTERM/SIGINT so cleanup runs when a parent process kills us
        # (atexit does NOT fire on SIGTERM — Python uses the OS default which
        # terminates immediately).  Signal handlers can only be set from the
        # main thread; silently skip if we're in a worker thread.
        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                signal.signal(sig, self._signal_handler)
            except (OSError, ValueError):
                pass

    def _signal_handler(self, signum, frame):
        """Handle SIGTERM/SIGINT by cleaning up Chrome before exit."""
        self.shutdown()
        sys.exit(128 + signum)

    def _cancel_idle_timer(self) -> None:
        """Cancel any pending idle shutdown timer."""
        with self._idle_lock:
            if self._idle_timer is not None:
                self._idle_timer.cancel()
                self._idle_timer = None
            self._idle_generation += 1

    def _reset_idle_timer(self) -> None:
        """Start/reset the idle shutdown timer after a capture completes.

        Only applies when we launched Chrome ourselves (not reusing a daemon).
        """
        if not self._we_launched or self._idle_timeout <= 0:
            return
        with self._idle_lock:
            if self._idle_timer is not None:
                self._idle_timer.cancel()
            self._idle_generation += 1
            gen = self._idle_generation
            self._idle_timer = threading.Timer(
                self._idle_timeout, self._idle_shutdown, args=(gen,)
            )
            self._idle_timer.daemon = True
            self._idle_timer.start()
            logger.debug(
                f"Token Factory: Chrome idle timer set to {self._idle_timeout}s"
            )

    def _idle_shutdown(self, gen: int) -> None:
        """Auto-shutdown Chrome after idle timeout to free resources."""
        with self._idle_lock:
            self._idle_timer = None
            if gen != self._idle_generation:
                return
        if self._we_launched and self._ready:
            logger.info(
                f"Token Factory: Chrome idle for {self._idle_timeout}s, "
                "shutting down to free resources (will restart on next request)"
            )
            self.shutdown()

    def ensure_ready(self) -> None:
        """Lazy init: find/launch Chrome, navigate to Gemini, wait for input field.

        Holds the profile lock so two processes never launch, kill or drive
        the same profile's Chrome at the same time.
        """
        self._cancel_idle_timer()
        with profile_lock(self._profile_name):
            self._ensure_ready_locked()

    def _chrome_still_up(self) -> bool:
        """True if the Chrome this factory attached to still answers CDP.

        Another process (daemon restart, idle shutdown of a Chrome it launched)
        may have closed it since the last capture.
        """
        from .chrome_manager import is_chrome_responsive

        return bool(self._port) and is_chrome_responsive(self._port)

    def _ensure_ready_locked(self) -> None:
        if self._ready:
            if self._chrome_still_up():
                return
            logger.warning(
                f"Token Factory: Chrome on port {self._port} went away — reconnecting"
            )
            if self._we_launched and self._process:
                try:
                    self._process.kill()
                except Exception:
                    pass
                self._process = None
            self._ready = False
            self._ws_url = None
            self._port = None
            self._we_launched = False

        chrome_path = get_chrome_path()
        if not chrome_path:
            raise TokenFactoryError(
                "No Chromium browser found. Install Chrome, Brave, Edge, or another "
                "Chromium browser for Pro/Thinking models.\n"
                "Set preference: GEMCLI_BROWSER=brave or gemcli config set browser brave"
            )

        if not self._chrome_profile_path:
            raise TokenFactoryError(
                "No Chrome profile configured. Run 'gemcli login' first."
            )

        # Try to find an existing gemcli Chrome instance for our profile
        # (profile-aware — won't accidentally grab Antigravity's browser).
        # If the daemon is running ('gemcli chrome start'), it's registered
        # in the port map and will be found here.  We should ALWAYS reuse
        # a running daemon — it has the authenticated session and avoids
        # launching a stale TF profile.
        #
        # Health-check first: this may auto-stop+cleanup a daemon whose age
        # or RSS has exceeded the limits, which clears the port map entry
        # so find_existing_gemcli_chrome() naturally returns nothing and we
        # fall through to launch a fresh TF Chrome below.
        from .chrome_manager import check_daemon_health

        check_daemon_health()
        existing_port, existing_url = find_existing_gemcli_chrome(
            profile_name=self._profile_name
        )

        if existing_port:
            # Health check: verify the Chrome has functional pages before
            # committing to reuse it.  A zombie Chrome (PID alive, CDP
            # responding, but zero pages) will fail downstream.
            if is_chrome_healthy(existing_port):
                self._port = existing_port
                self._we_launched = False
                logger.debug(f"Token Factory: reusing Chrome on port {existing_port}")
                # Verify the connection actually works (catches stale target IDs
                # left over from a Chrome restart — Bug 4)
                try:
                    page = find_or_create_gemini_page(self._port)
                    if page and page.get("webSocketDebuggerUrl"):
                        ws_url = page["webSocketDebuggerUrl"]
                        get_current_url(ws_url)  # Probe — raises StaleTargetError if stale
                    else:
                        raise StaleTargetError("No functional Gemini page")
                except (StaleTargetError, Exception) as e:
                    logger.warning(
                        f"Token Factory: Chrome on port {existing_port} has "
                        f"stale target IDs ({e}) — clearing and launching fresh"
                    )
                    _clear_port_map(existing_port)
                    existing_port = None  # Fall through to fresh launch
            else:
                logger.warning(
                    f"Token Factory: Chrome on port {existing_port} is unhealthy "
                    f"(no pages), launching fresh instance"
                )
                existing_port = None  # Fall through to fresh launch

        if not existing_port:
            # Launch on the profile's OWN user-data-dir. Never a copy: a copied
            # profile carries the same (device-bound) Google session, and using
            # one session from several browsers gets it revoked (issue #3).
            profile_dir = Path(self._chrome_profile_path)
            profile_dir.mkdir(parents=True, exist_ok=True)

            # Clean up orphaned Chrome processes on exactly this profile
            self._kill_stale_chrome(profile_dir)

            # Use a different port range (9300+) for headless TF instances
            # so they don't block `gemcli login` from using the 9222+ range
            # when searching for existing visible browsers.
            self._port = find_available_port(start=9300)
            from gemini_web_mcp_cli.core.constants import CHROME_USER_AGENT
            args = [
                chrome_path,
                f"--remote-debugging-port={self._port}",
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-extensions",
                f"--user-data-dir={profile_dir}",
                "--remote-allow-origins=*",
                "--headless",
                f"--user-agent={CHROME_USER_AGENT}",
                "--disable-blink-features=AutomationControlled",
            ]
            try:
                # DEVNULL, not PIPE: nobody reads these pipes, and a long-lived
                # Chrome blocks once its stderr fills the 64 KB pipe buffer.
                self._process = subprocess.Popen(
                    args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                )
                time.sleep(3)
            except Exception as e:
                raise TokenFactoryError(f"Failed to launch Chrome: {e}")
            self._we_launched = True
            # Register in port map so other gemcli components can discover us
            _write_port_map(self._port, self._profile_name, self._process.pid)
            logger.debug(
                f"Token Factory: launched Chrome on port {self._port} "
                f"with TF profile {profile_dir}"
            )

        # Find or create Gemini page (retry — headless Chrome may take
        # a moment for the debugger endpoint to become responsive)
        page = None
        for _ in range(5):
            page = find_or_create_gemini_page(self._port)
            if page:
                break
            time.sleep(3)
        if not page:
            raise TokenFactoryError("Failed to open Gemini page in Chrome.")

        self._ws_url = page.get("webSocketDebuggerUrl")
        if not self._ws_url:
            raise TokenFactoryError("No WebSocket URL for Gemini page.")

        # Navigate to /app if not already there (this also leaves a Google
        # sign-in page a previous failed attempt may have parked Chrome on).
        current_url = get_current_url(self._ws_url)
        if "gemini.google.com/app" not in current_url:
            navigate_to_url(self._ws_url, GEMINI_APP_URL)

        # Wait for input field
        if not self._wait_for_input():
            raise TokenFactoryError("Gemini page failed to load (input field not found).")

        # Verify the page is signed in. The signed-out Gemini page also has an
        # SNlM0e, so only the account email (oPEP7c) proves a session. Saved
        # auth.json cookies are never injected into Chrome: this Chrome owns
        # the session, and mixing in another copy gets it revoked (issue #3).
        signed_in_email = run_js(self._ws_url, "window.WIZ_global_data?.oPEP7c || ''")
        snlm0e = run_js(
            self._ws_url, "window.WIZ_global_data?.SNlM0e || ''"
        ) if signed_in_email else ""

        if not snlm0e:
            logger.info(
                "Token Factory: Chrome profile is signed out — attempting "
                "one-click sign-in via CDP..."
            )
            snlm0e = self._auto_sign_in()
            if not snlm0e:
                raise AuthError(
                    "Session expired — auto sign-in failed.\n"
                    f"Run 'gemcli login --profile {self._profile_name}' to sign in again."
                )

        self._ready = True
        logger.debug("Token Factory: ready")

    def _auto_sign_in(self) -> str | None:
        """Attempt automatic sign-in by clicking Gemini's Sign In button via CDP.

        Chrome's profile retains the Google account at the browser level even
        when Gemini session cookies expire.  Clicking "Sign in" triggers an
        OAuth redirect that Chrome auto-completes — zero user interaction.

        If the redirect lands on a Google account-chooser page, the first
        account is selected automatically. If Chrome has no saved Google
        account and lands on the email-entry page, the saved AuthManager email
        is submitted before continuing the OAuth flow.

        Returns:
            The SNlM0e token if sign-in succeeds, or None on failure.
        """
        from .cdp import _filter_gemini_cookies

        ws = self._ws_url
        auth_email = self._load_auth_email()

        # Click "Sign in" in the Gemini UI
        clicked = run_js(ws, """
            (() => {
                const buttons = document.querySelectorAll('button');
                for (const btn of buttons) {
                    if (btn.textContent.trim() === 'Sign in') {
                        btn.click();
                        return true;
                    }
                }
                return false;
            })()
        """)
        if not clicked:
            logger.debug("Token Factory: no 'Sign in' button found")
            return None

        # Monitor the redirect chain (max ~30s)
        for attempt in range(15):
            time.sleep(2)
            try:
                url = run_js(ws, "window.location.href") or ""
            except Exception:
                continue

            # Success: back on Gemini with valid session. The signed-out page
            # also carries an SNlM0e, so require the account email (oPEP7c) —
            # otherwise the first poll "succeeds" before the redirect happens.
            if "gemini.google.com/app" in url:
                signed_in_email = run_js(
                    ws, "window.WIZ_global_data?.oPEP7c || ''"
                )
                snlm0e = run_js(
                    ws, "window.WIZ_global_data?.SNlM0e || ''"
                ) if signed_in_email else ""
                if snlm0e:
                    logger.info(
                        f"Token Factory: auto sign-in succeeded "
                        f"(SNlM0e {len(snlm0e)} chars)"
                    )
                    # Save fresh cookies to auth state on disk
                    try:
                        cookies_list = get_page_cookies(ws)
                        cookies = _filter_gemini_cookies(cookies_list)
                        if cookies.get("__Secure-1PSID"):
                            from .auth import AuthManager
                            from .profiles import ProfileManager

                            pm = ProfileManager()
                            am = AuthManager(
                                profile_manager=pm,
                                profile_name=self._profile_name,
                            )
                            am.load()
                            am.state.cookies = cookies
                            am.state.tokens.snlm0e = snlm0e
                            am.state.last_refreshed = time.time()
                            am.save()
                            logger.debug(
                                "Token Factory: saved fresh auth state to disk"
                            )
                    except Exception as e:
                        logger.debug(f"Token Factory: save auth state failed: {e}")
                    return snlm0e
                # Page loaded but no SNlM0e yet — keep waiting
                continue

            # Google account chooser — auto-select first account
            if "accounts.google.com" in url:
                try:
                    page_text = (
                        run_js(ws, "document.body.innerText.substring(0, 500)")
                        or ""
                    )
                except Exception:
                    page_text = ""

                if "password" in page_text.lower():
                    logger.warning(
                        "Token Factory: auto sign-in hit password page — "
                        "can't auto-complete"
                    )
                    return None

                # Google identifier page — headless profiles may have auth
                # cookies on disk but no browser-level saved account chooser.
                if auth_email:
                    submitted_email = run_js(ws, f"""
                        (() => {{
                            const input = document.querySelector('input[type="email"]')
                                || document.querySelector('input#identifierId')
                                || document.querySelector('input[name="identifier"]');
                            if (!input) return false;

                            input.focus();
                            input.value = {auth_email!r};
                            input.dispatchEvent(new Event('input', {{ bubbles: true }}));
                            input.dispatchEvent(new Event('change', {{ bubbles: true }}));

                            const buttons = Array.from(document.querySelectorAll(
                                'button, div[role="button"]'
                            ));
                            const next = buttons.find((el) =>
                                el.textContent.trim().toLowerCase() === 'next'
                            ) || document.querySelector('#identifierNext button')
                              || document.querySelector('#identifierNext');
                            if (!next) return false;
                            next.click();
                            return true;
                        }})()
                    """)
                    if submitted_email:
                        logger.debug(
                            "Token Factory: submitted saved email on "
                            "Google identifier page"
                        )
                        continue

                # Try clicking the first account in the chooser
                run_js(ws, """
                    (() => {
                        const selectors = [
                            '[data-identifier]',
                            '[data-email]',
                            'li[data-authuser]',
                            'div[data-authuser]',
                        ];
                        for (const sel of selectors) {
                            const el = document.querySelector(sel);
                            if (el) { el.click(); return; }
                        }
                    })()
                """)
                continue

        logger.warning("Token Factory: auto sign-in timed out")
        return None

    def _load_auth_state(self):
        """Load saved auth state for the active Token Factory profile."""
        try:
            from .auth import AuthManager
            from .profiles import ProfileManager

            pm = ProfileManager()
            am = AuthManager(profile_manager=pm, profile_name=self._profile_name)
            return am.load()
        except Exception as e:
            logger.debug(f"Token Factory: could not load auth state: {e}")
            return None

    def _load_auth_email(self) -> str:
        """Load the saved profile email for Google identifier-page sign-in."""
        state = self._load_auth_state()
        return state.email.strip() if state else ""

    def _activate_tool(self, tool_id: int) -> str:
        """Activate a tool (Images/Videos/Music) in Chrome's Gemini UI.

        Opens the Tools drawer and clicks the corresponding tool toggle.
        This ensures Chrome's BotGuard-signed request body includes the
        tool activation, making generation deterministic.

        Args:
            tool_id: Tool ID (14=Images, 11=Videos, 21=Music)

        Returns:
            Raw activation result: 'activated', 'already_active', 'disabled'
            (usage limit), 'not_found', 'no_drawer', or 'error'.
        """
        aliases = TOOL_ID_UI_ALIASES.get(tool_id)
        if not aliases:
            logger.debug(f"Token Factory: unknown tool_id {tool_id}, skipping activation")
            return "unsupported"

        js = ACTIVATE_TOOL_JS.format(tool_names_json=json.dumps(list(aliases)))
        result = run_js(self._ws_url, js) or "error"

        if result in ("activated", "already_active"):
            logger.debug(f"Token Factory: tool '{aliases[0]}' {result}")
            # Give the UI a moment to update placeholder/state
            if result == "activated":
                time.sleep(0.5)
            return result

        if result == "disabled":
            logger.warning(
                f"Token Factory: tool '{aliases[0]}' is disabled for this account "
                "(usage limit reached)"
            )
        else:
            logger.warning(
                f"Token Factory: failed to activate tool '{aliases[0]}' "
                f"(result: {result})"
            )
        return result

    def _set_template(self, template_name: str) -> bool:
        """Select a template card on a Create videos / Create music page.

        Templates prefill the style (the captured body carries a template
        descriptor at inner[0][9]); a custom prompt and options still apply.

        Best effort — returns False when the card is not found (the generation
        then proceeds as a regular prompt).
        """
        name = (template_name or "").strip()
        if not name:
            return False

        # Escape single quotes so the name can be embedded in the JS call
        escaped = name.replace("\\", "\\\\").replace("'", "\\'")
        js = SELECT_TEMPLATE_JS.replace("{template_name}", escaped)
        result = run_js(self._ws_url, js)

        if result in ("selected", "clicked"):
            logger.debug(f"Token Factory: template '{name}' {result}")
            time.sleep(0.5)
            return True

        logger.warning(
            f"Token Factory: template '{name}' not found "
            f"(result: {result})"
        )
        return False

    def _set_aspect_ratio(self, label: str) -> bool:
        """Pick an aspect-ratio option in Chrome's composer dropdown.

        Used for both video orientation ("Landscape (16:9)") and image aspect
        ("1:1", "16:9", ...). Chrome encodes the pick in inner[55] and
        inner[0][9]; driving the UI keeps the signed body consistent.
        """
        if not label:
            return False
        js = SELECT_COMPANION_OPTION_JS.format(
            mode="aspect", control="Aspect ratio", label=label
        )
        result = run_js(self._ws_url, js)
        if result in ("selected", "already_active"):
            logger.debug(f"Token Factory: aspect ratio '{label}' {result}")
            time.sleep(0.3)
            return True
        logger.warning(
            f"Token Factory: failed to set aspect ratio '{label}' (result: {result})"
        )
        return False

    def _set_music_option(self, control: str, label: str) -> bool:
        """Pick a Length/Vocals/Genre option in Chrome's music composer.

        Chrome encodes music picks in inner[55] and inner[0][9].
        """
        if not label:
            return False
        js = SELECT_COMPANION_OPTION_JS.format(
            mode="named", control=control, label=label
        )
        result = run_js(self._ws_url, js)
        if result in ("selected", "already_active"):
            logger.debug(f"Token Factory: music {control}='{label}' {result}")
            time.sleep(0.3)
            return True
        logger.warning(
            f"Token Factory: failed to set music {control}='{label}' "
            f"(result: {result})"
        )
        return False

    def _set_model_picker(self, model) -> bool:
        """Select the requested model in Chrome's Gemini mode picker.

        Chat requests mirror the same picker: inner[79] is the model category
        and inner[80] is the thinking level (Low=1, Medium=4, High=2). The
        base model is matched by hash via data-test-id. Thinking level is the
        Low / Medium / High submenu.

        Best effort — returns False on failure and lets capture() continue,
        since the model header override still applies.
        """
        if not getattr(model, "hash", None):
            return False

        js = SET_MODEL_PICKER_JS.replace("{hash}", model.hash).replace(
            "{level}", model.thinking_label
        )
        result = run_js(self._ws_url, js)

        if result == "set":
            logger.debug(f"Token Factory: model picker set to {model.name}")
            time.sleep(0.3)
            return True

        logger.warning(
            f"Token Factory: failed to set model picker to {model.name} "
            f"(result: {result})"
        )
        return False

    def _set_composer_mode(self, task: bool) -> bool:
        """Select Chat or Task on the segmented control under the prompt.

        Task is required: a missing control must not silently send a chat.
        Chat is best effort so an account that has not received the toggle
        still sends.
        """
        want = "Task" if task else "Chat"
        result = run_js(self._ws_url, SET_COMPOSER_MODE_JS.replace("{mode}", want))
        if result in ("set", "already"):
            logger.debug(f"Token Factory: composer mode {want} {result}")
            time.sleep(0.2)
            return True
        if task:
            raise TokenFactoryError(
                "Could not select Task in Gemini. The Chat/Task control was "
                "not on the page. Reload gemini.google.com in the GemCLI "
                "Chrome window and try again."
            )
        logger.debug(f"Token Factory: Chat control not found ({result})")
        return False

    def _deactivate_tool(self) -> None:
        """Deactivate any active tool in Chrome's Gemini UI."""
        try:
            run_js(self._ws_url, DEACTIVATE_TOOL_JS)
        except Exception:
            pass  # Non-fatal

    def capture(
        self,
        prompt: str,
        model,
        metadata=None,
        tool_id: int | None = None,
        video_orientation: str | None = None,
        template: str | None = None,
        image_aspect: str | None = None,
        music_length: str | None = None,
        music_vocals: str | None = None,
        music_genre: str | None = None,
        task: bool = False,
    ) -> CapturedRequest:
        """Capture a BotGuard token while holding the profile lock.

        See _capture_locked() for arguments. Callers on the same profile (other
        CLI runs, parallel MCP calls) wait; they would otherwise overwrite this
        capture's prompt, tool state and token in the shared Gemini tab.
        """
        self._cancel_idle_timer()
        with profile_lock(self._profile_name):
            return self._capture_locked(
                prompt, model, metadata=metadata, tool_id=tool_id,
                video_orientation=video_orientation, template=template,
                image_aspect=image_aspect, music_length=music_length,
                music_vocals=music_vocals, music_genre=music_genre,
                task=task,
            )

    def _capture_locked(
        self,
        prompt: str,
        model,
        metadata=None,
        tool_id: int | None = None,
        video_orientation: str | None = None,
        template: str | None = None,
        image_aspect: str | None = None,
        music_length: str | None = None,
        music_vocals: str | None = None,
        music_genre: str | None = None,
        task: bool = False,
    ) -> CapturedRequest:
        """Capture a BotGuard token by triggering a request in Chrome.

        Args:
            prompt: The message to send
            model: Model object with .name and .header attributes
            metadata: ConversationMetadata for multi-turn (has .cid for conversation ID)
            tool_id: Tool activation ID (11=Videos, 14=Images, 21=Music)
            video_orientation: For the Videos tool, "landscape" (16:9) or
                "portrait" (9:16). Drives Chrome's aspect-ratio control so the
                signed body carries the requested Omni video orientation.
            template: Optional template name (video or music). Clicks the
                template card on the Create videos / Create music page.
            image_aspect: For the Images tool, an aspect label ("1:1", "9:16",
                "3:4", "4:3", "16:9"). Drives Chrome's aspect-ratio control.
            music_length: For the Music tool, the UI length label ("Short" /
                "Standard") from MUSIC_LENGTHS.
            music_vocals: For the Music tool, the UI vocals label from MUSIC_VOCALS.
            music_genre: For the Music tool, the UI genre label(s) from
                normalize_music_genre().

        Returns:
            CapturedRequest with URL, body, headers, and cookies for Python replay.
        """
        self._ensure_ready_locked()

        # Force a full page reload every N generations to refresh stale SNlM0e tokens.
        self._generation_count += 1
        if self._generation_count % _GENERATIONS_BEFORE_REFRESH == 0:
            logger.debug(
                f"Token Factory: generation {self._generation_count}, "
                f"forcing page reload for fresh SNlM0e"
            )
            navigate_to_url(self._ws_url, GEMINI_APP_URL)
            if not self._wait_for_input():
                raise TokenFactoryError("Gemini page failed to load after periodic token refresh.")
            signed_in = run_js(self._ws_url, "window.WIZ_global_data?.oPEP7c || ''")
            if not signed_in:
                raise AuthError(
                    "Token Factory: SNlM0e missing after page refresh — "
                    "session expired. Run 'gemcli login' to refresh."
                )

        # Navigate to the right conversation
        target_url = GEMINI_APP_URL
        if metadata and metadata.cid:
            # Response cids are "c_<hex>"; the web app's URL is /app/<hex>.
            # With the prefix Chrome opens a blank chat and the follow-up
            # starts a new conversation.
            target_url = f"{GEMINI_APP_URL}/{metadata.cid.removeprefix('c_')}"

        # Always verify Chrome is on the target page. Re-navigate if needed.
        # This handles the race condition where a previous capture() left
        # Chrome mid-navigation (Bug 3: parallel image gen race).
        current = get_current_url(self._ws_url)
        if target_url not in current or "gemini.google.com" not in current:
            navigate_to_url(self._ws_url, target_url)
            if not self._wait_for_input():
                raise TokenFactoryError("Gemini page failed to load after navigation.")
        else:
            # Even if on the right URL, ensure the input field is ready
            if not self._wait_for_input(timeout=5):
                # Page may be in a bad state from aborted XHR — re-navigate
                navigate_to_url(self._ws_url, target_url)
                if not self._wait_for_input():
                    raise TokenFactoryError("Gemini page failed to load after navigation.")

        # Activate the requested tool (Images/Videos/Music) in Chrome's UI
        # BEFORE typing the prompt. This ensures the BotGuard-signed request
        # body includes the tool activation data.
        #
        # A disabled tool means the account hit its usage limit for that
        # feature. Sending the prompt anyway would silently produce a chat or
        # image response instead of the requested media, so fail fast.
        tool_activated = False
        if tool_id and tool_id in TOOL_ID_UI_ALIASES:
            tool_name = TOOL_ID_TO_NAME.get(tool_id, str(tool_id))
            tool_result = self._activate_tool(tool_id)
            if tool_result not in ("activated", "already_active", "disabled"):
                # The page may still be settling after the navigation above;
                # reload it and retry activation once before giving up.
                logger.warning(
                    f"Token Factory: retrying '{tool_name}' activation "
                    f"after page reload (result: {tool_result})"
                )
                navigate_to_url(self._ws_url, target_url)
                if self._wait_for_input():
                    tool_result = self._activate_tool(tool_id)

            if tool_result in ("activated", "already_active"):
                tool_activated = tool_result == "activated"
            elif tool_result == "disabled":
                # UsageLimitExceeded deliberately does NOT subclass
                # TokenFactoryError — the client must surface it instead of
                # falling back to a direct HTTP request that cannot work.
                raise UsageLimitExceeded(
                    f"The {tool_name} tool is disabled — Gemini usage limit "
                    "reached for this profile. Try another profile with "
                    "'-p <profile>' or wait for the quota to reset."
                )
            else:
                # Sending the request without the tool would silently produce a
                # chat or image response instead of the requested media.
                raise ToolActivationError(
                    f"Could not activate the {tool_name} tool in Gemini "
                    f"(result: {tool_result}). Open gemini.google.com in the "
                    "GemCLI Chrome window to check the tool is available, "
                    "or try again."
                )

        # Media options: drive the composer's template / aspect-ratio / music
        # controls so the captured body matches the requested options. The
        # model header is still overridden below, but inner[79]/inner[80]
        # mirror the picker, so the UI must agree.
        if tool_id == VIDEO_TOOL_ID:
            if template:
                self._set_template(template)
            if video_orientation:
                self._set_aspect_ratio(VIDEO_ORIENTATION_LABELS[video_orientation])
        elif tool_id == IMAGE_TOOL_ID:
            if image_aspect:
                self._set_aspect_ratio(image_aspect)
        elif tool_id == MUSIC_TOOL_ID:
            if template:
                self._set_template(template)
            if music_length:
                self._set_music_option("Length", music_length)
            if music_vocals:
                self._set_music_option("Vocals", music_vocals)
            if music_genre:
                self._set_music_option("Genre", music_genre)

        if model is not None and getattr(model, "hash", None):
            self._set_model_picker(model)

        # Chat and Task share the composer. Tools (image/video/music) use their
        # own pages, which do not have the segmented control.
        if tool_id is None:
            self._set_composer_mode(task)

        # Install XHR interceptor (resets window.__cap = null as its first statement)
        run_js(self._ws_url, XHR_INTERCEPTOR_JS)

        # Type the prompt via DOM (long/complex text is unreliable as keystrokes)
        # and click Send so Chrome builds a BotGuard-signed request. The typed
        # text only triggers the capture; Python puts the real prompt into the
        # request (issue #2). Newlines are flattened because typing one into
        # Gemini's editor cut the captured prompt off at that line.
        typed = " ".join(prompt.split())
        escaped_prompt = typed.replace("\\", "\\\\").replace("`", "\\`").replace("$", "\\$")
        run_js(self._ws_url, TYPE_PROMPT_JS.format(prompt=escaped_prompt))
        time.sleep(0.5)
        run_js(self._ws_url, CLICK_SEND_JS)

        # Poll for captured request
        captured = self._poll_capture()
        if not captured:
            self._raise_if_prompt_escaped(target_url)
            # Retry once: navigate fresh, re-install hook
            logger.debug("Token Factory: first capture failed, retrying...")
            navigate_to_url(self._ws_url, target_url)
            if not self._wait_for_input():
                raise TokenFactoryError("Gemini page failed to load on retry.")
            run_js(self._ws_url, XHR_INTERCEPTOR_JS)
            run_js(self._ws_url, TYPE_PROMPT_JS.format(prompt=escaped_prompt))
            time.sleep(0.5)
            run_js(self._ws_url, CLICK_SEND_JS)
            captured = self._poll_capture()
            if not captured:
                self._raise_if_prompt_escaped(target_url)
                raise TokenFactoryError(
                    "Failed to capture BotGuard token after retry. "
                    "Chrome may not be on gemini.google.com."
                )

        transport = captured.get("transport") or TRANSPORT_STREAMGENERATE
        if transport == TRANSPORT_PROCESS_SESSION:
            url = captured["url"]  # absolute channel-open URL
        else:
            url = urljoin(GEMINI_APP_URL, captured["url"])
        logger.debug(f"Token Factory: captured {transport} request")

        # Get JS-set headers (model header, tracking headers, etc.)
        js_headers = captured.get("headers", {})

        # Build complete Chrome-like headers
        headers = dict(CHROME_HEADERS)
        headers["x-browser-validation"] = compute_xbv(CHROME_USER_AGENT)
        headers.update(js_headers)

        # Keep Chrome's captured model header and rewrite the hash, category,
        # and thinking level in place. The live header continues past that pair.
        if model and getattr(model, "hash", None):
            replaced = False
            for key, value in list(headers.items()):
                if key.lower() == MODEL_HEADER_KEY and isinstance(value, str):
                    headers[key] = rewrite_captured_model_header(value, model)
                    replaced = True
            if not replaced and model.header:
                headers.update(model.header)

        # Grab ALL cookies from the browser
        cookies = self._get_google_cookies()

        # Extract the live SNlM0e access token from Chrome's window global.
        # This is the correct 'at=' token for the current Chrome session, which
        # must be used when replaying batchexecute calls with Chrome's cookies.
        # Mismatching Python's cached token with Chrome's cookies causes silent
        # empty responses (0 candidates). Retry up to 5s since WIZ_global_data
        # is populated by Gemini's JS bootstrap after page load.
        chrome_access_token: str | None = None
        for attempt in range(10):
            try:
                chrome_access_token = run_js(
                    self._ws_url,
                    "window.WIZ_global_data && window.WIZ_global_data.SNlM0e",
                )
                if chrome_access_token:
                    logger.debug(
                        f"Token Factory: captured Chrome SNlM0e "
                        f"(attempt {attempt + 1}, "
                        f"{len(chrome_access_token)} chars)"
                    )
                    break
            except Exception:
                pass
            time.sleep(0.5)

        # Fallback: extract SNlM0e from page HTML source.
        # The token is server-rendered in the HTML even if JS globals
        # haven't populated yet (same technique used by auth.py).
        if not chrome_access_token:
            try:
                import re

                from .cdp import get_page_html
                from .constants import TOKEN_PATTERNS

                html = get_page_html(self._ws_url)
                match = re.search(TOKEN_PATTERNS["snlm0e"], html)
                if match:
                    chrome_access_token = match.group(1)
                    logger.debug(
                        f"Token Factory: extracted SNlM0e from "
                        f"page HTML ({len(chrome_access_token)} chars)"
                    )
            except Exception as e:
                logger.debug(f"Token Factory: HTML SNlM0e extraction failed: {e}")

        if not chrome_access_token:
            raise AuthError(
                "Token Factory: SNlM0e not found — session expired.\n"
                "Run 'gemcli login' to refresh credentials."
            )

        # Deactivate any tool we enabled so Chrome returns to default state
        if tool_activated:
            self._deactivate_tool()
            time.sleep(1)  # Match activation's 0.5s settle — deactivation can be slower

        # Navigate back to /app to leave Chrome in a clean state for next capture
        # (the aborted XHR may leave the page in a weird state)
        navigate_to_url(self._ws_url, GEMINI_APP_URL)

        self._reset_idle_timer()

        return CapturedRequest(
            url=url,
            body=captured["body"],
            headers=headers,
            cookies=cookies,
            access_token=chrome_access_token,
            transport=transport,
        )

    def shutdown(self) -> None:
        """Clean up Chrome and resources.

        Other processes may be using the Chrome this factory launched (they
        find it through the port map), so closing it waits for the profile
        lock. If the lock stays busy, Chrome is left running for them.
        """
        self._cancel_idle_timer()
        if self._process and self._we_launched:
            try:
                with profile_lock(self._profile_name, timeout=_SHUTDOWN_LOCK_WAIT):
                    self._shutdown_locked()
                return
            except GeminiError:
                logger.info(
                    "Token Factory: profile busy in another process — leaving "
                    f"Chrome on port {self._port} running for it"
                )
                # Hand it over: keep its port map entry and lock files.
                self._process = None
                self._we_launched = False
        self._shutdown_locked()

    def _shutdown_locked(self) -> None:
        if self._process and self._we_launched:
            # Browser.close lets Chrome flush renewed cookies to disk before
            # exiting; this Chrome runs on the user's real profile.
            try:
                browser_ws = get_debugger_url(self._port) if self._port else None
                if browser_ws:
                    execute_cdp_command(browser_ws, "Browser.close")
                    self._process.wait(timeout=10)
            except Exception:
                pass
            try:
                self._process.terminate()
                self._process.wait(timeout=5)
            except Exception:
                try:
                    self._process.kill()
                except Exception:
                    pass
            self._process = None
            # Clean up port map entry we registered
            if self._port:
                _clear_port_map(self._port)
        # Clean up lock files only if we launched Chrome on this profile
        lock_dir = (
            Path(self._chrome_profile_path)
            if self._chrome_profile_path and self._we_launched else None
        )
        if lock_dir:
            _clean_lock_files(lock_dir)
        self._ready = False
        self._ws_url = None
        self._port = None
        self._we_launched = False
        logger.debug("Token Factory: shutdown")

    @staticmethod
    def _kill_stale_chrome(profile_dir: Path) -> None:
        """Kill ALL Chrome processes using the given profile directory."""
        try:
            result = subprocess.run(
                ["pgrep", "-f", "--", _user_data_dir_pgrep_pattern(profile_dir)],
                capture_output=True, text=True, timeout=5,
            )
            pids = [
                int(p) for p in result.stdout.strip().split("\n") if p.strip()
            ]
            for pid in pids:
                try:
                    os.kill(pid, signal.SIGTERM)
                    logger.debug(f"Token Factory: killing Chrome PID {pid}")
                except OSError:
                    pass
            if pids:
                # Wait for graceful exit (up to 5s), then SIGKILL survivors
                for _ in range(10):
                    alive = []
                    for pid in pids:
                        try:
                            os.kill(pid, 0)  # probe — raises OSError if dead
                            alive.append(pid)
                        except OSError:
                            pass
                    if not alive:
                        break
                    time.sleep(0.5)
                else:
                    for pid in alive:
                        try:
                            os.kill(pid, signal.SIGKILL)
                            logger.debug(
                                f"Token Factory: force-killed Chrome PID {pid}"
                            )
                        except OSError:
                            pass
                    time.sleep(1)
        except Exception as e:
            logger.debug(f"Token Factory: stale Chrome check skipped: {e}")
        # Remove all stale lock files regardless
        _clean_lock_files(profile_dir)

    def _wait_for_input(self, timeout: int = 20) -> bool:
        """Wait for Gemini's input field to appear."""
        for _ in range(timeout):
            if run_js(self._ws_url, INPUT_READY_JS):
                return True
            time.sleep(1)
        return False

    def _poll_capture(self, timeout: int = 20) -> dict | None:
        """Poll window.__cap for a captured request."""
        for _ in range(timeout):
            time.sleep(1)
            result = run_js(self._ws_url, "window.__cap")
            if not result:
                continue
            if result.get("transport") == TRANSPORT_PROCESS_SESSION and not result.get("url"):
                # The channel was opened before the hook was installed, so its
                # auth/model URL is unknown. The data POST was aborted; a fresh
                # page (the caller's retry) opens a new channel.
                logger.debug("Token Factory: processSession data captured without open URL")
                return None
            return result
        return None

    def _raise_if_prompt_escaped(self, target_url: str) -> None:
        """Stop if Chrome sent the prompt through a request the hook missed.

        A new chat that got sent moves the tab from /app to /app/<cid>. Retrying
        would send the prompt again (issue: duplicate conversations and quota).
        Only detectable for new chats; follow-ups are already on /app/<cid>.
        """
        if target_url != GEMINI_APP_URL:
            return
        try:
            current = get_current_url(self._ws_url)
        except Exception:
            return
        path = current.split("gemini.google.com", 1)[-1].split("?", 1)[0].rstrip("/")
        if path.startswith("/app/") and len(path) > len("/app/"):
            navigate_to_url(self._ws_url, GEMINI_APP_URL)
            raise PromptEscaped(
                "Chrome sent the prompt through a Gemini request that Token Factory "
                "does not recognise, so it was not captured. Not retrying (that would "
                "send it again). Gemini may have changed its chat transport for this "
                f"account; run 'gemcli -p {self._profile_name} doctor --deep'."
            )

    def get_raw_cookies(self) -> list[dict]:
        """Get the raw CDP cookie list (with domain/path info) from the last capture."""
        return self._raw_cookies

    def _get_google_cookies(self) -> dict[str, str]:
        """Get all Google/Gemini cookies from the browser."""
        all_cookies = get_page_cookies(self._ws_url)
        # Store raw cookies with domain info for cross-domain downloads
        self._raw_cookies = all_cookies
        cookies = {}
        for c in all_cookies:
            domain = c.get("domain", "")
            if "google.com" in domain or "gemini.google.com" in domain:
                cookies[c["name"]] = c["value"]
        return cookies
