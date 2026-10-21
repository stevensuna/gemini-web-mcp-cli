"""End-to-end probes of the paths a profile actually depends on (issue #5).

"Signed in" and "saved cookies present" do not prove that uploads, images,
video, music or Pro work: those all need a BotGuard token captured by Token
Factory. These probes exercise that path directly.

The token probe is free: Token Factory's XHR interceptor aborts the request
inside Chrome, so the probe prompt never reaches Gemini and uses no quota. It
also reports which chat transport the account uses (StreamGenerate or
processSession; see docs/research/transport/processSession.md).
The upload probe pushes a few bytes to Google's upload endpoint without
attaching them to any chat.
"""

from __future__ import annotations

import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from loguru import logger

from .locks import profile_lock

PROBE_PROMPT = "[gemcli health probe]"


@dataclass
class ProbeResult:
    """Outcome of one probe. ``detail`` names the failing stage on failure."""

    name: str
    ok: bool
    detail: str = ""
    duration: float = 0.0
    transport: str = ""  # token capture only: "streamgenerate" or "processSession"

    def summary(self) -> str:
        return "ok" if self.ok else f"failed: {self.detail}"


def probe_token_capture(
    profile_name: str,
    chrome_profile_path: str | None,
    lock_timeout: float | None = None,
) -> ProbeResult:
    """Capture a BotGuard token for the profile without sending anything.

    Raises nothing; failures are reported in the result. ``ProfileBusy`` is
    reported as a failure with detail "busy" so callers can treat it as skipped.
    """
    from .client import GeminiClient
    from .constants import MODELS
    from .exceptions import GeminiError
    from .locks import ProfileBusy
    from .token_factory import TokenFactory

    start = time.time()

    def result(ok: bool, detail: str = "") -> ProbeResult:
        return ProbeResult("token_capture", ok, detail, round(time.time() - start, 1))

    if not chrome_profile_path:
        return result(False, "no Chrome profile — run `gemcli login`")

    factory = TokenFactory(chrome_profile_path=chrome_profile_path, profile_name=profile_name)
    try:
        with profile_lock(profile_name, timeout=lock_timeout):
            captured = factory.capture(PROBE_PROMPT, MODELS["fast"])
        token, _ = GeminiClient._extract_botguard(captured.body)
        if not token:
            return result(False, "capture: request captured without a BotGuard token")
        if not captured.access_token:
            return result(False, "capture: no SNlM0e access token in Chrome")
        ok = result(True)
        ok.transport = captured.transport
        return ok
    except ProfileBusy:
        return result(False, "busy")
    except GeminiError as e:
        return result(False, f"{type(e).__name__}: {e}".splitlines()[0])
    except Exception as e:  # CDP/websocket failures surface as plain exceptions
        logger.debug(f"probe_token_capture({profile_name}) failed: {e!r}")
        return result(False, f"{type(e).__name__}: {e}".splitlines()[0])
    finally:
        factory.shutdown()


async def probe_upload(profile_name: str) -> ProbeResult:
    """Upload a tiny text file with the profile's cookies (not attached to a chat)."""
    from .client import GeminiClient

    start = time.time()
    client = GeminiClient(profile_name=profile_name)
    try:
        from gemini_web_mcp_cli.services.file import FileService

        await client.init()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "gemcli-probe.txt"
            path.write_text("gemcli upload probe\n", encoding="utf-8")
            file_id = await FileService(client).upload(path)
        ok = bool(file_id)
        detail = "" if ok else "upload returned no file id"
        return ProbeResult("upload", ok, detail, round(time.time() - start, 1))
    except Exception as e:
        return ProbeResult(
            "upload", False, f"{type(e).__name__}: {e}".splitlines()[0],
            round(time.time() - start, 1),
        )
    finally:
        await client.close()
