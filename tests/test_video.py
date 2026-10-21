"""Tests for video generation (Veo 3.1) support."""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from gemini_web_mcp_cli.core.exceptions import APIError, VideoGenerationError
from gemini_web_mcp_cli.core.models import Candidate, StreamResponse
from gemini_web_mcp_cli.core.parser import parse_stream_response
from gemini_web_mcp_cli.core.rpc import build_stream_response
from gemini_web_mcp_cli.services.video import (
    VideoService,
    extract_video_metadata,
    extract_video_url,
)

# ── VideoGenerationError ──────────────────────────────────────────────────


class TestVideoGenerationError:
    def test_inherits_api_error(self):
        err = VideoGenerationError("test")
        assert isinstance(err, APIError)

    def test_error_code(self):
        err = VideoGenerationError("limit", error_code=1037)
        assert err.error_code == 1037

    def test_message(self):
        err = VideoGenerationError("something broke")
        assert str(err) == "something broke"


# ── StreamResponse.has_video ──────────────────────────────────────────────


class TestStreamResponseHasVideo:
    def test_has_video_true(self):
        candidate = Candidate(generated_video=[["video_data"]])
        response = StreamResponse(candidates=[candidate])
        assert response.has_video is True

    def test_has_video_false_no_video(self):
        candidate = Candidate(text="Hello")
        response = StreamResponse(candidates=[candidate])
        assert response.has_video is False

    def test_has_video_false_empty_candidates(self):
        response = StreamResponse()
        assert response.has_video is False

    def test_has_video_false_empty_list(self):
        candidate = Candidate(generated_video=[])
        response = StreamResponse(candidates=[candidate])
        assert response.has_video is False

    def test_has_video_multiple_candidates(self):
        c1 = Candidate(text="No video here")
        c2 = Candidate(generated_video=[["track_data"]])
        response = StreamResponse(candidates=[c1, c2])
        assert response.has_video is True


# ── Candidate.generated_video field ───────────────────────────────────────


class TestCandidateVideo:
    def test_default_none(self):
        c = Candidate()
        assert c.generated_video is None

    def test_with_video_data(self):
        data = [[[["track_info"]]]]
        c = Candidate(generated_video=data)
        assert c.generated_video == data

    def test_coexists_with_images_and_music(self):
        c = Candidate(
            generated_images=[["img_url"]],
            generated_music=[["audio_url"]],
            generated_video=[["video_data"]],
        )
        assert c.generated_images is not None
        assert c.generated_music is not None
        assert c.generated_video is not None


# ── extract_video_url ──────────────────────────────────────────────────────


class TestExtractVideoUrl:
    def test_extracts_url(self):
        # video_data[0][0][0][0][7][1] = download URL
        # Structure: entries > entry > [tracks, metadata, safety] > track > URLs
        video_data = [
            [  # entries wrapper
                [  # entry: [tracks, metadata, ...]
                    [  # tracks array
                        [  # actual track data
                            None, None, None, None, None, None, None,
                            [  # URLs: [preview, download, preview2]
                                "https://preview.example.com/video",
                                "https://contribution.usercontent.google.com/download?c=abc",
                                "https://preview2.example.com/video",
                            ],
                        ],
                    ],
                ],
            ],
        ]
        url = extract_video_url(video_data)
        assert url == "https://contribution.usercontent.google.com/download?c=abc"

    def test_returns_none_on_empty(self):
        assert extract_video_url([]) is None
        assert extract_video_url(None) is None

    def test_returns_none_on_bad_structure(self):
        assert extract_video_url([[[]]]) is None
        assert extract_video_url([[[None]]]) is None


# ── extract_video_metadata ─────────────────────────────────────────────────


