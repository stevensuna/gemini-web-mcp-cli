"""Music service: generate music tracks via Gemini (Lyria 3.5)."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path

from loguru import logger

from gemini_web_mcp_cli.core.client import GeminiClient
from gemini_web_mcp_cli.core.constants import (
    MUSIC_TOOL_ID,
    normalize_music_genre,
    normalize_music_length,
    normalize_music_vocals,
)
from gemini_web_mcp_cli.core.models import StreamResponse
from gemini_web_mcp_cli.core.music_presets import get_music_preset, list_music_presets


class MusicFormat(StrEnum):
    """Download format for generated music tracks."""

    AUDIO = "audio"  # MP3 audio only
    VIDEO = "video"  # MP4 with cover art


class MusicService:
    """Service for music generation using Lyria 3.5.

    Music generation completes within a single StreamGenerate call — no polling
    needed. The tool is activated by setting inner_req_list[49] = 21. The response
    streams back in ~16 frames over ~30 seconds, with music data at
    candidate_data[12][86].
    """

    def __init__(self, client: GeminiClient):
        self.client = client

    async def generate(
        self,
        prompt: str,
        model: str | None = None,
        style: str | None = None,
        length: str | None = None,
        vocals: str | None = None,
        genre: str | None = None,
        template: str | None = None,
    ) -> StreamResponse:
        """Generate a music track from a text prompt.

        Music generation completes within the StreamGenerate response (no polling).
        The response contains MP3, MP4, metadata, lyrics, and cover art info at
        candidate_data[12][86].

        The Lyria 3.5 composer exposes Length, Vocals, and Genre controls plus
        template cards. These are driven through Chrome's UI so the signed
        request body carries the selections.

        Args:
            prompt: Text description of the music to generate.
            model: Optional model name (pro, flash, thinking).
            style: Optional legacy style preset name (e.g., "8-bit", "k-pop",
                   "emo"). Use list_styles() to see available presets.
            length: "short" or "standard".
            vocals: "custom" (from prompt), "vocals" (vocals on), or
                    "instrumental".
            genre: Genre name, e.g. "pop", "hip-hop & rap", "rock", "k-pop",
                   "latin", "electronic", "r&b", "country", "afrobeats",
                   "reggae", "jazz & blues", "classical", "folk", "lo-fi",
                   "acoustic", "cinematic", "ambient". "custom" leaves the
                   genre based on the prompt.
            template: Optional music template name (e.g. "Soundscape",
                      "Intro music", "Brand jingle", "Rap battle").

        Raises:
            ValueError: If a style preset, length, vocals, or genre is unknown.
        """
        preset = None
        if style:
            preset = get_music_preset(style)
            if preset is None:
                available = ", ".join(list_music_presets())
                raise ValueError(
                    f"Unknown music style '{style}'. "
                    f"Available styles: {available}"
                )

        return await self.client.send(
            prompt=prompt,
            model=model,
            tool_id=MUSIC_TOOL_ID,
            style_preset=preset,
            music_length=normalize_music_length(length),
            music_vocals=normalize_music_vocals(vocals),
            music_genre=normalize_music_genre(genre),
            template=template,
        )

    @staticmethod
    def list_styles() -> list[str]:
        """Return sorted list of available music style preset names."""
        return list_music_presets()

    async def download(
        self,
        url: str,
        output_path: str | Path,
        fmt: MusicFormat = MusicFormat.AUDIO,
    ) -> Path:
        """Download a generated music track to a local file.

        Uses CDP page fetch (JavaScript fetch from Gemini page context)
        to bypass partitioned cookie restrictions. Falls back to httpx
        if Chrome is unavailable.

        Args:
            url: The audio or video URL from the completed generation response.
            output_path: Local path to save the file.
            fmt: MusicFormat.AUDIO for MP3, MusicFormat.VIDEO for MP4 with cover art.

        Returns:
            Path to the saved file.
        """
        logger.debug(f"Downloading music ({fmt.value}): {url[:80]}...")
        result = await self.client.download_media(
            url=url, output_path=output_path, timeout=60.0,
        )
        logger.info(f"Music track saved to {result} (format: {fmt.value})")
        return result
