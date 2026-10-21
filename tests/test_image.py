"""Tests for image generation (Nano Banana) support."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from gemini_web_mcp_cli.core.models import StreamResponse
from gemini_web_mcp_cli.services.image import ImageService


class TestImageServiceGenerate:
    async def test_generate_defaults_to_pro_model(self):
        mock_client = MagicMock()
        mock_client.send = AsyncMock(return_value=StreamResponse(text="Generating..."))
        svc = ImageService(mock_client)
        await svc.generate("A serene mountain landscape")
        kwargs = mock_client.send.call_args.kwargs
        assert kwargs["model"] == "pro"
        assert kwargs["tool_id"] == 14
        assert kwargs["force_token_factory"] is True
        assert kwargs["image_aspect"] is None

    async def test_generate_with_flash_model(self):
        mock_client = MagicMock()
        mock_client.send = AsyncMock(return_value=StreamResponse())
        svc = ImageService(mock_client)
        await svc.generate("A poster", model="flash")
        assert mock_client.send.call_args.kwargs["model"] == "flash"

    async def test_generate_passes_aspect(self):
        mock_client = MagicMock()
        mock_client.send = AsyncMock(return_value=StreamResponse())
        svc = ImageService(mock_client)
        await svc.generate("A vertical poster", aspect="9:16")
        assert mock_client.send.call_args.kwargs["image_aspect"] == "9:16"

    async def test_generate_normalizes_aspect_aliases(self):
        mock_client = MagicMock()
        mock_client.send = AsyncMock(return_value=StreamResponse())
        svc = ImageService(mock_client)

        await svc.generate("square image", aspect="square")
        assert mock_client.send.call_args.kwargs["image_aspect"] == "1:1"

        await svc.generate("wide image", aspect="landscape")
        assert mock_client.send.call_args.kwargs["image_aspect"] == "16:9"

    async def test_generate_rejects_unknown_aspect(self):
        mock_client = MagicMock()
        svc = ImageService(mock_client)
        with pytest.raises(ValueError, match="Unknown image aspect ratio"):
            await svc.generate("test", aspect="5:4")


class TestEncodeForPath:
    """Gemini serves JPEG; the saved bytes must match the requested extension."""

    def _jpeg(self) -> bytes:
        from io import BytesIO

        from PIL import Image

        buf = BytesIO()
        Image.new("RGB", (8, 8), (200, 30, 30)).save(buf, format="JPEG")
        return buf.getvalue()

    def test_jpeg_saved_as_png_is_converted(self, monkeypatch):
        from pathlib import Path

        from gemini_web_mcp_cli.services import image

        monkeypatch.setattr(image, "_image_processor", None)
        out = image._encode_for_path(self._jpeg(), Path("poster.png"))
        assert out.startswith(b"\x89PNG")

    def test_matching_format_is_untouched(self, monkeypatch):
        from pathlib import Path

        from gemini_web_mcp_cli.services import image

        monkeypatch.setattr(image, "_image_processor", None)
        raw = self._jpeg()
        assert image._encode_for_path(raw, Path("a.jpg")) is raw
        assert image._encode_for_path(raw, Path("a.bin")) is raw

    def test_unreadable_bytes_are_kept(self, monkeypatch):
        from pathlib import Path

        from gemini_web_mcp_cli.services import image

        monkeypatch.setattr(image, "_image_processor", None)
        assert image._encode_for_path(b"not an image", Path("a.png")) == b"not an image"