class TestExtractVideoMetadata:
    def _build_video_data(self):
        """Build realistic video data matching the captured structure.

        Structure: video_data[0][0] = entry = [tracks, metadata, safety]
        - video_data[0][0][0]    = tracks array
        - video_data[0][0][0][0] = actual track data
        - video_data[0][0][1]    = metadata array
        """
        track = [None] * 18
        track[7] = ["preview_url", "download_url", "preview2_url"]
        track[11] = "video/mp4"
        track[17] = [[8], 1280, 720]  # duration=8s, 1280x720

        metadata = [
            "A sunset on the beach with waves",  # description
            None,
            [None, None, "models/veo-3.1-fast-generate-002"],  # model
            None, None, None, None,
            ["Scene: A beautiful sunset over the ocean"],  # scene
        ]

        # video_data[0]          = entries wrapper
        # video_data[0][0]       = entry: [tracks, metadata]
        # video_data[0][0][0]    = tracks array
        # video_data[0][0][0][0] = actual track
        # video_data[0][0][1]    = metadata
        return [[[
            [track],    # entry[0] = tracks array, tracks[0] = track
            metadata,   # entry[1] = metadata
        ]]]

    def test_extracts_metadata(self):
        video_data = self._build_video_data()
        meta = extract_video_metadata(video_data)
        assert meta is not None
        assert meta["description"] == "A sunset on the beach with waves"
        assert meta["model"] == "models/veo-3.1-fast-generate-002"
        assert meta["mime_type"] == "video/mp4"
        assert meta["duration_seconds"] == 8
        assert meta["width"] == 1280
        assert meta["height"] == 720
        assert meta["orientation"] == "landscape"

    def test_detects_portrait_orientation(self):
        """Portrait videos (h > w) should report portrait orientation."""
        track = [None] * 18
        track[11] = "video/mp4"
        track[17] = [[10], 720, 1280]
        metadata = ["A vertical video"]
        video_data = [[[[track], metadata]]]
        meta = extract_video_metadata(video_data)
        assert meta is not None
        assert meta["orientation"] == "portrait"

    def test_extracts_scene(self):
        video_data = self._build_video_data()
        meta = extract_video_metadata(video_data)
        assert "scene" in meta
        assert "sunset" in meta["scene"].lower()

    def test_returns_none_on_empty(self):
        assert extract_video_metadata([]) is None
        assert extract_video_metadata(None) is None

    def test_partial_metadata(self):
        """Should still work if some fields are missing."""
        track = [None] * 18
        track[11] = "video/mp4"
        # video_data[0][0] = entry: [tracks, metadata]
        video_data = [[[[track], [None]]]]
        meta = extract_video_metadata(video_data)
        assert meta is not None
        assert meta["mime_type"] == "video/mp4"


# ── Parser: video extraction ────────────────────────────────────────────


class TestParserVideoExtraction:
    """Test that parse_stream_response extracts generated_video from candidate data."""

    def _build_stream_frame(self, candidate_data):
        """Build a minimal StreamGenerate frame with candidate data."""
        inner = [None] * 30
        inner[1] = ["conv_id", "resp_id", ""]
        inner[4] = [candidate_data]
        inner[25] = True

        frame_json = json.dumps([["wrb.fr", None, json.dumps(inner)]])
        length = len(frame_json.encode("utf-16-le")) // 2
        return f"{length}\n{frame_json}"

    def test_extracts_video_data(self):
        """Video data at candidate[12][59] should be extracted."""
        candidate = [None] * 40
        candidate[0] = "rc_test"
        candidate[1] = ["Here is your video"]
        # Build index 12 with video at sub-index 59
        # Real structure: entries > entry > [tracks, metadata] > track
        index_12 = [None] * 60
        index_12[59] = [
            [  # entries wrapper
                [  # entry: [tracks, metadata]
                    [  # tracks array
                        [None, None, None, None, None, None, None,
                         ["preview", "download_url", "preview2"],
                         None, None, None, "video/mp4"],
                    ],
                    ["Description", None, [None, None, "veo-3.1"]],
                ],
            ],
        ]
        candidate[12] = index_12

        content = self._build_stream_frame(candidate)
        results = parse_stream_response(content)
        assert len(results) > 0
        c = results[0]["candidates"][0]
        assert c["generated_video"] is not None
        assert c["generated_video"][0][0][0][0][7][1] == "download_url"

    def test_no_video_data_returns_none(self):
        """Regular chat response should have generated_video = None."""
        candidate = [None] * 40
        candidate[0] = "rc_test"
        candidate[1] = ["Hello, world!"]

        content = self._build_stream_frame(candidate)
        results = parse_stream_response(content)
        assert len(results) > 0
        c = results[0]["candidates"][0]
        assert c["generated_video"] is None


