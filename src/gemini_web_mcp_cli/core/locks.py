"""Per-profile browser lock shared by every gemcli process.

Token Factory drives a single Gemini tab: it types the prompt, toggles tools,
and reads the intercepted request from ``window.__cap``. Two callers using the
same profile at once overwrite each other's prompt and token, and one caller
can close Chrome while another is mid-capture. Every step that drives or
stops a profile's Chrome holds this lock, so parallel CLI runs and MCP calls
queue instead.

The lock is an ``fcntl.flock`` on ``~/.gemini-web-mcp-cli/locks/<profile>.lock``.
flock locks belong to the open file, so threads in one process exclude each
other as well as separate processes. Nested use on the same thread is
reentrant (capture() calls ensure_ready(), which also locks).
"""

from __future__ import annotations

import fcntl
import os
import threading
import time
from contextlib import contextmanager
from pathlib import Path

from loguru import logger

from .constants import CONFIG_DIR_NAME
from .exceptions import GeminiError

# How long a caller waits for another capture on the same profile to finish.
# Override with GEMCLI_PROFILE_LOCK_TIMEOUT (seconds).
_DEFAULT_TIMEOUT = 300.0

_held = threading.local()


class ProfileBusy(GeminiError):
    """The profile's Chrome stayed busy with another request past the timeout.

    Not a TokenFactoryError: the client must surface it, not fall back to
    plain HTTP.
    """


def _lock_path(profile_name: str) -> Path:
    safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in profile_name)
    return Path.home() / CONFIG_DIR_NAME / "locks" / f"{safe or 'default'}.lock"


def lock_timeout() -> float:
    try:
        return float(os.environ.get("GEMCLI_PROFILE_LOCK_TIMEOUT", _DEFAULT_TIMEOUT))
    except ValueError:
        return _DEFAULT_TIMEOUT


@contextmanager
def profile_lock(profile_name: str, timeout: float | None = None):
    """Hold the profile's browser lock, waiting up to ``timeout`` seconds.

    ``timeout=0`` tries once. Raises ProfileBusy if the lock is not acquired.
    """
    depth = getattr(_held, "depth", None)
    if depth is None:
        depth = _held.depth = {}
    if depth.get(profile_name):
        depth[profile_name] += 1
        try:
            yield
        finally:
            depth[profile_name] -= 1
        return

    timeout = lock_timeout() if timeout is None else timeout
    path = _lock_path(profile_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    fh = path.open("a")
    deadline = time.monotonic() + timeout
    waited = False
    try:
        while True:
            try:
                fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise ProfileBusy(
                        f"Profile '{profile_name}' is busy with another request "
                        f"(waited {timeout:.0f}s). Retry, use another profile with "
                        "'-p <profile>', or raise GEMCLI_PROFILE_LOCK_TIMEOUT."
                    ) from None
                if not waited:
                    logger.info(f"Profile '{profile_name}' is busy — waiting for it")
                    waited = True
                time.sleep(0.25)
        depth[profile_name] = 1
        try:
            yield
        finally:
            depth[profile_name] = 0
            fcntl.flock(fh, fcntl.LOCK_UN)
    finally:
        fh.close()
