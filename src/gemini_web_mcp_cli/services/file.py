"""File service: upload files to Gemini.

Implements the 2-step resumable upload protocol to push.clients6.google.com.
"""

from __future__ import annotations

from pathlib import Path

import httpx
from loguru import logger

from gemini_web_mcp_cli.core.client import GeminiClient
from gemini_web_mcp_cli.core.constants import CHROME_USER_AGENT, RPC
from gemini_web_mcp_cli.core.exceptions import GeminiError

_UPLOAD_URL = "https://push.clients6.google.com/upload/"
_PUSH_ID = "feeds/mcudyrk2a4khkz"

# File-type codes used in the file_data entry sent to StreamGenerate
# (inner[0][3][i][0][1]). Google expects a per-category integer, NOT a single
# constant. Confirmed via live capture (Jul 2026): video -> 2. The Feb 2026
# capture used 16 for a markdown/text file, so text-like types keep 16.
FILE_TYPE_CODES = {
    "video": 2,
    "image": 3,
    "audio": 4,
}


def file_type_code(mime_type: str) -> int:
    """Map a MIME type to Gemini's file-type code for the file_data entry."""
    category = (mime_type or "").split("/", 1)[0].lower()
    return FILE_TYPE_CODES.get(category, 16)


def build_file_data(file_id: str, name: str, mime_type: str) -> list:
    """Build one StreamGenerate file_data entry (an inner[0][3] item).

    Format discovered via Chrome DevTools MCP live capture.
    """
    return [
        [file_id, file_type_code(mime_type), None, mime_type],
        name,
        None, None, None, None, None, None,
        [0],
    ]


class FileService:
    """Service for uploading files to Gemini."""

    def __init__(self, client: GeminiClient):
        self.client = client
        self._bard_activity_enabled = False

    async def _ensure_bard_activity(self):
        """Enable Bard activity (required before first upload)."""
        if self._bard_activity_enabled:
            return

        try:
            await self.client.execute_rpc(RPC.BARD_ACTIVITY, payload="[1]")
            self._bard_activity_enabled = True
            logger.debug("Enabled Bard activity for file upload")
        except Exception as e:
            logger.warning(f"Failed to enable Bard activity: {e}")
            # Non-fatal, try upload anyway

    async def upload(self, file_path: str | Path) -> str:
        """Upload a file using the 2-step resumable upload protocol.

        Args:
            file_path: Local path to the file.

        Returns:
            File identifier string (e.g., "/contrib_service/ttl_1d/...")
        """
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {path}")

        file_size = path.stat().st_size
        filename = path.name

        if file_size == 0:
            raise ValueError(f"File is empty: {path}")

        await self._ensure_bard_activity()

        logger.info(f"Uploading file: {filename} ({file_size} bytes)")

        cookies = self.client.get_httpx_cookies()
        base_headers = {
            "User-Agent": CHROME_USER_AGENT,
            "Origin": "https://gemini.google.com",
            "Referer": "https://gemini.google.com/",
        }

        async with httpx.AsyncClient(http2=True, cookies=cookies) as http_client:
            # Step 1: Start Resumable Upload
            start_headers = dict(base_headers)
            start_headers.update({
                "push-id": _PUSH_ID,
                "x-goog-upload-command": "start",
                "x-goog-upload-protocol": "resumable",
                "x-goog-upload-header-content-length": str(file_size),
                "content-type": "application/x-www-form-urlencoded;charset=UTF-8",
            })

            body = f"File name: {filename}"

            resp1 = await http_client.post(
                _UPLOAD_URL,
                headers=start_headers,
                content=body.encode("utf-8"),
                timeout=30.0,
            )

            if resp1.status_code != 200:
                raise GeminiError(
                    f"Failed to start upload session (status {resp1.status_code}): {resp1.text}"
                )

            upload_url = resp1.headers.get("x-goog-upload-url")
            if not upload_url:
                raise GeminiError("Upload response missing x-goog-upload-url header")

            # Step 2: Upload Data (true streaming)
            upload_headers = dict(base_headers)
            upload_headers.update({
                "push-id": _PUSH_ID,
                "x-goog-upload-command": "upload, finalize",
                "x-goog-upload-offset": "0",
                "content-type": "application/x-www-form-urlencoded;charset=utf-8",
                "content-length": str(file_size),
            })

            # Stream the file in chunks instead of loading entirely into memory.
            # Critical for large files (100MB+ videos) where read_bytes() would
            # block the event loop and consume excessive RAM.
            chunk_size = 1024 * 1024  # 1 MB
            file_size_mb = file_size / (1024 * 1024)
            # Log progress every ~10 MB (or every chunk for files < 10 MB)
            log_interval = max(1, int(10 * 1024 * 1024 / chunk_size))

            async def _stream_file():
                """Async generator that yields file chunks for streaming upload."""
                bytes_sent = 0
                chunks_since_log = 0
                with open(path, "rb") as f:
                    while True:
                        chunk = f.read(chunk_size)
                        if not chunk:
                            break
                        bytes_sent += len(chunk)
                        chunks_since_log += 1
                        if chunks_since_log >= log_interval:
                            sent_mb = bytes_sent / (1024 * 1024)
                            logger.info(
                                f"Upload progress: {sent_mb:.1f} / {file_size_mb:.1f} MB"
                            )
                            chunks_since_log = 0
                        yield chunk
                logger.info(f"Upload complete: {bytes_sent / (1024 * 1024):.1f} MB sent")

            # Dynamic timeout: base 60s + 2s per MB, minimum 120s.
            upload_timeout = max(120.0, 60.0 + file_size_mb * 2)

            resp2 = await http_client.post(
                upload_url,
                headers=upload_headers,
                content=_stream_file(),
                timeout=upload_timeout,
            )

            if resp2.status_code != 200:
                raise GeminiError(
                    f"Failed to finalize upload (status {resp2.status_code}): {resp2.text}"
                )

            file_id = resp2.text.strip()
            if not file_id:
                raise GeminiError("Upload finalized but returned empty file identifier")

            logger.debug(f"File uploaded successfully: {file_id}")
            return file_id