# ── build_stream_response passes generated_video ─────────────────────────


class TestBuildStreamResponseVideo:
    """Test that build_stream_response() passes generated_video to Candidate."""

    def _build_frame(self, candidate, metadata=None):
        """Build a complete frame from candidate data."""
        inner = [None] * 30
        inner[1] = metadata or ["c_test", "r_test", ""]
        inner[4] = [candidate]
        inner[25] = True

        frame_json = json.dumps([["wrb.fr", None, json.dumps(inner)]])
        length = len(frame_json.encode("utf-16-le")) // 2
        return f"{length}\n{frame_json}"

    def test_video_data_flows_to_candidate(self):
        """Video data from parsed frames should end up on the Candidate model."""
        video_data = [
            [  # entries wrapper
                [  # entry: [tracks, metadata]
                    [  # tracks array
                        [None, None, None, None, None, None, None,
                         ["preview", "https://download.example.com/video.mp4", "preview2"]],
                    ],
                    ["A sunset video"],
                ],
            ],
        ]

        candidate = [None] * 40
        candidate[0] = "rc_video_test"
        candidate[1] = ["Here is your video"]
        index_12 = [None] * 60
        index_12[59] = video_data
        candidate[12] = index_12

        response_text = self._build_frame(candidate)
        result = build_stream_response(response_text)
        assert result.has_video is True
        assert result.candidates[0].generated_video is not None
        url = extract_video_url(result.candidates[0].generated_video)
        assert url == "https://download.example.com/video.mp4"

    def test_no_video_data(self):
        """Regular chat response should have has_video=False."""
        candidate = [None] * 40
        candidate[0] = "rc_chat_test"
        candidate[1] = ["Hello!"]

        response_text = self._build_frame(candidate)
        result = build_stream_response(response_text)
        assert result.has_video is False


# ── Frame merge preserves media data ─────────────────────────────────────


