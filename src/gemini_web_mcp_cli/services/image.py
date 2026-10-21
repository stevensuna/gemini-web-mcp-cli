"""Image service: generate and download images via Gemini."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Callable

import httpx
from loguru import logger

from gemini_web_mcp_cli.core.client import GeminiClient
from gemini_web_mcp_cli.core.constants import (
    CHROME_USER_AGENT,
    CONFIG_DIR_NAME,
    IMAGE_TOOL_ID,
    normalize_image_aspect,
)
from gemini_web_mcp_cli.core.exceptions import GeminiError
from gemini_web_mcp_cli.core.models import StreamResponse


def _load_image_processor() -> Callable[[bytes], bytes] | None:
    """Load optional image post-processor from plugins directory."""
    plugin = Path.home() / CONFIG_DIR_NAME / "plugins" / "clean_image.py"
    if not plugin.is_file():
        return None
    try:
        spec = importlib.util.spec_from_file_location("clean_image", plugin)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        fn = getattr(mod, "process_image", None)
        if callable(fn):
            logger.debug("Loaded image processor plugin from {}", plugin)
            return fn
        logger.warning("Plugin {} missing process_image() function", plugin)
    except ImportError as e:
        logger.error("Image processor plugin requires Pillow: pip install Pillow ({})", e)
    except Exception as e:
        logger.warning("Failed to load image processor plugin: {}", e)
    return None


_image_processor = _load_image_processor()

# File extension -> Pillow format name. Gemini serves JPEG; a caller asking for
# "poster.png" should get a PNG, not JPEG bytes with a .png name.
_EXT_FORMATS = {".png": "PNG", ".jpg": "JPEG", ".jpeg": "JPEG", ".webp": "WEBP"}


def _encode_for_path(raw: bytes, output: Path) -> bytes:
    """Post-process image bytes and convert them to the format ``output`` names."""
    data = _image_processor(raw) if _image_processor else raw
    target = _EXT_FORMATS.get(output.suffix.lower())
    if not target:
        return data
    try:
        from io import BytesIO

        from PIL import Image

        with Image.open(BytesIO(data)) as img:
            if img.format == target:
                return data
            if target == "JPEG" and img.mode not in ("RGB", "L"):
                img = img.convert("RGB")
            buf = BytesIO()
            img.save(buf, format=target, **({"quality": 95} if target == "JPEG" else {}))
            logger.debug(f"Converted image {img.format} -> {target} for {output.name}")
            return buf.getvalue()
    except Exception as e:  # never lose the download over a conversion problem
        logger.warning(f"Could not convert image to {target} ({e}); saving original bytes")
        return data

# Headers that match a real browser for Google CDN downloads
_DOWNLOAD_HEADERS = {
    "User-Agent": CHROME_USER_AGENT,
    "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://gemini.google.com/",
    "Sec-Fetch-Dest": "image",
    "Sec-Fetch-Mode": "no-cors",
    "Sec-Fetch-Site": "cross-site",
}


class ImageService:
    """Service for image generation and management.

    Image generation goes through the standard StreamGenerate endpoint.
    Requires BotGuard token (Token Factory) for reliable image generation.
    The model decides to generate images based on the prompt content.
    """

    def __init__(self, client: GeminiClient):
        self.client = client

    async def generate(
        self,
        prompt: str,
        model: str | None = None,
        aspect: str | None = None,
    ) -> StreamResponse:
        """Generate an image from a text prompt.

        Uses tool_id=14 (IMAGE_TOOL_ID) to explicitly activate image routing.
        BotGuard token is required (force_token_factory=True).

        Two quality tiers:
        - "pro" (default): Nano Banana Pro (Gemini 3 Pro Image) — for Pro/Ultra
          subscribers, high fidelity. Default because image generation requires
          Gemini Advanced on most accounts.
        - "flash": Nano Banana 2 (Gemini 3.1 Flash Image) —
          Pro-level quality at Flash speed, accurate text rendering.
          Only works on accounts with Flash image gen enabled.

        Args:
            aspect: Optional aspect ratio — "1:1", "9:16", "3:4", "4:3", or
                    "16:9". Aliases like "square", "portrait", "landscape" are
                    accepted. When None, Gemini's default is used.
        """
        return await self.client.send(
            prompt=prompt,
            model=model or "pro",
            tool_id=IMAGE_TOOL_ID,
            force_token_factory=True,
            image_aspect=normalize_image_aspect(aspect),
        )

    async def download(
        self,
        image_url: str,
        output_path: str | Path,
    ) -> Path:
        """Download a generated image to a local file.

        Tries CDP page fetch first (for partitioned cookie support),
        then falls back to httpx with domain-aware cookies.
        """
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)

        # Request at >=1025px so the watermark matches the 96px alpha map.
        # The browser always loads images at display resolution (>1024),
        # so the watermark plugin's 96px map expects that size.
        if "=s" not in image_url and "=w" not in image_url:
            image_url = f"{image_url}=s1536"

        logger.debug(f"Downloading image: {image_url[:80]}...")

        # Try CDP page fetch first
        try:
            raw = await self.client._download_via_cdp(image_url, timeout=30)
            output.write_bytes(_encode_for_path(raw, output))
            logger.info(f"Image saved via browser: {output}")
            return output
        except Exception as e:
            logger.debug(f"CDP image download unavailable, using httpx: {e}")

        # Fallback: httpx with domain-aware cookies
        max_retries = 1
        for attempt in range(max_retries + 1):
            cookies = self.client.get_httpx_cookies()
            timeout = httpx.Timeout(connect=10.0, read=30.0, write=30.0, pool=30.0)

            async with httpx.AsyncClient(
                http2=True,
                cookies=cookies,
                headers=_DOWNLOAD_HEADERS,
                follow_redirects=True,
                timeout=timeout,
            ) as client:
                response = await client.get(image_url)

                content_type = response.headers.get("content-type", "").lower()
                if "text/html" in content_type:
                    # Stale cookie / Token Factory drift resulting in login wall.
                    if attempt < max_retries:
                        logger.debug(
                            "Image download redirected to login. "
                            "Refreshing cookies via CDP for retry..."
                        )
                        refreshed = await self.client._ensure_browser_cookies()
                        if refreshed:
                            continue

                    raise GeminiError(
                        "Image download redirected to login page. "
                        "Run 'gemcli login' to refresh credentials."
                    )

                response.raise_for_status()
                raw = response.content
                output.write_bytes(_encode_for_path(raw, output))

            logger.info(f"Image saved to {output}")
            return output
