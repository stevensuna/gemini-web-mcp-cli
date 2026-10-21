"""Tests for music generation (Lyria 3) support."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from gemini_web_mcp_cli.core.constants import MUSIC_TOOL_ID
from gemini_web_mcp_cli.core.exceptions import APIError, MusicGenerationError
from gemini_web_mcp_cli.core.models import Candidate, StreamResponse
from gemini_web_mcp_cli.core.music_presets import (
    MUSIC_PRESETS,
    PRESET_ALIASES,
    build_preset_file_data,
    get_music_preset,
    list_music_presets,
)
from gemini_web_mcp_cli.core.parser import parse_stream_response
from gemini_web_mcp_cli.core.rpc import build_stream_response, build_streamgenerate_body
from gemini_web_mcp_cli.services.music import MusicFormat, MusicService

# ── MusicFormat enum ───────────────────────────────────────────────────────


class TestMusicFormat:
    def test_audio_value(self):
        assert MusicFormat.AUDIO == "audio"

    def test_video_value(self):
        assert MusicFormat.VIDEO == "video"

    def test_from_string_audio(self):
        assert MusicFormat("audio") == MusicFormat.AUDIO

    def test_from_string_video(self):
        assert MusicFormat("video") == MusicFormat.VIDEO

    def test_invalid_raises(self):
        with pytest.raises(ValueError):
            MusicFormat("wav")


# ── MusicGenerationError ──────────────────────────────────────────────────


class TestMusicGenerationError:
    def test_inherits_api_error(self):
        err = MusicGenerationError("test")
        assert isinstance(err, APIError)

    def test_error_code(self):
        err = MusicGenerationError("limit", error_code=1037)
        assert err.error_code == 1037

    def test_message(self):
        err = MusicGenerationError("something broke")
        assert str(err) == "something broke"


# ── MUSIC_TOOL_ID constant ──────────────────────────────────────────────


class TestMusicToolId:
    def test_value(self):
        assert MUSIC_TOOL_ID == 21


# ── StreamResponse.has_music ──────────────────────────────────────────────


class TestStreamResponseHasMusic:
    def test_has_music_true(self):
        candidate = Candidate(generated_music=[["track_data"]])
        response = StreamResponse(candidates=[candidate])
        assert response.has_music is True

    def test_has_music_false_no_music(self):
        candidate = Candidate(text="Hello")
        response = StreamResponse(candidates=[candidate])
        assert response.has_music is False

    def test_has_music_false_empty_candidates(self):
        response = StreamResponse()
        assert response.has_music is False

    def test_has_music_false_empty_list(self):
        candidate = Candidate(generated_music=[])
        response = StreamResponse(candidates=[candidate])
        assert response.has_music is False

    def test_has_music_multiple_candidates(self):
        c1 = Candidate(text="No music here")
        c2 = Candidate(generated_music=[["audio_url", "cover_url"]])
        response = StreamResponse(candidates=[c1, c2])
        assert response.has_music is True


# ── Candidate.generated_music field ───────────────────────────────────────


class TestCandidateMusic:
    def test_default_none(self):
        c = Candidate()
        assert c.generated_music is None

    def test_with_music_data(self):
        data = [["audio_url", "video_url", "cover_art_url"]]
        c = Candidate(generated_music=data)
        assert c.generated_music == data

    def test_coexists_with_images(self):
        c = Candidate(
            generated_images=[["img_url"]],
            generated_music=[["audio_url"]],
        )
        assert c.generated_images is not None
        assert c.generated_music is not None


# ── build_streamgenerate_body tool_id ────────────────────────────────────


class TestBuildStreamGenerateBodyToolId:
    def test_no_tool_id_default(self):
        """Without tool_id, inner[49] should remain None."""
        import json
        from urllib.parse import parse_qs

        body = build_streamgenerate_body(
            prompt="Hello",
            access_token="test_token",
        )
        parsed = parse_qs(body.rstrip("&"))
        f_req = json.loads(parsed["f.req"][0])
        inner = json.loads(f_req[1])
        assert inner[49] is None

    def test_music_tool_id(self):
        """With tool_id=21, inner[49] should be 21."""
        import json
        from urllib.parse import parse_qs

        body = build_streamgenerate_body(
            prompt="A song about cats",
            access_token="test_token",
            tool_id=MUSIC_TOOL_ID,
        )
        parsed = parse_qs(body.rstrip("&"))
        f_req = json.loads(parsed["f.req"][0])
        inner = json.loads(f_req[1])
        assert inner[49] == 21


# ── Parser: music extraction ─────────────────────────────────────────────


class TestParserMusicExtraction:
    """Test that parse_stream_response extracts generated_music from candidate data."""

    def _build_stream_frame(self, candidate_data):
        """Build a minimal StreamGenerate frame with candidate data."""
        import json

        inner = [None] * 30
        inner[1] = ["conv_id", "resp_id", ""]
        inner[4] = [candidate_data]
        inner[25] = True

        frame_json = json.dumps([["wrb.fr", None, json.dumps(inner)]])
        length = len(frame_json.encode("utf-16-le")) // 2
        return f"{length}\n{frame_json}"

    def test_extracts_music_data(self):
        """Music data at candidate[12][86] should be extracted."""
        # Build a candidate with music data at index [12][86]
        candidate = [None] * 40
        candidate[0] = "rc_test"
        candidate[1] = ["Generated a track"]
        # Build index 12 with music at sub-index 86
        index_12 = [None] * 87
        index_12[86] = [
            [None, ["mp3_data"]],
            [None, ["mp4_data"]],
            ["Track Title", None, "Album", None, "Pop"],
        ]
        candidate[12] = index_12

        content = self._build_stream_frame(candidate)
        results = parse_stream_response(content)
        assert len(results) > 0
        c = results[0]["candidates"][0]
        assert c["generated_music"] is not None
        assert c["generated_music"][2][0] == "Track Title"

    def test_no_music_data_returns_none(self):
        """Regular chat response should have generated_music = None."""
        candidate = [None] * 40
        candidate[0] = "rc_test"
        candidate[1] = ["Hello, world!"]

        content = self._build_stream_frame(candidate)
        results = parse_stream_response(content)
        assert len(results) > 0
        c = results[0]["candidates"][0]
        assert c["generated_music"] is None


# ── build_stream_response passes generated_music ─────────────────────────


class TestBuildStreamResponseMusic:
    """Test that build_stream_response() passes generated_music to Candidate."""

    def test_music_data_flows_to_candidate(self):
        """Music data from parsed frames should end up on the Candidate model."""
        import json

        music_data = [
            [None, ["mp3_data"]],
            [None, ["mp4_data"]],
            ["Song Title", None, "My Album", None, "Rock"],
        ]

        candidate = [None] * 40
        candidate[0] = "rc_music_test"
        candidate[1] = ["Here is your track"]

        index_12 = [None] * 87
        index_12[86] = music_data
        candidate[12] = index_12

        inner = [None] * 30
        inner[1] = ["c_test", "r_test", ""]
        inner[4] = [candidate]
        inner[25] = True

        frame_json = json.dumps([["wrb.fr", None, json.dumps(inner)]])
        length = len(frame_json.encode("utf-16-le")) // 2
        response_text = f"{length}\n{frame_json}"

        result = build_stream_response(response_text)
        assert result.has_music is True
        assert result.candidates[0].generated_music is not None
        assert result.candidates[0].generated_music[2][0] == "Song Title"

    def test_no_music_data(self):
        """Regular chat response should have has_music=False."""
        import json

        candidate = [None] * 40
        candidate[0] = "rc_chat_test"
        candidate[1] = ["Hello!"]

        inner = [None] * 30
        inner[1] = ["c_test", "r_test", ""]
        inner[4] = [candidate]
        inner[25] = True

        frame_json = json.dumps([["wrb.fr", None, json.dumps(inner)]])
        length = len(frame_json.encode("utf-16-le")) // 2
        response_text = f"{length}\n{frame_json}"

        result = build_stream_response(response_text)
        assert result.has_music is False


# ── MusicService ──────────────────────────────────────────────────────────


class TestMusicService:
    def test_init(self):
        mock_client = MagicMock()
        svc = MusicService(mock_client)
        assert svc.client is mock_client

    async def test_generate_passes_tool_id(self):
        """generate() should pass tool_id=MUSIC_TOOL_ID to client.send()."""
        mock_client = MagicMock()
        mock_client.send = AsyncMock(
            return_value=StreamResponse(text="Generating your track...")
        )
        svc = MusicService(mock_client)
        result = await svc.generate("A pop song about rain", model="flash")
        mock_client.send.assert_called_once_with(
            prompt="A pop song about rain",
            model="flash",
            tool_id=MUSIC_TOOL_ID,
            style_preset=None,
            music_length=None,
            music_vocals=None,
            music_genre=None,
            template=None,
        )
        assert result.text == "Generating your track..."

    async def test_generate_default_model(self):
        mock_client = MagicMock()
        mock_client.send = AsyncMock(return_value=StreamResponse())
        svc = MusicService(mock_client)
        await svc.generate("test prompt")
        mock_client.send.assert_called_once_with(
            prompt="test prompt",
            model=None,
            tool_id=MUSIC_TOOL_ID,
            style_preset=None,
            music_length=None,
            music_vocals=None,
            music_genre=None,
            template=None,
        )

    async def test_download_creates_file(self, tmp_path):
        mock_client = MagicMock()
        fake_audio = b"fake mp3 content"
        output_file = tmp_path / "subdir" / "track.mp3"

        async def fake_download(url, output_path, timeout=60.0):
            out = Path(output_path)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(fake_audio)
            return out

        mock_client.download_media = AsyncMock(side_effect=fake_download)
        svc = MusicService(mock_client)

        saved = await svc.download(
            "https://example.com/audio.mp3", output_file, fmt=MusicFormat.AUDIO
        )

        assert saved == output_file
        assert output_file.exists()
        assert output_file.read_bytes() == fake_audio

    async def test_download_video_format(self, tmp_path):
        mock_client = MagicMock()
        fake_video = b"fake mp4 content"
        output_file = tmp_path / "track.mp4"

        async def fake_download(url, output_path, timeout=60.0):
            out = Path(output_path)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(fake_video)
            return out

        mock_client.download_media = AsyncMock(side_effect=fake_download)
        svc = MusicService(mock_client)

        saved = await svc.download(
            "https://example.com/video.mp4", output_file, fmt=MusicFormat.VIDEO
        )

        assert saved == output_file
        assert output_file.read_bytes() == fake_video

    async def test_generate_with_style(self):
        """generate() with style should pass style_preset to client.send()."""
        mock_client = MagicMock()
        mock_client.send = AsyncMock(
            return_value=StreamResponse(text="8-bit track")
        )
        svc = MusicService(mock_client)
        await svc.generate("Cats playing games", style="8-bit")
        call_kwargs = mock_client.send.call_args.kwargs
        assert call_kwargs["tool_id"] == MUSIC_TOOL_ID
        assert call_kwargs["style_preset"] is not None
        assert call_kwargs["style_preset"]["id"] == "5YcQ7ninNzGzST8"

    async def test_generate_with_length(self):
        mock_client = MagicMock()
        mock_client.send = AsyncMock(return_value=StreamResponse())
        svc = MusicService(mock_client)
        await svc.generate("A short jingle", length="short")
        assert mock_client.send.call_args.kwargs["music_length"] == "Short"

    async def test_generate_with_vocals(self):
        mock_client = MagicMock()
        mock_client.send = AsyncMock(return_value=StreamResponse())
        svc = MusicService(mock_client)
        await svc.generate("A beat", vocals="instrumental")
        assert mock_client.send.call_args.kwargs["music_vocals"] == "Instrumental"

    async def test_generate_with_genre(self):
        mock_client = MagicMock()
        mock_client.send = AsyncMock(return_value=StreamResponse())
        svc = MusicService(mock_client)
        await svc.generate("A chill beat", genre="lo-fi")
        assert mock_client.send.call_args.kwargs["music_genre"] == "Lo-fi"

    async def test_generate_with_template(self):
        mock_client = MagicMock()
        mock_client.send = AsyncMock(return_value=StreamResponse())
        svc = MusicService(mock_client)
        await svc.generate("A brand jingle", template="Brand jingle")
        assert mock_client.send.call_args.kwargs["template"] == "Brand jingle"

    async def test_generate_rejects_unknown_length(self):
        import pytest

        mock_client = MagicMock()
        svc = MusicService(mock_client)
        with pytest.raises(ValueError, match="Unknown music length"):
            await svc.generate("test", length="epic")

    async def test_generate_rejects_unknown_genre(self):
        import pytest

        mock_client = MagicMock()
        svc = MusicService(mock_client)
        with pytest.raises(ValueError, match="Unknown music genre"):
            await svc.generate("test", genre="polka")

    async def test_generate_with_alias(self):
        """generate() should resolve style aliases."""
        mock_client = MagicMock()
        mock_client.send = AsyncMock(return_value=StreamResponse())
        svc = MusicService(mock_client)
        await svc.generate("test", style="rap")
        call_kwargs = mock_client.send.call_args.kwargs
        assert call_kwargs["style_preset"]["name"] == "90's rap"

    async def test_generate_invalid_style_raises(self):
        """generate() should raise ValueError for unknown style."""
        mock_client = MagicMock()
        svc = MusicService(mock_client)
        with pytest.raises(ValueError, match="Unknown music style"):
            await svc.generate("test", style="nonexistent-style")

    async def test_generate_no_style(self):
        """generate() without style should not pass style_preset."""
        mock_client = MagicMock()
        mock_client.send = AsyncMock(return_value=StreamResponse())
        svc = MusicService(mock_client)
        await svc.generate("test prompt")
        call_kwargs = mock_client.send.call_args.kwargs
        assert call_kwargs["style_preset"] is None

    def test_list_styles(self):
        """list_styles() should return sorted preset names."""
        styles = MusicService.list_styles()
        assert isinstance(styles, list)
        assert len(styles) == 16
        assert styles == sorted(styles)
        assert "8-bit" in styles
        assert "k-pop" in styles


# ── Music presets module ──────────────────────────────────────────────────


class TestMusicPresets:
    def test_all_16_presets(self):
        assert len(MUSIC_PRESETS) == 16

    def test_preset_keys(self):
        expected = {
            "90s-rap", "latin-pop", "folk-ballad", "8-bit", "workout",
            "reggaeton", "rnb-romance", "kawaii-metal", "cinematic", "emo",
            "afropop", "forest-bath", "k-pop", "birthday-roast",
            "folk-a-cappella", "bad-music",
        }
        assert set(MUSIC_PRESETS.keys()) == expected

    def test_preset_has_required_fields(self):
        for key, preset in MUSIC_PRESETS.items():
            assert "id" in preset, f"{key} missing 'id'"
            assert "name" in preset, f"{key} missing 'name'"
            assert "image_url" in preset, f"{key} missing 'image_url'"
            assert "audio_url" in preset, f"{key} missing 'audio_url'"
            assert "system_prompt" in preset, f"{key} missing 'system_prompt'"

    def test_preset_ids_unique(self):
        ids = [p["id"] for p in MUSIC_PRESETS.values()]
        assert len(ids) == len(set(ids))

    def test_get_music_preset_direct(self):
        preset = get_music_preset("8-bit")
        assert preset is not None
        assert preset["name"] == "8-bit"

    def test_get_music_preset_alias(self):
        preset = get_music_preset("rap")
        assert preset is not None
        assert preset["name"] == "90's rap"

    def test_get_music_preset_case_insensitive(self):
        preset = get_music_preset("K-POP")
        assert preset is not None
        assert preset["name"] == "K-pop"

    def test_get_music_preset_not_found(self):
        assert get_music_preset("doesnotexist") is None

    def test_list_music_presets_sorted(self):
        presets = list_music_presets()
        assert presets == sorted(presets)
        assert len(presets) == 16

    def test_aliases_resolve(self):
        for alias, target in PRESET_ALIASES.items():
            assert target in MUSIC_PRESETS, f"Alias '{alias}' -> '{target}' not in MUSIC_PRESETS"

    def test_build_preset_file_data_structure(self):
        preset = MUSIC_PRESETS["8-bit"]
        file_data = build_preset_file_data(preset)

        # Should be a 7-element list (indices 0-6)
        assert len(file_data) == 7
        # First 6 elements are None
        for i in range(6):
            assert file_data[i] is None
        # Index 6 is the preset container
        container = file_data[6]
        assert container[0] is None
        assert container[1] is None
        assert container[2] == []
        assert container[3] == preset["id"]
        # Inner preset data
        inner = container[4]
        assert inner[0] == preset["id"]
        assert inner[1] == preset["name"]
        assert inner[2] == [[preset["image_url"], 1], [preset["audio_url"], 3]]
        assert inner[3] == preset["system_prompt"]


# ── build_streamgenerate_body with style_preset ──────────────────────────


class TestBuildStreamGenerateBodyStylePreset:
    def test_no_style_preset_default(self):
        """Without style_preset, inner[0] should have 7 elements."""
        import json
        from urllib.parse import parse_qs

        body = build_streamgenerate_body(
            prompt="Hello",
            access_token="test_token",
        )
        parsed = parse_qs(body.rstrip("&"))
        f_req = json.loads(parsed["f.req"][0])
        inner = json.loads(f_req[1])
        assert len(inner[0]) == 7

    def test_with_style_preset_extends_inner0(self):
        """With style_preset, inner[0] should have 10 elements."""
        import json
        from urllib.parse import parse_qs

        preset = MUSIC_PRESETS["8-bit"]
        body = build_streamgenerate_body(
            prompt="Cats playing games",
            access_token="test_token",
            tool_id=MUSIC_TOOL_ID,
            style_preset=preset,
        )
        parsed = parse_qs(body.rstrip("&"))
        f_req = json.loads(parsed["f.req"][0])
        inner = json.loads(f_req[1])
        # inner[0] should now have 10 elements (7 original + 3 extended: None, None, preset_data)
        assert len(inner[0]) == 10
        # inner[0][7] and inner[0][8] are None (padding)
        assert inner[0][7] is None
        assert inner[0][8] is None
        # inner[0][9] is the preset file data
        preset_data = inner[0][9]
        assert preset_data is not None
        # Verify the preset container structure
        assert preset_data[6][3] == "5YcQ7ninNzGzST8"  # preset_id
        assert preset_data[6][4][1] == "8-bit"  # preset name

    def test_style_preset_with_tool_id(self):
        """Both style_preset and tool_id should coexist."""
        import json
        from urllib.parse import parse_qs

        preset = MUSIC_PRESETS["k-pop"]
        body = build_streamgenerate_body(
            prompt="summer vibes",
            access_token="test_token",
            tool_id=MUSIC_TOOL_ID,
            style_preset=preset,
        )
        parsed = parse_qs(body.rstrip("&"))
        f_req = json.loads(parsed["f.req"][0])
        inner = json.loads(f_req[1])
        # tool_id at inner[49]
        assert inner[49] == 21
        # style preset at inner[0][9]
        assert inner[0][9] is not None
        assert inner[0][9][6][4][1] == "K-pop"