class TestFrameMergePreservesMedia:
    """Test that build_stream_response preserves media data across frames.

    This is the critical fix for the music has_music=false bug:
    when a later frame has candidates WITHOUT media data, the earlier
    frame's media data should be preserved.
    """

    def _build_frame(self, candidate, is_complete=False):
        """Build a frame from candidate data.

        Frame format: {length}\n{json} where length counts the \n + json
        in UTF-16 code units (the newline IS counted in the length per
        Google's protocol — see parser.py comment).
        """
        inner = [None] * 30
        inner[1] = ["c_test", "r_test", ""]
        inner[4] = [candidate]
        if is_complete:
            inner[25] = True
        frame_json = json.dumps([["wrb.fr", None, json.dumps(inner)]])
        # Length includes the \n separator (it's part of the content)
        frame_content = f"\n{frame_json}"
        length = len(frame_content.encode("utf-16-le")) // 2
        return f"{length}{frame_content}"

    def test_preserves_video_data_across_frames(self):
        """Video data from frame 1 should survive when frame 2 has no video."""
        # Frame 1: candidate with video data
        # Real structure: entries > entry > [tracks, metadata] > track
        video_data = [
            [[[  # entries > entry > tracks
                [None, None, None, None, None, None, None,
                 ["preview", "https://download.example.com/video.mp4"]],
            ]]],
        ]
        c1 = [None] * 40
        c1[0] = "rc_1"
        c1[1] = ["Video ready"]
        index_12 = [None] * 60
        index_12[59] = video_data
        c1[12] = index_12
        frame1 = self._build_frame(c1)

        # Frame 2: candidate WITHOUT video data (text-only update)
        c2 = [None] * 40
        c2[0] = "rc_1"
        c2[1] = ["Video ready - updated text"]
        frame2 = self._build_frame(c2, is_complete=True)

        response_text = frame1 + frame2
        result = build_stream_response(response_text)

        # Video data from frame 1 should be preserved
        assert result.has_video is True
        assert result.candidates[0].generated_video is not None
        url = extract_video_url(result.candidates[0].generated_video)
        assert url == "https://download.example.com/video.mp4"

    def test_preserves_music_data_across_frames(self):
        """Music data from frame 1 should survive when frame 2 has no music."""
        # Frame 1: candidate with music data
        music_data = [
            [None, ["mp3_url"]],
            [None, ["mp4_url"]],
            ["Song Title"],
        ]
        c1 = [None] * 40
        c1[0] = "rc_1"
        c1[1] = ["Music ready"]
        index_12 = [None] * 87
        index_12[86] = music_data
        c1[12] = index_12
        frame1 = self._build_frame(c1)

        # Frame 2: candidate WITHOUT music data
        c2 = [None] * 40
        c2[0] = "rc_1"
        c2[1] = ["Music ready - final"]
        frame2 = self._build_frame(c2, is_complete=True)

        response_text = frame1 + frame2
        result = build_stream_response(response_text)

        assert result.has_music is True
        assert result.candidates[0].generated_music is not None
        assert result.candidates[0].generated_music[2][0] == "Song Title"

    def test_preserves_image_data_across_frames(self):
        """Image data from frame 1 should survive when frame 2 has no images."""
        # Frame 1: candidate with image data
        image_data = [["https://img.example.com/image1.png", 512, 512]]
        c1 = [None] * 40
        c1[0] = "rc_1"
        c1[1] = ["Image ready"]
        index_12 = [None] * 10
        index_12[7] = [image_data]
        c1[12] = index_12
        frame1 = self._build_frame(c1)

        # Frame 2: candidate WITHOUT image data
        c2 = [None] * 40
        c2[0] = "rc_1"
        c2[1] = ["Image ready - final"]
        frame2 = self._build_frame(c2, is_complete=True)

        response_text = frame1 + frame2
        result = build_stream_response(response_text)

        assert result.candidates[0].generated_images is not None
        assert len(result.candidates[0].generated_images) > 0

    def test_later_frame_can_update_media(self):
        """If a later frame has different media data, it should replace the old one."""
        # Frame 1: candidate with video data (URL v1)
        # Real structure: entries > entry > [tracks] > track
        video_v1 = [
            [[[[None, None, None, None, None, None, None,
                ["preview", "https://example.com/v1.mp4"]]]]],
        ]
        c1 = [None] * 40
        c1[0] = "rc_1"
        c1[1] = ["Video v1"]
        index_12 = [None] * 60
        index_12[59] = video_v1
        c1[12] = index_12
        frame1 = self._build_frame(c1)

        # Frame 2: candidate with DIFFERENT video data (URL v2)
        video_v2 = [
            [[[[None, None, None, None, None, None, None,
                ["preview", "https://example.com/v2.mp4"]]]]],
        ]
        c2 = [None] * 40
        c2[0] = "rc_1"
        c2[1] = ["Video v2"]
        index_12_v2 = [None] * 60
        index_12_v2[59] = video_v2
        c2[12] = index_12_v2
        frame2 = self._build_frame(c2, is_complete=True)

        response_text = frame1 + frame2
        result = build_stream_response(response_text)

        # Should use the LATEST video data
        url = extract_video_url(result.candidates[0].generated_video)
        assert url == "https://example.com/v2.mp4"


# ── VideoService ──────────────────────────────────────────────────────────


