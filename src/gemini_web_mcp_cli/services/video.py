"""Video service: generate videos via Gemini Omni (Veo 3.1)."""

from __future__ import annotations

import asyncio
from pathlib import Path

from loguru import logger

from gemini_web_mcp_cli.core.client import GeminiClient
from gemini_web_mcp_cli.core.constants import (
    VIDEO_TOOL_ID,
    normalize_video_orientation,
)
from gemini_web_mcp_cli.core.exceptions import VideoGenerationError
from gemini_web_mcp_cli.core.models import StreamResponse

VIDEO_REJECTION_PATTERNS = [
    "can't generate more videos",
    "cannot generate more videos",
]


def extract_video_url(video_data: list) -> str | None:
    """Extract the download URL from candidate[12][59] video data.

    Video data structure:
        video_data[0]          = entries array (wraps the entry)
        video_data[0][0]       = entry: [tracks, metadata, safety_classifiers]
        video_data[0][0][0]    = tracks array (wraps the track)
        video_data[0][0][0][0] = track data
        track_data[7]          = [preview_url, download_url, preview_url_2]
        track_data[11]         = "video/mp4"
        track_data[17]         = [[duration], width, height]

    Returns the download URL or None.
    """
    try:
        url = video_data[0][0][0][0][7][1]
        if url:
            return url
    except (IndexError, TypeError):
        pass

    # Fallback: scan for any string starting with https:// in the structure
    def _find_url(obj: object, depth: int = 0) -> str | None:
        if depth > 8:
            return None
        if isinstance(obj, str) and obj.startswith("https://") and len(obj) > 30:
            return obj
        if isinstance(obj, list):
            for item in obj:
                result = _find_url(item, depth + 1)
                if result:
                    return result
        return None

    return _find_url(video_data)


def extract_video_metadata(video_data: list) -> dict | None:
    """Extract video metadata (description, model, duration, resolution).

    Structure:
        video_data[0][0][1]       = metadata array
        video_data[0][0][0][0]    = track data (with mime_type, duration, resolution)
    """
    try:
        meta = video_data[0][0][1]
        result: dict = {}
        if meta and isinstance(meta, list):
            if len(meta) > 0 and meta[0]:
                result["description"] = meta[0]
            if len(meta) > 2 and meta[2] and isinstance(meta[2], list):
                if len(meta[2]) > 2 and meta[2][2]:
                    result["model"] = meta[2][2]
            if len(meta) > 7 and meta[7] and isinstance(meta[7], list):
                if len(meta[7]) > 0 and meta[7][0]:
                    result["scene"] = meta[7][0][:200]
        # Duration and resolution from track data
        track = video_data[0][0][0][0]
        if isinstance(track, list):
            if len(track) > 11 and track[11]:
                result["mime_type"] = track[11]
            if len(track) > 17 and track[17] and isinstance(track[17], list):
                duration_info = track[17]
                if len(duration_info) > 0 and isinstance(duration_info[0], list):
                    result["duration_seconds"] = duration_info[0][0]
                if len(duration_info) > 1:
                    result["width"] = duration_info[1]
                if len(duration_info) > 2:
                    result["height"] = duration_info[2]
        width = result.get("width")
        height = result.get("height")
        if isinstance(width, int) and isinstance(height, int) and width and height:
            result["orientation"] = "portrait" if height > width else "landscape"
        return result if result else None
    except (IndexError, TypeError):
        return None


