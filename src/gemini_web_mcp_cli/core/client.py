"""GeminiClient: the main entry point that composes all core components.

Usage:
    client = GeminiClient(profile_name="default")
    await client.init()
    response = await client.send("Hello!")
    print(response.text)
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path

import httpx
from loguru import logger

from . import webchannel
from .auth import AuthManager
from .constants import (
    CHROME_USER_AGENT,
    DEFAULT_MODEL,
    GEMINI_HEADERS,
    MODELS,
    TOKEN_FACTORY_MODELS,
    Model,
    get_model,
)
from .exceptions import APIError, AuthError, GeminiError, GeminiReplyError, TokenFactoryError
from .models import BatchResult, ConversationMetadata, RPCPayload, StreamResponse
from .profiles import ProfileManager
from .rpc import RPCTransport, build_process_session_response, build_stream_response
from .webchannel import TRANSPORT_PROCESS_SESSION

# Gemini's generic failure replies (a server-side error rendered as text).
# Only short replies that start with one are treated as errors, so answers that
# merely discuss errors pass through.
_ERROR_REPLY = re.compile(
    r"^\s*(?:I seem to be encountering an error|I'm encountering an error"
    r"|Something went wrong)\b",
    re.IGNORECASE,
)
_ERROR_REPLY_MAX_CHARS = 200


def _check_reply(response: StreamResponse) -> StreamResponse:
    """Raise GeminiReplyError when Gemini returned its generic failure text."""
    if not isinstance(response, StreamResponse):
        return response
    text = (response.text or "").strip()
    has_media = response.has_images or response.has_video or response.has_music
    if (text and not has_media and len(text) <= _ERROR_REPLY_MAX_CHARS
            and _ERROR_REPLY.match(text)):
        raise GeminiReplyError(
            f"Gemini returned an error instead of an answer: {text!r}. "
            "Usually temporary; retry, or use another profile.",
            reply=text,
        )
    return response


class GeminiClient:
    """High-level client that composes AuthManager, RPCTransport, and ProfileManager.

    Handles initialization, authentication, and provides simple methods for
    chat, batchexecute, and other operations.
    """

    def __init__(
        self,
        profile_name: str | None = None,
        proxy: str | None = None,
        timeout: float = 300.0,
    ):
        self.profile_manager = ProfileManager()
        self.auth_manager = AuthManager(
            profile_manager=self.profile_manager,
            profile_name=profile_name,
            proxy=proxy,
        )
        self.proxy = proxy
        self.timeout = timeout
        self._http_client: httpx.AsyncClient | None = None
        self._transport: RPCTransport | None = None
        self._token_factory = None  # Lazy-initialized TokenFactory
        self._browser_http_client: httpx.AsyncClient | None = None
        self._browser_cookies: dict[str, str] | None = None  # Full cookies from Token Factory
        self._raw_browser_cookies: list[dict] = []  # Raw CDP cookies with domain info
        self._browser_access_token: str | None = None  # Chrome's live SNlM0e (from WIZ_global_data)
        self._initialized = False

    @property
    def transport(self) -> RPCTransport:
        if not self._transport:
            raise AuthError("Client not initialized. Call init() first.")
        return self._transport

    async def init(self) -> None:
        """Initialize the client: load auth, create HTTP client, set up transport."""
        # Load auth state from profile
        auth_state = self.auth_manager.load()

        if not auth_state.is_valid:
            # If no Python tokens but Chrome profile exists, we can still
            # operate via Token Factory (Chrome handles auth directly).
            if auth_state.chrome_profile_path:
                logger.info(
                    "No Python auth tokens available, but Chrome profile found. "
                    "Operating in Token Factory-only mode."
                )
            else:
                raise AuthError(
                    "No valid authentication found. Run `gemcli login` first."
                )

        # Refresh tokens to ensure they're current (skip if no tokens to refresh)
        if auth_state.is_valid:
            try:
                await self.auth_manager.refresh_tokens()
            except AuthError:
                logger.debug("Token refresh failed, attempting recovery...")
                try:
                    await self.auth_manager.recover()
                except AuthError:
                    logger.warning(
                        "Token recovery failed. Using cached tokens — "
                        "some features may not work."
                    )

        auth_state = self.auth_manager.state

        # Create HTTP client (may have empty cookies in TF-only mode)
        self._http_client = httpx.AsyncClient(
            http2=True,
            timeout=self.timeout,
            proxy=self.proxy,
            follow_redirects=True,
            headers=GEMINI_HEADERS,
            cookies=auth_state.cookies,
        )

        # Create transport (may have empty tokens in TF-only mode)
        self._transport = RPCTransport(
            client=self._http_client,
            access_token=auth_state.tokens.snlm0e,
            build_label=auth_state.tokens.cfb2h,
            session_id=auth_state.tokens.fdrfje,
        )

        # Pre-populate browser cookies from auth state so that RPC calls
        # (like limits, gems) work immediately without needing a Chrome
        # session. The cookies from gemcli login are the same CDP-extracted
        # browser cookies that execute_rpc_with_browser_cookies needs.
        if auth_state.cookies:
            self._browser_cookies = dict(auth_state.cookies)
            logger.debug(
                f"Pre-populated {len(auth_state.cookies)} browser cookies "
                f"from auth state"
            )

        self._initialized = True
        logger.info("GeminiClient initialized.")

    async def close(self) -> None:
        """Close the HTTP client, Token Factory, and clean up."""
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None
        if self._browser_http_client:
            await self._browser_http_client.aclose()
            self._browser_http_client = None
        if self._token_factory:
            self._token_factory.shutdown()
            self._token_factory = None
        self._transport = None
        self._initialized = False

    async def send(
        self,
        prompt: str,
        model: str | Model | None = None,
        metadata: ConversationMetadata | None = None,
        file_data: list | None = None,
        gem_id: str | None = None,
        tool_id: int | None = None,
        style_preset: dict | None = None,
        force_token_factory: bool = False,
        extended_thinking: bool | None = None,
        thinking_level: str | None = None,
        task: bool = False,
        video_orientation: str | None = None,
        template: str | None = None,
        image_aspect: str | None = None,
        music_length: str | None = None,
        music_vocals: str | None = None,
        music_genre: str | None = None,
    ) -> StreamResponse:
        """Send a chat message via StreamGenerate.

        Routes through Token Factory when:
        - Pro/Thinking models are requested (need BotGuard for model header)
        - tool_id is set (music tools need BotGuard token in body)
        - force_token_factory is True (video generation needs BotGuard)

        Args:
            tool_id: Optional tool activation ID for inner_req_list[49].
                     Use VIDEO_TOOL_ID (11) for video, IMAGE_TOOL_ID (14) for
                     image, MUSIC_TOOL_ID (21) for music generation.
            style_preset: Optional music style preset dict (from music_presets.py).
                          Injected into inner[0][9] for remix-style generation.
            force_token_factory: Force Token Factory usage for BotGuard tokens
                                 even when tool_id alone would suffice.
            extended_thinking: Explicitly enable or disable Thinking level
                               High (formerly Extended thinking). ``None``
                               preserves the legacy model behavior, including
                               ``thinking``. ``thinking_level`` wins when set.
            thinking_level: ``low``, ``medium``, or ``high``. Medium is 4 and
                            High is 2 on the model-header tail and inner[80].
            task: Select the Task composer control (formerly Spark) before
                  capture. Chrome's signed body carries the mode.
            video_orientation: For video generation, "landscape" (16:9) or
                               "portrait" (9:16). Drives the Omni video tool's
                               aspect-ratio control in Chrome.
            template: Optional template name (video or music, e.g. "Anime",
                      "Logo reveal", "Soundscape"). Applied through the
                      Create videos / Create music page in Chrome.
            image_aspect: For image generation, an aspect label ("1:1", "16:9",
                          ...). Drives the Images tool's aspect control.
            music_length: For music generation, the UI length label ("Short" /
                          "Standard") from MUSIC_LENGTHS.
            music_vocals: For music generation, the UI vocals label from MUSIC_VOCALS.
            music_genre: For music generation, the UI genre label from
                         normalize_music_genre().
        """
        resolved_model = self._resolve_model(
            model, extended_thinking, thinking_level=thinking_level
        )

        # ALL requests now route through Token Factory.
        # Google requires BotGuard to cryptographically sign request bodies.
        # Python-built bodies always get 0 candidates, even with valid cookies
        # and BotGuard tokens, because the signature is tied to the exact body
        # content Chrome generates. Only Chrome's signed body works.
        #
        # The regular HTTP path is kept as a fallback only if Token Factory
        # is completely unavailable (no Chrome profile configured).
        try:
            response = await self._send_via_token_factory(
                prompt=prompt,
                model=resolved_model,
                metadata=metadata,
                file_data=file_data,
                gem_id=gem_id,
                tool_id=tool_id,
                style_preset=style_preset,
                video_orientation=video_orientation,
                template=template,
                image_aspect=image_aspect,
                music_length=music_length,
                music_vocals=music_vocals,
                music_genre=music_genre,
                task=task,
            )
            return _check_reply(response)
        except Exception as e:
            # Attachments, tools, and Task only work with Chrome's signed body.
            # Without it Gemini answers anyway ("I can't open the file" plus an
            # invented description, issue #6), so fail instead of returning that.
            if isinstance(e, TokenFactoryError) and (file_data or tool_id or task):
                raise TokenFactoryError(
                    f"{e}\nNot retrying without Chrome: attachments, "
                    "image/video/music tools, and Task mode need its BotGuard token."
                ) from e
            # If Token Factory fails (no Chrome profile, Chrome not available),
            # fall back to regular HTTP path as a last resort.
            if isinstance(e, TokenFactoryError):
                logger.warning(
                    f"Token Factory unavailable ({e}), falling back to regular HTTP. "
                    "This may not work if BotGuard is required."
                )
            else:
                raise

        return _check_reply(await self.transport.stream_generate(
            prompt=prompt,
            model=resolved_model,
            metadata=metadata,
            file_data=file_data,
            gem_id=gem_id,
            tool_id=tool_id,
            style_preset=style_preset,
            video_orientation=video_orientation,
            image_aspect=image_aspect,
        ))

    async def execute_rpc(
        self,
        rpc_id: str,
        payload: str = "[]",
        source_path: str = "/app",
    ) -> list[BatchResult]:
        """Execute a single RPC via batchexecute."""
        return await self.transport.batchexecute(
            payloads=[RPCPayload(rpc_id=rpc_id, payload=payload)],
            source_path=source_path,
        )

    async def execute_rpcs(
        self,
        payloads: list[RPCPayload],
        source_path: str = "/app",
    ) -> list[BatchResult]:
        """Execute multiple RPCs in a single batchexecute call."""
        return await self.transport.batchexecute(
            payloads=payloads,
            source_path=source_path,
        )

    async def _ensure_browser_cookies(self, force: bool = False) -> bool:
        """Ensure browser cookies are available by extracting from Chrome via CDP.

        Tries the Chrome daemon first, then falls back to launching Token Factory.
        Does NOT waste an API call — only extracts cookies from an existing session.

        Args:
            force: Ignore cached cookies and re-extract live cookies from Chrome.
                   Used when pre-populated auth.json cookies turn out to be stale.

        Returns:
            True if browser cookies are now available, False otherwise.
        """
        if self._browser_cookies and not force:
            return True

        if force:
            self._browser_cookies = None
            self._raw_browser_cookies = []
            self._browser_access_token = None

        try:
            from .browser_auth import get_browser_auth_status_for_port
            from .cdp import find_existing_gemcli_chrome, run_js
            from .chrome_manager import check_daemon_health, same_chrome_profile_path

            profile_name = self.auth_manager.resolved_profile_name
            expected_email = (self.auth_manager.state.email or "").lower()

            # Helper: extract cookies + access token from Chrome on a given port.
            # Never injects saved cookies into that Chrome (issue #3), and
            # refuses a Chrome signed in to a different account.
            def _extract_from_port(port: int) -> bool:
                status = get_browser_auth_status_for_port(port)
                if not status.is_authenticated:
                    return False
                if expected_email and status.ws_url:
                    chrome_email = (
                        run_js(status.ws_url, "window.WIZ_global_data?.oPEP7c || ''") or ""
                    ).lower()
                    if chrome_email and chrome_email != expected_email:
                        logger.warning(
                            f"Chrome on port {port} is signed in as {chrome_email}, "
                            f"not {expected_email} (profile '{profile_name}') — not using it"
                        )
                        return False
                self._browser_cookies = status.cookies
                self._raw_browser_cookies = status.raw_cookies
                self._browser_access_token = status.access_token
                logger.info(
                    f"Browser cookies extracted from Chrome "
                    f"({len(status.cookies)} cookies)"
                )
                return True

            # Use the Chrome daemon only if it holds THIS profile; otherwise
            # it would return another account's cookies.
            daemon_info, status = check_daemon_health()
            port = None
            daemon_is_ours = bool(
                status == "running" and daemon_info and (
                    daemon_info.profile_name == profile_name
                    or same_chrome_profile_path(
                        daemon_info.chrome_profile_path,
                        self.profile_manager.get_chrome_profile_path(profile_name),
                    )
                )
            )

            if daemon_is_ours:
                port = daemon_info.port
                logger.debug(
                    f"Extracting browser cookies from Chrome daemon on port {port}"
                )
            else:
                # Fall back: this profile's own gemcli Chrome from the port map
                found_port, found_url = find_existing_gemcli_chrome(
                    profile_name=profile_name
                )
                if found_port:
                    port = found_port
                    logger.debug(
                        f"Extracting browser cookies from gemcli Chrome "
                        f"on port {port}"
                    )

            if port and _extract_from_port(port):
                return True

            # Last resort: launch Token Factory to get Chrome running,
            # then extract cookies directly from the page via CDP
            logger.debug(
                "No running Chrome found, launching Token Factory for cookies"
            )
            factory = self._ensure_token_factory()
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, factory.ensure_ready)

            # Token Factory's get_raw_cookies() is only populated after
            # capture(), so we extract cookies directly from Chrome via CDP
            if factory._port and _extract_from_port(factory._port):
                return True

        except Exception as e:
            logger.warning(f"Failed to extract browser cookies: {e}")

        return False

    async def execute_rpc_with_browser_cookies(
        self,
        rpc_id: str,
        payload: str = "[]",
        source_path: str = "/app",
    ) -> list[BatchResult]:
        """Execute a single RPC using full browser cookies.

        Required for RPCs that need full auth (e.g. hNvQHb conversation reload
        after Token Factory-initiated video generation). Auto-populates browser
        cookies from Chrome if not already available.
        """
        return await self.execute_rpcs_with_browser_cookies(
            [RPCPayload(rpc_id=rpc_id, payload=payload)],
            source_path=source_path,
        )

    async def execute_rpcs_with_browser_cookies(
        self,
        payloads: list[RPCPayload],
        source_path: str = "/app",
    ) -> list[BatchResult]:
        """Execute one or more RPCs in a single batchexecute call with full cookies.

        Batching lets RPCs that only process one payload per call (e.g. qpEbW
        usage queries) be fetched in a single HTTP round-trip.

        Cookies pre-populated from auth.json can be stale; when the request
        returns no data and the cookies did not come from a live Chrome
        session, the cookies are re-extracted from Chrome and the batch is
        retried once.
        """
        results = await self._execute_browser_batch(payloads, source_path)
        cookies_are_live = bool(self._raw_browser_cookies)

        if not any(r.data for r in results) and not cookies_are_live:
            refreshed = await self._ensure_browser_cookies(force=True)
            if refreshed:
                results = await self._execute_browser_batch(payloads, source_path)

        return results

    async def _execute_browser_batch(
        self,
        payloads: list[RPCPayload],
        source_path: str = "/app",
    ) -> list[BatchResult]:
        """One batchexecute POST with whatever browser cookies are available."""
        # Auto-populate browser cookies if not already available
        if not self._browser_cookies:
            await self._ensure_browser_cookies()

        if not self._browser_cookies:
            return await self.execute_rpcs(payloads, source_path)

        from .parser import parse_batchexecute_response
        from .rpc import (
            build_batchexecute_body,
            build_batchexecute_url,
            build_headers,
        )

        rpc_ids = [p.rpc_id for p in payloads]
        url = build_batchexecute_url(
            rpc_ids=rpc_ids,
            reqid=self.transport._next_reqid(),
            build_label=self.transport.build_label,
            session_id=self.transport.session_id,
            source_path=source_path,
        )
        body = build_batchexecute_body(
            payloads,
            self._browser_access_token or self.transport.access_token,
        )
        headers = build_headers()

        if self._browser_http_client is None:
            self._browser_http_client = httpx.AsyncClient(
                http2=True, timeout=self.timeout, follow_redirects=True,
            )

        logger.debug(f"batchexecute (browser cookies): {rpc_ids}")
        response = await self._browser_http_client.post(
            url, content=body, headers=headers, cookies=self._browser_cookies,
        )
        response.raise_for_status()

        parsed = parse_batchexecute_response(response.text)
        return [
            BatchResult(rpc_id=r["rpc_id"], data=r["data"], raw=r["raw"])
            for r in parsed
        ]

    async def process_gem_file(
        self, upload_id: str, filename: str, mime_type: str
    ) -> str:
        """Process an uploaded file for use as a gem knowledge file.

        Calls the ProcessFile endpoint to convert a resumable upload ID into a
        gem knowledge token (starts with "$Aed...") for embedding in gem create/update
        payloads at position 14.

        Discovered via Chrome DevTools (Feb 2026). Different from batchexecute:
        uses a dedicated endpoint with f.req=[null, "{inner_json}"] body format.

        Args:
            upload_id: File identifier from FileService.upload() (e.g. "/contrib_service/ttl_1d/..."
                       as returned by the resumable upload protocol)
            filename: Original filename (e.g. "knowledge.txt")
            mime_type: MIME type of the file (e.g. "text/plain")

        Returns:
            Gem knowledge token starting with "$" for use in gem payload position 14.
        """
        import json
        from urllib.parse import urlencode

        import orjson

        from .constants import Endpoint
        from .parser import extract_json_from_response, get_nested
        from .rpc import build_headers

        # Inner payload: [[[upload_id, null, 1, mime_type], filename, null×6, [1]], null, 1, ["en"]]
        # [1] at the end marks this as a gem knowledge file (vs [0] for chat attachments)
        inner_payload = [
            [[upload_id, None, 1, mime_type], filename, None, None, None, None, None, None, [1]],
            None,
            1,
            ["en"],
        ]
        inner_json = json.dumps(inner_payload)
        f_req = json.dumps([None, inner_json])

        access_token = self._browser_access_token or self.transport.access_token
        body = urlencode({"f.req": f_req, "at": access_token}) + "&"

        params: dict[str, str | int] = {"hl": "en", "_reqid": self.transport._next_reqid(), "rt": "c"}  # noqa: E501
        if self.transport.build_label:
            params["bl"] = self.transport.build_label
        if self.transport.session_id:
            params["f.sid"] = self.transport.session_id

        url = f"{Endpoint.PROCESS_GEM_FILE}?{urlencode(params)}"
        cookies = self._browser_cookies or self.auth_manager.state.cookies
        headers = build_headers()

        if self._browser_http_client is None:
            self._browser_http_client = httpx.AsyncClient(
                http2=True, timeout=self.timeout, follow_redirects=True,
            )

        logger.debug(f"ProcessFile: {filename} ({mime_type})")
        response = await self._browser_http_client.post(
            url, content=body.encode("utf-8"), headers=headers, cookies=cookies,
        )
        response.raise_for_status()

        # Response: streaming wrb.fr frames; token is at data[0][5] of parsed inner JSON
        frames = extract_json_from_response(response.text)
        for frame in frames:
            if not isinstance(frame, list) or len(frame) < 3 or frame[0] != "wrb.fr":
                continue
            raw_json = frame[2]
            if not isinstance(raw_json, str):
                continue
            try:
                data = orjson.loads(raw_json)
            except (orjson.JSONDecodeError, ValueError):
                continue
            token = get_nested(data, [0, 5])
            if isinstance(token, str) and token.startswith("$"):
                logger.debug(f"ProcessFile: got token for {filename}")
                return token

        raise GeminiError(f"ProcessFile: failed to extract gem knowledge token for {filename}")

    async def search_drive(self, query: str, max_results: int = 20) -> list[dict[str, str]]:
        """Search Google Drive files using the v2internal API with SAPISID hash auth.

        Uses the same internal API and auth pattern as the Google Drive Picker,
        supporting Docs, Sheets, Slides, and PDFs. Results are ordered by recency.

        Args:
            query: Search text (e.g. "CSL", "Q4 report")
            max_results: Maximum number of results to return (default 20)

        Returns:
            List of dicts with "id", "name", "mime_type" keys.
        """
        import hashlib
        import time
        from urllib.parse import quote

        cookies = self._browser_cookies or self.auth_manager.state.cookies
        sapisid = cookies.get("SAPISID", "") if isinstance(cookies, dict) else ""

        if not sapisid:
            logger.debug("search_drive: no SAPISID available, returning empty results")
            return []

        ts = int(time.time())
        hash_value = hashlib.sha1(f"{ts} {sapisid} https://docs.google.com".encode()).hexdigest()
        sapisid_hash = f"{ts}_{hash_value}_u"
        auth = f"SAPISIDHASH {sapisid_hash} SAPISID1PHASH {sapisid_hash} SAPISID3PHASH {sapisid_hash}"  # noqa: E501

        # Search Google Workspace files only (Docs, Sheets, Slides, PDF)
        mime_filter = (
            "mimeType='application/vnd.google-apps.document' or "
            "mimeType='application/vnd.google-apps.spreadsheet' or "
            "mimeType='application/vnd.google-apps.presentation' or "
            "mimeType='application/pdf'"
        )
        q = f"fullText contains '{query}' and ({mime_filter}) and trashed=false"

        from .constants import DRIVE_PICKER_API_KEY

        # The direct v2internal/files endpoint returns 401 when called from Python
        # (CORS/auth restriction). The BATCH endpoint accepts the same SAPISID auth
        # and wraps the file-list request in a multipart body — same pattern as the
        # Google Drive Picker uses. Confirmed working via Chrome DevTools (Feb 2026).
        boundary = "=====gemcli_drive_search====="
        inner_params = (
            f"q={quote(q)}"
            f"&maxResults={max_results}"
            "&fields=items(id,title,mimeType)"
            "&supportsAllDrives=true"
            "&includeItemsFromAllDrives=true"
            "&orderBy=recency+desc"
            f"&key={DRIVE_PICKER_API_KEY}"
        )
        inner_request = (
            f"GET /drive/v2internal/files?{inner_params} HTTP/1.1\r\n"
            "\r\n"
        )
        batch_body = (
            f"--{boundary}\r\n"
            "content-type: application/http\r\n"
            "content-transfer-encoding: binary\r\n"
            "\r\n"
            f"{inner_request}"
            f"--{boundary}--"
        )

        url = "https://clients6.google.com/batch/drive/v2internal"
        headers = {
            "Authorization": auth,
            "Content-Type": f'multipart/mixed; boundary="{boundary}"',
            "Origin": "https://docs.google.com",
            "Referer": "https://docs.google.com/",
            "User-Agent": CHROME_USER_AGENT,
            "X-Goog-Authuser": "0",
        }

        if self._browser_http_client is None:
            self._browser_http_client = httpx.AsyncClient(
                http2=True, timeout=self.timeout, follow_redirects=True,
            )

        try:
            resp = await self._browser_http_client.post(
                url, content=batch_body.encode("utf-8"), headers=headers, cookies=cookies,
            )
            if resp.status_code == 200:
                # Parse multipart batch response — find the JSON items inside
                import re
                results = []
                # Extract JSON object from the batch response body
                json_match = re.search(r'\{.*"items".*\}', resp.text, re.DOTALL)
                if json_match:
                    import json as _json
                    data = _json.loads(json_match.group(0))
                    for item in data.get("items", []):
                        results.append({
                            "id": item.get("id", ""),
                            "name": item.get("title", ""),
                            "mime_type": item.get("mimeType", ""),
                        })
                logger.debug(f"search_drive: found {len(results)} results for {query!r}")
                return results
            logger.warning(f"search_drive: HTTP {resp.status_code} for {query!r}: {resp.text[:200]}")  # noqa: E501
        except Exception as e:
            logger.debug(f"search_drive: failed for {query!r}: {e}")

        return []

    async def get_drive_file_info(self, file_id: str) -> dict[str, str]:
        """Look up a Google Drive file's name and MIME type using browser auth.

        Uses SAPISID hash authentication (same as the Google Drive Picker).
        Falls back to generic defaults if the lookup fails.

        Args:
            file_id: Google Drive file ID (e.g. "1xpWhh_M_yJ8SaOoP5mI7ErROtMTikTiLbjYQM-Tb9ZM")

        Returns:
            Dict with "name" and "mime_type" keys.
        """
        import hashlib
        import time

        _DEFAULT_MIME = "application/vnd.google-apps.document"

        cookies = self._browser_cookies or self.auth_manager.state.cookies
        sapisid = cookies.get("SAPISID", "") if isinstance(cookies, dict) else ""

        if not sapisid:
            logger.debug(f"get_drive_file_info: no SAPISID, using defaults for {file_id}")
            return {"name": file_id, "mime_type": _DEFAULT_MIME}

        ts = int(time.time())
        hash_value = hashlib.sha1(f"{ts} {sapisid} https://docs.google.com".encode()).hexdigest()
        sapisid_hash = f"{ts}_{hash_value}_u"
        auth = f"SAPISIDHASH {sapisid_hash} SAPISID1PHASH {sapisid_hash} SAPISID3PHASH {sapisid_hash}"  # noqa: E501

        from .constants import DRIVE_PICKER_API_KEY

        url = (
            f"https://clients6.google.com/drive/v2internal/files/{file_id}"
            f"?fields=title%2CmimeType&key={DRIVE_PICKER_API_KEY}"
        )
        headers = {
            "Authorization": auth,
            "Origin": "https://docs.google.com",
            "Referer": "https://docs.google.com/",
            "User-Agent": CHROME_USER_AGENT,
        }

        if self._browser_http_client is None:
            self._browser_http_client = httpx.AsyncClient(
                http2=True, timeout=self.timeout, follow_redirects=True,
            )

        try:
            resp = await self._browser_http_client.get(
                url, headers=headers, cookies=cookies,
            )
            if resp.status_code == 200:
                data = resp.json()
                return {
                    "name": data.get("title", data.get("name", file_id)),
                    "mime_type": data.get("mimeType", _DEFAULT_MIME),
                }
            logger.debug(f"get_drive_file_info: HTTP {resp.status_code} for {file_id}, using defaults")  # noqa: E501
        except Exception as e:
            logger.debug(f"get_drive_file_info: lookup failed for {file_id}: {e}")

        return {"name": file_id, "mime_type": _DEFAULT_MIME}

    async def process_gem_drive_file(
        self, file_id: str, file_name: str, mime_type: str
    ) -> str:
        """Process a Google Drive file for use as a gem knowledge file.

        Calls the ProcessFile endpoint with a Drive file reference (no upload needed).
        The Drive file ID is passed directly — no resumable upload step required.

        Discovered via Chrome DevTools (Feb 2026). Drive payload format differs
        from local files: upload_id is null, Drive info replaces it at position 4.

        Args:
            file_id: Google Drive file ID
            file_name: Display name for the file
            mime_type: MIME type (e.g. "application/vnd.google-apps.document")

        Returns:
            Gem knowledge token starting with "$" for embedding at payload position 14.
        """
        import json
        from urllib.parse import urlencode

        import orjson

        from .constants import Endpoint
        from .parser import extract_json_from_response, get_nested
        from .rpc import build_headers

        drive_url = f"https://drive.google.com/open?id={file_id}"
        # Drive payload: [null, name, null, null, [[file_id], null, drive_url, mime], null×3, [1]]
        drive_entry = [None, file_name, None, None, [[file_id], None, drive_url, mime_type], None, None, None, [1]]  # noqa: E501
        inner_payload = [
            drive_entry,
            None,
            1,
            ["en"],
        ]
        inner_json = json.dumps(inner_payload)
        f_req = json.dumps([None, inner_json])

        access_token = self._browser_access_token or self.transport.access_token
        body = urlencode({"f.req": f_req, "at": access_token}) + "&"

        params: dict[str, str | int] = {"hl": "en", "_reqid": self.transport._next_reqid(), "rt": "c"}  # noqa: E501
        if self.transport.build_label:
            params["bl"] = self.transport.build_label
        if self.transport.session_id:
            params["f.sid"] = self.transport.session_id

        url = f"{Endpoint.PROCESS_GEM_FILE}?{urlencode(params)}"
        cookies = self._browser_cookies or self.auth_manager.state.cookies
        headers = build_headers()

        if self._browser_http_client is None:
            self._browser_http_client = httpx.AsyncClient(
                http2=True, timeout=self.timeout, follow_redirects=True,
            )

        logger.debug(f"ProcessFile (Drive): {file_name} [{file_id}]")
        response = await self._browser_http_client.post(
            url, content=body.encode("utf-8"), headers=headers, cookies=cookies,
        )
        response.raise_for_status()

        frames = extract_json_from_response(response.text)
        for frame in frames:
            if not isinstance(frame, list) or len(frame) < 3 or frame[0] != "wrb.fr":
                continue
            raw_json = frame[2]
            if not isinstance(raw_json, str):
                continue
            try:
                data = orjson.loads(raw_json)
            except (orjson.JSONDecodeError, ValueError):
                continue
            token = get_nested(data, [0, 5])
            if isinstance(token, str) and token.startswith("$"):
                logger.debug(f"ProcessFile (Drive): got token for {file_name}")
                return token

        raise GeminiError(f"ProcessFile (Drive): failed to extract token for {file_name} [{file_id}]")  # noqa: E501

    def get_cookies(self) -> dict[str, str]:
        """Get the best available cookies (full browser set if available, else auth-only)."""
        if self._browser_cookies:
            return self._browser_cookies
        return self.auth_manager.state.cookies

    def get_httpx_cookies(self) -> httpx.Cookies:
        """Get cookies as httpx.Cookies with proper domain handling for cross-domain downloads.

        Duplicates cookies for both .google.com and .googleusercontent.com
        to ensure authentication works across Google CDN redirect domains.
        This is required for downloading images from lh3.googleusercontent.com.
        """
        cookies = httpx.Cookies()

        if self._raw_browser_cookies:
            for c in self._raw_browser_cookies:
                name = c.get("name")
                value = c.get("value")
                domain = c.get("domain", "")
                path = c.get("path", "/")

                if not name or not value:
                    continue

                if "google.com" in domain:
                    cookies.set(name, value, domain=domain, path=path)
                    # Duplicate for .googleusercontent.com for CDN downloads
                    if domain == ".google.com":
                        cookies.set(
                            name, value, domain=".googleusercontent.com", path=path
                        )
        else:
            # Fallback: simple cookies without domain info — set for both domains
            for name, value in self.get_cookies().items():
                cookies.set(name, value, domain=".google.com")
                cookies.set(name, value, domain=".googleusercontent.com")

        return cookies

    async def download_media(
        self,
        url: str,
        output_path: str | Path,
        headers: dict[str, str] | None = None,
        timeout: float = 120.0,
    ) -> Path:
        """Download a media file, trying CDP page fetch first, then httpx.

        CDP page fetch uses JavaScript fetch() from the Gemini page context,
        which has access to Chrome's full cookie jar including partitioned
        cookies. This is required for contribution.usercontent.google.com
        downloads, where CDP's Network.getAllCookies is missing critical cookies.

        Falls back to httpx with domain-aware cookies if Chrome is not
        available (e.g., Flash model without Token Factory).

        Args:
            url: The media download URL.
            output_path: Local path to save the downloaded file.
            headers: Optional HTTP headers (used only for httpx fallback).
            timeout: Download timeout in seconds.

        Returns:
            Path to the saved file.
        """
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)

        # Try CDP page fetch first (handles partitioned cookies)
        try:
            data = await self._download_via_cdp(url, timeout=int(timeout))
            output.write_bytes(data)
            logger.info(f"Downloaded via browser: {output} ({len(data)} bytes)")
            return output
        except Exception as e:
            logger.debug(f"CDP download unavailable, falling back to httpx: {e}")

        # Fallback: httpx with domain-aware cookies
        cookies = self.get_httpx_cookies()
        fallback_headers = headers or {
            "User-Agent": CHROME_USER_AGENT,
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9",
            "Origin": "https://gemini.google.com",
            "Referer": "https://gemini.google.com/",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-site",
        }
        http_timeout = httpx.Timeout(
            connect=10.0, read=timeout, write=30.0, pool=30.0,
        )

        async with httpx.AsyncClient(
            http2=True,
            headers=fallback_headers,
            cookies=cookies,
            follow_redirects=True,
            timeout=http_timeout,
        ) as client:
            response = await client.get(url)

            # Check for auth redirect (200 with HTML instead of media)
            content_type = response.headers.get("content-type", "").lower()
            if "text/html" in content_type:
                raise GeminiError(
                    "Media download redirected to login page. "
                    "Ensure Chrome is running with 'gemcli chrome start' "
                    "or re-login with 'gemcli login'."
                )

            response.raise_for_status()
            output.write_bytes(response.content)

        logger.info(f"Downloaded via httpx: {output}")
        return output

    async def _download_via_cdp(self, url: str, timeout: int = 120) -> bytes:
        """Download via CDP page fetch (runs in executor since CDP is sync).

        Uses a priority-based port discovery:
        1. Token Factory's port (already authenticated, most reliable)
        2. Profile-aware port map lookup
        3. Raises error if no Chrome is available

        Includes retry logic for:
        - Stale CDP target IDs after Chrome restart (Bug 4)
        - Transient "no Gemini page" during Chrome navigation (Bug 3)
        """
        from .cdp import (
            StaleTargetError,
            download_via_page_fetch,
            find_existing_gemcli_chrome,
            get_gemini_page_ws_url,
        )

        loop = asyncio.get_event_loop()

        def _do_download():
            max_retries = 2
            last_error = None

            for attempt in range(max_retries):
                port = None

                # Priority 1: Token Factory's Chrome (already has authenticated session)
                if self._token_factory and self._token_factory._port:
                    port = self._token_factory._port
                    logger.debug(f"CDP download: using Token Factory port {port}")

                # Priority 2: Profile-aware discovery from port map
                if not port:
                    profile_name = self.auth_manager.resolved_profile_name
                    found_port, _ = find_existing_gemcli_chrome(
                        profile_name=profile_name
                    )
                    if found_port:
                        port = found_port
                        logger.debug(f"CDP download: using mapped port {port}")

                if not port:
                    raise GeminiError("No Chrome instance found for browser download")

                ws_url = get_gemini_page_ws_url(port)
                if not ws_url:
                    if attempt < max_retries - 1:
                        logger.debug(
                            "CDP download: no Gemini page found, retrying..."
                        )
                        import time
                        time.sleep(1)
                        continue
                    raise GeminiError(
                        "No Gemini page found in Chrome for browser download"
                    )

                try:
                    return download_via_page_fetch(ws_url, url, timeout=timeout)
                except StaleTargetError as e:
                    last_error = e
                    logger.warning(
                        f"CDP download: stale target ID ({e}), "
                        f"resetting Token Factory state and retrying..."
                    )
                    # Reset Token Factory so it re-discovers Chrome on next use
                    if self._token_factory:
                        self._token_factory._ws_url = None
                        self._token_factory._ready = False
                    continue

            raise last_error or GeminiError("CDP download failed after retries")

        return await loop.run_in_executor(None, _do_download)

    def _needs_token_factory(self, model: Model) -> bool:
        """Check if this model requires BotGuard tokens (Pro/Thinking)."""
        return model.name in TOKEN_FACTORY_MODELS or model.thinking_level != "low"

    def _ensure_token_factory(self):
        """Lazy-initialize the Token Factory."""
        if self._token_factory is None:
            from .token_factory import TokenFactory

            auth_state = self.auth_manager.state
            if not auth_state.chrome_profile_path:
                raise TokenFactoryError(
                    "No Chrome profile configured. Run 'gemcli login' first."
                )
            self._token_factory = TokenFactory(
                chrome_profile_path=auth_state.chrome_profile_path,
                profile_name=self.auth_manager.resolved_profile_name,
            )
        return self._token_factory

    async def _send_via_token_factory(
        self,
        prompt: str,
        model: Model,
        metadata: ConversationMetadata | None = None,
        file_data: list | None = None,
        gem_id: str | None = None,
        tool_id: int | None = None,
        style_preset: dict | None = None,
        video_orientation: str | None = None,
        template: str | None = None,
        image_aspect: str | None = None,
        music_length: str | None = None,
        music_vocals: str | None = None,
        music_genre: str | None = None,
        task: bool = False,
    ) -> StreamResponse:
        """Send via Token Factory: Chrome captures BotGuard token, Python sends HTTP."""
        factory = self._ensure_token_factory()

        # TokenFactory is sync (CDP uses sync websocket) — run in executor
        loop = asyncio.get_event_loop()
        captured = await loop.run_in_executor(
            None,
            lambda: factory.capture(
                prompt=prompt,
                model=model,
                metadata=metadata,
                tool_id=tool_id,
                video_orientation=video_orientation,
                template=template,
                image_aspect=image_aspect,
                music_length=music_length,
                music_vocals=music_vocals,
                music_genre=music_genre,
                task=task,
            ),
        )

        # Create a separate HTTP client for browser-replay requests
        # (no preset cookies — we use the captured cookies directly)
        if self._browser_http_client is None:
            self._browser_http_client = httpx.AsyncClient(
                http2=True,
                timeout=self.timeout,
                follow_redirects=True,
            )

        # Store browser cookies and access token for use by other operations
        # (e.g., image download, video polling batchexecute calls).
        # IMPORTANT: captured.access_token is Chrome's live SNlM0e token extracted
        # from window.WIZ_global_data — use it for ANY subsequent calls that use
        self._browser_cookies = captured.cookies
        self._raw_browser_cookies = factory.get_raw_cookies()
        self._browser_access_token = captured.access_token  # Chrome's live SNlM0e

        # Sync fresh CDP auth back to disk so parallel/future CLI runs get it
        try:
            from gemini_web_mcp_cli.core.auth import AuthManager
            am = AuthManager(
                self.profile_manager, profile_name=self.auth_manager.resolved_profile_name
            )
            am.load()
            am.state.tokens.snlm0e = captured.access_token
            if self._raw_browser_cookies:
                cookie_dict = {}
                for c in self._raw_browser_cookies:
                    if c.get("name") and c.get("value") and "google.com" in c.get("domain", ""):
                        cookie_dict[c["name"]] = c["value"]
                if cookie_dict:
                    am.save_cookies(cookie_dict)
                    logger.debug("Token Factory: synced fresh browser cookies back to AuthManager.")
        except Exception as e:
            logger.debug(f"Failed to sync Token Factory auth to disk: {e}")

        if captured.transport == TRANSPORT_PROCESS_SESSION:
            return await self._replay_process_session(
                captured, prompt, model, file_data, metadata
            )

        # We extract the BotGuard token from Chrome's captured body and inject it
        # into our rebuilt body. We use Chrome's live SNlM0e access token
        # (captured.access_token) to ensure the 'at=' parameter is always consistent

        # Relay Chrome's captured body with the real prompt (inner[0][0]),
        # attachments (inner[0][3]) and conversation (inner[2]) patched in.
        # Chrome types a newline-free copy of the prompt (typing a newline cut
        # the captured prompt off at the first line, issue #2); BotGuard does
        # not bind the prompt text, so patching it is safe (verified live).
        body_str = self._patch_captured_body(
            captured.body, prompt, metadata=metadata, file_data=file_data
        )

        logger.debug(
            f"Token Factory: relaying Chrome's signed body "
            f"(model={model.name}, body_len={len(body_str)})"
        )
        response = await self._browser_http_client.post(
            captured.url,
            content=body_str,
            headers=captured.headers,
            cookies=captured.cookies,
        )
        response.raise_for_status()

        result = build_stream_response(response.text)
        logger.debug(
            f"Token Factory response: text={bool(result.text)}, "
            f"images={result.has_images}, video={result.has_video}, "
            f"music={result.has_music}, model={result.server_model_hash}, "
            f"candidates={len(result.candidates)}"
        )
        return result

    async def _replay_process_session(
        self,
        captured,
        prompt: str,
        model: Model,
        file_data: list | None,
        metadata: ConversationMetadata | None,
    ) -> StreamResponse:
        """Replay a processSession capture: open a channel with Chrome's cookies,
        send Chrome's setup message and the prompt, parse the streamed answer."""
        try:
            messages = webchannel.decode_forward_body(captured.body)
        except ValueError as e:
            raise APIError(f"Unrecognised processSession request from Chrome: {e}") from e
        setup = webchannel.find_setup_message(messages)
        if setup is None:
            raise TokenFactoryError("processSession capture has no setup message.")
        inner = webchannel.setup_inner(setup)
        if metadata and metadata.cid:
            webchannel.set_conversation(inner, metadata.cid)
        if file_data:
            while len(inner[0]) <= 3:
                inner[0].append(None)
            inner[0][3] = file_data
        # Chrome may encode the channel as binary protobuf; decode_forward_body
        # converted its setup to JSON, so declare JSON for the replayed channel.
        open_url = webchannel.use_json_encoding(
            webchannel.apply_model(captured.url, setup, model)
        )

        transcript = await webchannel.replay(
            self._browser_http_client,
            open_url,
            [setup, webchannel.prompt_message(prompt)],
            cookies=captured.cookies,
            headers=captured.headers,
            timeout=self.timeout,
        )
        result = build_process_session_response(transcript)
        logger.debug(
            f"Token Factory (processSession) response: text={bool(result.text)}, "
            f"images={result.has_images}, video={result.has_video}, "
            f"music={result.has_music}, model={result.server_model_hash}, "
            f"candidates={len(result.candidates)}"
        )
        return result

    @staticmethod
    def _extract_botguard(captured_body: str) -> tuple[str | None, str | None]:
        """Extract BotGuard token and challenge hash from Chrome's captured request body.

        Chrome's body is URL-encoded form data with an f.req parameter containing
        a nested JSON array. The BotGuard token is at inner[3] and the challenge
        hash is at inner[4].

        Returns:
            Tuple of (botguard_token, botguard_hash), either may be None.
        """
        import json
        from urllib.parse import parse_qs, unquote

        try:
            parsed = parse_qs(captured_body)
            f_req_raw = parsed.get("f.req", [None])[0]
            if not f_req_raw:
                # processSession data POST (req0___data__ = setup message)
                return webchannel.extract_botguard(captured_body)
            f_req = unquote(f_req_raw)
            outer = json.loads(f_req)
            inner = json.loads(outer[1])
            token = inner[3] if len(inner) > 3 and isinstance(inner[3], str) else None
            hash_val = inner[4] if len(inner) > 4 and isinstance(inner[4], str) else None
            if token:
                logger.debug(f"Extracted BotGuard token ({len(token)} chars) "
                             f"and hash={hash_val is not None}")
            return token, hash_val
        except Exception as e:
            logger.debug(f"Could not extract BotGuard from captured body: {e}")
            return None, None

    @staticmethod
    def _extract_at_from_body(captured_body: str) -> str | None:
        """Extract the at= (SNlM0e) token from Chrome's captured request body.

        Chrome's body is URL-encoded form data containing an 'at' parameter
        that holds the SNlM0e access token. This token is guaranteed to match
        Chrome's cookies since it's the one Chrome was going to use.

        Returns:
            The access token string, or None if not found.
        """
        from urllib.parse import parse_qs

        try:
            parsed = parse_qs(captured_body)
            at_values = parsed.get("at", [])
            if at_values and at_values[0]:
                token = at_values[0]
                logger.debug(
                    f"Extracted at= token from captured body "
                    f"({len(token)} chars)"
                )
                return token
        except Exception as e:
            logger.debug(f"Could not extract at= from captured body: {e}")
        return None

    @staticmethod
    def _patch_captured_body(
        captured_body: str,
        prompt: str,
        metadata: object = None,
        file_data: list | None = None,
    ) -> str:
        """Patch Chrome's captured request body with the real prompt and file data.

        Instead of rebuilding the entire body from scratch (which uses hardcoded
        inner array indices that go stale when Gemini updates their API), we modify
        Chrome's captured body in-place:
        - inner[0][0] = real prompt text
        - inner[0][3] = file_data (if provided)
        - inner[2] = conversation metadata (if provided, for multi-turn)

        This preserves Chrome's BotGuard token, array structure, and all other
        fields that may have shifted in newer Gemini versions.

        IMPORTANT: The inner array must maintain its exact original length.
        json.loads/json.dumps can strip trailing null elements; we explicitly
        pad back to the original length to avoid server rejection.
        """
        import json
        from urllib.parse import parse_qs, unquote, urlencode

        parsed = parse_qs(captured_body)
        f_req_raw = parsed.get("f.req", [None])[0]
        if not f_req_raw:
            raise ValueError("No f.req in captured body")

        f_req_str = unquote(f_req_raw)
        outer = json.loads(f_req_str)
        inner_str = outer[1]
        inner = json.loads(inner_str)
        original_length = len(inner)

        # Patch prompt text (inner[0][0])
        if len(inner) > 0 and isinstance(inner[0], list) and len(inner[0]) > 0:
            inner[0][0] = prompt
        else:
            inner[0] = [prompt, 0, None, None, None, None, 0]

        # Patch file_data (inner[0][3])
        if file_data is not None:
            while len(inner[0]) <= 3:
                inner[0].append(None)
            inner[0][3] = file_data

        # Patch conversation metadata (inner[2]) for multi-turn
        if metadata and hasattr(metadata, "to_list"):
            inner[2] = metadata.to_list()

        # Pad back to original length — json.loads can strip trailing nulls
        while len(inner) < original_length:
            inner.append(None)

        # Rebuild with compact separators (matching Chrome's JSON format)
        outer[1] = json.dumps(inner, separators=(",", ":"))
        new_f_req = json.dumps(outer, separators=(",", ":"))

        # Chrome's body may or may not have at=. Preserve whatever was there.
        result_parts = {"f.req": new_f_req}
        at_values = parsed.get("at")
        if at_values:
            result_parts["at"] = at_values[0]

        return urlencode(result_parts) + "&"

    def _resolve_model(
        self,
        model: str | Model | None,
        extended_thinking: bool | None = None,
        thinking_level: str | None = None,
    ) -> Model:
        """Resolve a model name and its thinking level.

        ``thinking_level`` (low, medium, high) wins over the Extended thinking
        boolean. The boolean still maps on to High and off to the fast model
        when the selected model is the legacy thinking alias.
        """
        if model is None:
            resolved = DEFAULT_MODEL
        elif isinstance(model, Model):
            resolved = model
        else:
            resolved = get_model(model)

        if thinking_level:
            return resolved.with_thinking_level(thinking_level)
        if extended_thinking is True:
            return resolved.with_extended_thinking()
        if extended_thinking is False and resolved.extended_thinking:
            return MODELS["fast"]
        return resolved

    async def __aenter__(self):
        await self.init()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()