class TestVideoService:
    def test_init(self):
        mock_client = MagicMock()
        svc = VideoService(mock_client)
        assert svc.client is mock_client
        assert svc._cid is None

    async def test_generate_sends_prompt(self):
        """generate() should call client.send() with prompt, tool_id=11, and force Token Factory."""
        mock_client = MagicMock()
        mock_client.send = AsyncMock(
            return_value=StreamResponse(text="Generating your video...")
        )
        svc = VideoService(mock_client)
        result = await svc.generate("A sunset on the beach", model="flash")
        mock_client.send.assert_called_once_with(
            prompt="A sunset on the beach",
            model="flash",
            tool_id=11,
            force_token_factory=True,
            video_orientation="landscape",
            template=None,
            file_data=None,
        )
        assert result.text == "Generating your video..."

    async def test_generate_passes_template(self):
        """generate() should forward an Omni template name to client.send()."""
        mock_client = MagicMock()
        mock_client.send = AsyncMock(return_value=StreamResponse(text="Starting..."))
        svc = VideoService(mock_client)
        await svc.generate("NAIDA'S salon", template="Logo reveal")
        kwargs = mock_client.send.call_args.kwargs
        assert kwargs["template"] == "Logo reveal"

    async def test_generate_passes_portrait_orientation(self):
        """generate() should forward portrait orientation to client.send()."""
        mock_client = MagicMock()
        mock_client.send = AsyncMock(return_value=StreamResponse(text="Starting..."))
        svc = VideoService(mock_client)
        await svc.generate("A vertical story", model="pro", orientation="portrait")
        kwargs = mock_client.send.call_args.kwargs
        assert kwargs["video_orientation"] == "portrait"
        assert kwargs["model"] == "pro"
        assert kwargs["tool_id"] == 11

    async def test_generate_accepts_orientation_aliases(self):
        """generate() accepts '9:16' and '16:9' aliases."""
        mock_client = MagicMock()
        mock_client.send = AsyncMock(return_value=StreamResponse(text="Starting..."))
        svc = VideoService(mock_client)

        await svc.generate("tall", orientation="9:16")
        assert mock_client.send.call_args.kwargs["video_orientation"] == "portrait"

        await svc.generate("wide", orientation="16:9")
        assert mock_client.send.call_args.kwargs["video_orientation"] == "landscape"

    async def test_generate_with_reference_image(self, monkeypatch, tmp_path):
        """generate() uploads reference files and attaches them as file_data."""
        from gemini_web_mcp_cli.services import file as file_module
        from gemini_web_mcp_cli.services import video as video_module

        uploaded = []

        class FakeFileService:
            def __init__(self, client):
                self.client = client

            async def upload(self, path):
                uploaded.append(path.name)
                return "/contrib_service/ttl_1d/fake"

        monkeypatch.setattr(file_module, "FileService", FakeFileService)

        image = tmp_path / "poster.png"
        image.write_bytes(b"fake-png")

        mock_client = MagicMock()
        mock_client.send = AsyncMock(return_value=StreamResponse())
        svc = video_module.VideoService(mock_client)
        await svc.generate("Animate this", files=[str(image)])

        assert uploaded == ["poster.png"]
        kwargs = mock_client.send.call_args.kwargs
        file_data = kwargs["file_data"]
        assert file_data is not None and len(file_data) == 1
        entry = file_data[0]
        assert entry[0] == ["/contrib_service/ttl_1d/fake", 3, None, "image/png"]
        assert entry[1] == "poster.png"
        assert entry[8] == [0]

    async def test_generate_rejects_unknown_orientation(self):
        """generate() raises ValueError for unknown orientation values."""
        import pytest

        mock_client = MagicMock()
        svc = VideoService(mock_client)
        with pytest.raises(ValueError, match="Unknown video orientation"):
            await svc.generate("test", orientation="diagonal")

    async def test_generate_stores_cid(self):
        """generate() should store the conversation ID from metadata."""
        from gemini_web_mcp_cli.core.models import ConversationMetadata

        meta = ConversationMetadata(cid="c_abc123", rid="r_xyz", rcid="rc_1")
        mock_client = MagicMock()
        mock_client.send = AsyncMock(
            return_value=StreamResponse(
                text="Starting...",
                metadata=meta,
            )
        )
        svc = VideoService(mock_client)
        await svc.generate("test prompt")
        assert svc._cid == "c_abc123"

    async def test_download_creates_file(self, tmp_path):
        mock_client = MagicMock()
        fake_video = b"fake mp4 content"
        output_file = tmp_path / "subdir" / "video.mp4"

        async def fake_download(url, output_path, timeout=120.0):
            out = Path(output_path)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(fake_video)
            return out

        mock_client.download_media = AsyncMock(side_effect=fake_download)
        svc = VideoService(mock_client)

        saved = await svc.download(
            "https://contribution.usercontent.google.com/download?c=abc",
            output_file,
        )

        assert saved == output_file
        assert output_file.exists()
        assert output_file.read_bytes() == fake_video

    async def test_download_creates_parent_dirs(self, tmp_path):
        """download() should create parent directories."""
        mock_client = MagicMock()
        output_file = tmp_path / "a" / "b" / "c" / "video.mp4"

        async def fake_download(url, output_path, timeout=120.0):
            out = Path(output_path)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(b"video data")
            return out

        mock_client.download_media = AsyncMock(side_effect=fake_download)
        svc = VideoService(mock_client)
        await svc.download("https://example.com/video.mp4", output_file)

        assert output_file.exists()

    async def test_wait_for_completion_no_cid(self):
        """wait_for_completion() should return None if no CID."""
        mock_client = MagicMock()
        svc = VideoService(mock_client)
        result = await svc.wait_for_completion(poll_interval=0.01, max_wait=0.05)
        assert result is None

    async def test_poll_status_calls_rpc_with_browser_cookies(self):
        """poll_status() should call execute_rpc_with_browser_cookies with hNvQHb."""
        from gemini_web_mcp_cli.core.models import BatchResult

        mock_client = MagicMock()
        mock_client.execute_rpc_with_browser_cookies = AsyncMock(
            return_value=[BatchResult(rpc_id="hNvQHb", data=["poll_data"], raw="")]
        )
        svc = VideoService(mock_client)
        svc._cid = "c_test123"
        result = await svc.poll_status("/app/test123")
        assert result["status"] == "polled"
        assert result["data"] == ["poll_data"]

        # Verify it called the browser-cookie method with hNvQHb
        call_kwargs = mock_client.execute_rpc_with_browser_cookies.call_args
        assert call_kwargs.kwargs["rpc_id"] == "hNvQHb"
        assert call_kwargs.kwargs["source_path"] == "/app/test123"
        # Verify payload contains the CID
        payload = json.loads(call_kwargs.kwargs["payload"])
        assert payload[0] == "c_test123"

    async def test_poll_status_no_cid(self):
        """poll_status() should return no_cid when no conversation ID is set."""
        mock_client = MagicMock()
        svc = VideoService(mock_client)
        result = await svc.poll_status()
        assert result["status"] == "no_cid"

    async def test_poll_status_no_result(self):
        """poll_status() should return no_result when RPC returns empty."""
        mock_client = MagicMock()
        mock_client.execute_rpc_with_browser_cookies = AsyncMock(return_value=[])
        svc = VideoService(mock_client)
        svc._cid = "c_test456"
        result = await svc.poll_status()
        assert result["status"] == "no_result"

    async def test_poll_status_default_source_path(self):
        """poll_status() should derive source_path from CID when not provided."""
        from gemini_web_mcp_cli.core.models import BatchResult

        mock_client = MagicMock()
        mock_client.execute_rpc_with_browser_cookies = AsyncMock(
            return_value=[BatchResult(rpc_id="hNvQHb", data=None, raw="")]
        )
        svc = VideoService(mock_client)
        svc._cid = "c_abc123def"
        await svc.poll_status()

        call_kwargs = mock_client.execute_rpc_with_browser_cookies.call_args
        assert call_kwargs.kwargs["source_path"] == "/app/abc123def"

    async def test_parse_conversation_data_with_video(self):
        """_parse_conversation_data() should extract video from hNvQHb data."""
        mock_client = MagicMock()
        svc = VideoService(mock_client)

        # Build nested data: data[0][0][3][0][0] = candidate
        # Real structure: entries > entry > [tracks] > track
        video_data = [
            [[[[None, None, None, None, None, None, None,
                ["preview", "https://download.example.com/video.mp4"]]]]],
        ]
        candidate = [None] * 40
        candidate[0] = "rc_test"
        candidate[1] = ["Here is your video"]
        index_12 = [None] * 60
        index_12[59] = video_data
        candidate[12] = index_12

        data = [[[[candidate]]]]  # data[0][0][3][0][0] via extra nesting
        # Adjust to match: get_nested(data, [0, 0, 3, 0, 0])
        # data[0] = outer, data[0][0] = inner, data[0][0][3] = candidates_list
        # data[0][0][3][0] = first_candidate_group, data[0][0][3][0][0] = candidate
        outer = [None] * 4
        outer[3] = [[candidate]]
        data = [[outer]]

        result = svc._parse_conversation_data(data)
        assert result is not None
        assert result.has_video is True
        assert result.text == "Here is your video"
        assert result.candidates[0].rcid == "rc_test"

    async def test_parse_conversation_data_no_video(self):
        """_parse_conversation_data() should return None for non-video data."""
        mock_client = MagicMock()
        svc = VideoService(mock_client)

        # Candidate without video data
        candidate = [None] * 40
        candidate[0] = "rc_test"
        candidate[1] = ["Just text"]

        outer = [None] * 4
        outer[3] = [[candidate]]
        data = [[outer]]

        result = svc._parse_conversation_data(data)
        # Should return a StreamResponse but without video
        assert result is not None
        assert result.has_video is False

    async def test_parse_conversation_data_bad_structure(self):
        """_parse_conversation_data() should return None for invalid data."""
        mock_client = MagicMock()
        svc = VideoService(mock_client)

        result = svc._parse_conversation_data([])
        assert result is None

        result = svc._parse_conversation_data(None)
        assert result is None

    async def test_wait_for_completion_raises_on_quota_exceeded(self):
        """wait_for_completion() should raise VideoGenerationError on quota rejection."""
        import pytest

        mock_client = MagicMock()
        svc = VideoService(mock_client)
        svc._cid = "c_test_quota"

        quota_text = (
            "Sorry, I can't generate more videos for you today, "
            "but come back tomorrow and we can make more."
        )
        candidate = [None] * 40
        candidate[0] = "rc_test"
        candidate[1] = [quota_text]

        outer = [None] * 4
        outer[3] = [[candidate]]
        poll_data = [[outer]]

        svc.poll_status = AsyncMock(
            return_value={"status": "polled", "data": poll_data}
        )

        with pytest.raises(VideoGenerationError, match="can't generate more videos"):
            await svc.wait_for_completion(poll_interval=0.01, max_wait=0.1)

    async def test_wait_for_completion_continues_on_non_rejection_text(self):
        """wait_for_completion() should keep polling when text is not a rejection."""
        mock_client = MagicMock()
        svc = VideoService(mock_client)
        svc._cid = "c_test_continue"

        # First poll: text-only response (still generating)
        text_candidate = [None] * 40
        text_candidate[0] = "rc_test"
        text_candidate[1] = ["Generating your video..."]
        text_outer = [None] * 4
        text_outer[3] = [[text_candidate]]
        text_data = [[text_outer]]

        # Second poll: video ready
        video_data = [
            [[[[None, None, None, None, None, None, None,
                ["preview", "https://download.example.com/video.mp4"]]]]],
        ]
        video_candidate = [None] * 40
        video_candidate[0] = "rc_test"
        video_candidate[1] = ["Here is your video"]
        index_12 = [None] * 60
        index_12[59] = video_data
        video_candidate[12] = index_12
        video_outer = [None] * 4
        video_outer[3] = [[video_candidate]]
        done_data = [[video_outer]]

        svc.poll_status = AsyncMock(side_effect=[
            {"status": "polled", "data": text_data},
            {"status": "polled", "data": done_data},
        ])

        result = await svc.wait_for_completion(poll_interval=0.01, max_wait=1.0)
        assert result is not None
        assert result.has_video is True
        assert svc.poll_status.call_count == 2