class VideoService:
    """Service for video generation using Gemini Omni (Veo 3.1 engine).

    The Omni video tool supports:
    - Model selection via the Gemini mode picker: flash (default), pro, lite,
      thinking (extended). Pro/thinking videos use the higher-quality engine.
    - Orientation: landscape (16:9) or portrait (9:16).

    Video generation is async:
    1. StreamGenerate starts the generation (returns acknowledgment)
    2. Poll hNvQHb (conversation reload) with browser cookies until video data appears
    3. Completed response contains video data at candidate[12][59]

    The hNvQHb RPC requires:
    - Full browser cookies (28+), not basic 2-cookie auth
    - Payload: ["c_<cid>",10,null,1,[1],[4],null,1]
    - source_path: /app/<cid_short>

    Download URL is at contribution.usercontent.google.com (same domain as music).
    """

    def __init__(self, client: GeminiClient):
        self.client = client
        self._cid: str | None = None

    async def generate(
        self,
        prompt: str,
        model: str | None = None,
        orientation: str | None = "landscape",
        template: str | None = None,
        files: list[str] | None = None,
    ) -> StreamResponse:
        """Start video generation from a text prompt.

        Video generation requires BotGuard tokens and tool_id=11 (VIDEO_TOOL_ID)
        to explicitly activate Omni video routing. The Token Factory also drives
        Chrome's aspect-ratio, template, and model controls so the signed
        request body carries the requested options.

        Args:
            prompt: Description of the video to create.
            model: "flash" (default), "pro", "lite", or "thinking".
            orientation: "landscape" (16:9, default) or "portrait" (9:16).
                         Accepts common aliases like "16:9" / "9:16".
            template: Optional Omni template name (e.g. "Anime", "Logo reveal",
                      "8-bit adventure"). Templates prefill the style; the
                      prompt and orientation still apply.
            files: Optional reference files (images, videos, audio) to upload
                   and attach. Omni uses them as references for the generated
                   video (e.g. animate a still image).

        Returns the initial acknowledgment. Use wait_for_completion() to poll.
        """
        import mimetypes
        from pathlib import Path

        from gemini_web_mcp_cli.services.file import FileService, build_file_data

        file_data = None
        if files:
            file_data = []
            file_service = FileService(self.client)
            for fpath in files:
                path = Path(fpath)
                file_id = await file_service.upload(path)
                mime_type, _ = mimetypes.guess_type(path)
                mime_type = mime_type or "application/octet-stream"
                file_data.append(build_file_data(file_id, path.name, mime_type))

        normalized = normalize_video_orientation(orientation)
        response = await self.client.send(
            prompt=prompt,
            model=model,
            tool_id=VIDEO_TOOL_ID,
            force_token_factory=True,
            video_orientation=normalized,
            template=template,
            file_data=file_data,
        )
        if response.metadata and response.metadata.cid:
            self._cid = response.metadata.cid
        return response

    async def poll_status(self, source_path: str | None = None) -> dict:
        """Poll for video generation completion using hNvQHb conversation reload.

        Uses browser cookies and proper payload format to reload the conversation.
        Returns video data when generation is complete.
        """
        if not self._cid:
            return {"status": "no_cid"}

        import json

        cid_short = self._cid.replace("c_", "")
        path = source_path or f"/app/{cid_short}"
        payload = json.dumps([self._cid, 10, None, 1, [1], [4], None, 1])

        results = await self.client.execute_rpc_with_browser_cookies(
            rpc_id="hNvQHb",
            payload=payload,
            source_path=path,
        )
        if results and results[0].data:
            return {"status": "polled", "data": results[0].data}
        return {"status": "no_result"}

    async def wait_for_completion(
        self,
        poll_interval: float = 15.0,
        max_wait: float = 900.0,
    ) -> StreamResponse | None:
        """Poll repeatedly until video generation completes or timeout.

        Polls hNvQHb with browser cookies to reload the conversation.
        When video data appears at candidate[12][59], returns the response.

        Returns StreamResponse with video data, or None on timeout.
        """
        if not self._cid:
            logger.warning("No conversation ID, cannot poll for video completion")
            return None

        elapsed = 0.0

        while elapsed < max_wait:
            await asyncio.sleep(poll_interval)
            elapsed += poll_interval

            result = await self.poll_status()
            logger.debug(f"Video poll ({elapsed:.0f}s): {result.get('status')}")

            data = result.get("data")
            if data is None:
                continue

            # Parse the conversation data to find video
            response = self._parse_conversation_data(data)
            if response and response.has_video:
                logger.info(f"Video generation complete ({elapsed:.0f}s)")
                return response

            if response and not response.has_video and response.text:
                text_lower = response.text.lower()
                for pattern in VIDEO_REJECTION_PATTERNS:
                    if pattern in text_lower:
                        logger.warning(f"Video quota exceeded: {response.text}")
                        raise VideoGenerationError(response.text)

        logger.warning(f"Video poll timeout after {max_wait}s")
        return None

    def _parse_conversation_data(self, data: list) -> StreamResponse | None:
        """Parse hNvQHb conversation data to extract video response.

        hNvQHb returns: data[0][0][3][0][0] = candidate array
        Video data appears at candidate[12][59] once rendering completes
        (confirmed: candidate[12] grows to len=65 during Veo render).
        """
        try:
            from gemini_web_mcp_cli.core.models import Candidate
            from gemini_web_mcp_cli.core.parser import get_nested

            candidate_raw = get_nested(data, [0, 0, 3, 0, 0])
            if not isinstance(candidate_raw, list):
                return None

            # Video data at candidate[12][59] once Veo rendering is complete
            video_data = get_nested(candidate_raw, [12, 59])
            text = get_nested(candidate_raw, [1, 0])
            rcid = get_nested(candidate_raw, [0])

            return StreamResponse(
                candidates=[
                    Candidate(
                        rcid=rcid,
                        text=text,
                        generated_video=video_data,
                    )
                ],
                text=text,
                is_complete=True,
            )
        except Exception as e:
            logger.error(f"Failed to parse video conversation: {e}")
            return None

    async def download(
        self,
        video_url: str,
        output_path: str | Path,
    ) -> Path:
        """Download a generated video to a local file.

        Uses CDP page fetch (JavaScript fetch from Gemini page context)
        to bypass partitioned cookie restrictions. Falls back to httpx
        if Chrome is unavailable.
        """
        return await self.client.download_media(
            url=video_url, output_path=output_path, timeout=120.0,
        )
