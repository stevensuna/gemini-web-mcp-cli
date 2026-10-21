"""Tests for Gems service (CNgdBe RPC)."""

import base64
import json
from unittest.mock import AsyncMock, MagicMock

from gemini_web_mcp_cli.core.models import BatchResult
from gemini_web_mcp_cli.services.gems import (
    GEM_TOOL_ALIASES,
    GEM_TOOL_NAMES,
    Gem,
    GemCategory,
    GemDefaultTool,
    GemResource,
    GemsService,
    _build_notebook_token,
    _parse_resources,
)

# Sample response data captured from live Gemini API (Feb 2026)
# Structure: [null, null, [[gem1], [gem2], ...]]
SAMPLE_CUSTOM_GEMS_DATA = [
    None,
    None,
    [
        [
            "f999f1015c03",
            ["Pixel Art Creator", "Creates pixel art assets", None, None, None, None,
             ["", None, None, ["#C88EE1", "#55226E"], ["#9700D2", "#F2CCFF"]],
             False, False, [], []],
            ["Act as an Exceptional Pixel Art Expert.", None, [2]],
            False,
            ["182P-whiIFGnQxr5", None, None, False],
            [True, True, True],
        ],
        [
            "4d521c249aa1",
            ["Slide Deck Generator", "Creates slides using Red Hat Branding"],
            ["You are the Red Hat Presentation Architect.", None, [2]],
            False,
            None,
            [True, True, True],
        ],
    ],
]

# Gem with Drive document + uploaded files (based on live capture Feb 2026)
SAMPLE_GEM_WITH_RESOURCES_DATA = [
    None,
    None,
    [
        [
            "57a69e14347c",
            ["Post My Voice", "Voice cloning gem", None, None, None, None,
             ["", None, None, ["#D89800", "#4F3500"], ["#7E5700", "#FFD289"]],
             False, False, [],
             [
                 [
                     [
                         [None, ["1cdGJUcpxpFfSq1RehAW5QkB8APjXUkxv"],
                          "1cdGJUcpxpFfSq1RehAW5QkB8APjXUkxv"],
                         16, "WRITING_STYLE_DNA.md", None, None, None,
                         ["https://drive.google.com/file/d/1cdGJUcpxpFfSq1RehAW5QkB8APjXUkxv/view"],
                         None, 4, [1765161482, 820993000], None,
                         "text/markdown", None, [True],
                     ],
                     [
                         [["00063a4c80227c05", 8], None,
                          "7672080d-554a-4f16-9c29-ff124fcdcd72"],
                         11, "All JBD LinkedIN Blogs.pdf", None, None, None,
                         None, None, 1, [1752950092, 196264000], None,
                         "application/pdf", None, [True],
                     ],
                     [
                         [None, ["1lmhLsc1-YK0p9vUgN2Mi6Unn3yuJ"],
                          "4d26d3fe-c87b-487b-b5ed-a7941b8a0b06"],
                         8, "CSL Resource Doc", None, None, None,
                         ["https://drive.google.com/open?id=1lmhLsc1-YK0p9vUgN2Mi6Unn3yuJ"],
                         None, 4, [1771792936, 780978000], None,
                         "application/vnd.google-apps.document", None, [True],
                     ],
                     [
                         [["dc1376b9655ec642", 8], None,
                          "b16b0fdd-fa38-4896-abe9-85a9548ed221"],
                         1, "thumbnail.jpg", None, None, None,
                         None, None, 6, [1767194329, 687393000], None,
                         "image/jpeg", None, [True],
                     ],
                 ],
                 [["", []]],
             ]],
            ["You are a voice cloning expert.", None, [1]],
            False,
            None,
            [True, True, True],
        ],
    ],
]

SAMPLE_PREDEFINED_GEMS_DATA = [
    None,
    None,
    [
        [
            "brainstormer",
            ["Brainstormer", "Find inspiration easily. Fresh ideas for parties, gifts, and more."],
            ["Your purpose is to inspire and spark creativity.", None, [3, 2, 1]],
            False,
            None,
            [False, True, True],
        ],
        [
            "learning-coach",
            ["Learning coach", "Here to help you learn and practice new concepts."],
            ["You are a friendly AI tutor.", None, [3, 2, 1]],
            False,
            None,
            [False, True, True],
        ],
    ],
]

SAMPLE_SHARED_GEMS_DATA = [
    None,
    None,
    [
        [
            "d891aedbb939",
            ["PlainSpeak", "", None, None,
             ["Matt Peter", "mpeter@example.com", "https://example.com/avatar"],
             None, ["", None, None, ["#25B2D4", "#00404E"], ["#00677D", "#92E5FF"]]],
            ["Simulate a professional writing assistant.", None, [2]],
            False,
            ["folder_id", None, None, True],
            [True, False, True],
        ],
    ],
]

SAMPLE_EMPTY_GEMS_DATA = [None, None, []]


# ── GemCategory ───────────────────────────────────────────────────────────


class TestGemCategory:
    def test_custom_value(self):
        assert GemCategory.CUSTOM == 2

    def test_predefined_value(self):
        assert GemCategory.PREDEFINED == 3

    def test_shared_value(self):
        assert GemCategory.SHARED == 6

    def test_all_value(self):
        assert GemCategory.ALL == 1


# ── Gem dataclass ──────────────────────────────────────────────────────────


class TestGemResource:
    def test_defaults(self):
        r = GemResource(name="doc.txt", mime_type="text/plain", source="uploaded")
        assert r.name == "doc.txt"
        assert r.mime_type == "text/plain"
        assert r.source == "uploaded"
        assert r.drive_url == ""

    def test_drive_resource(self):
        r = GemResource(
            name="My Doc", mime_type="application/vnd.google-apps.document",
            source="drive", drive_url="https://drive.google.com/open?id=abc",
        )
        assert r.source == "drive"
        assert r.drive_url == "https://drive.google.com/open?id=abc"


class TestGemDataclass:
    def test_defaults(self):
        g = Gem(id="abc", name="Test")
        assert g.description == ""
        assert g.prompt == ""
        assert g.predefined is False
        assert g.shared is False
        assert g.resources == []
        assert g.default_tool == 0
        assert g.default_tool_name == "No default tool"

    def test_all_fields(self):
        r = GemResource(name="f.md", mime_type="text/markdown", source="uploaded")
        g = Gem(id="abc", name="Test", description="desc",
                prompt="You are...", predefined=True, shared=False,
                resources=[r], default_tool=14, default_tool_name="Create image")
        assert g.id == "abc"
        assert g.name == "Test"
        assert g.description == "desc"
        assert g.prompt == "You are..."
        assert g.predefined is True
        assert len(g.resources) == 1
        assert g.resources[0].name == "f.md"
        assert g.default_tool == 14
        assert g.default_tool_name == "Create image"


# ── GemsService.list_gems ──────────────────────────────────────────────────


class TestListGems:
    def _make_svc(self, data):
        mock_client = MagicMock()
        mock_client.execute_rpc_with_browser_cookies = AsyncMock(
            return_value=[BatchResult(rpc_id="CNgdBe", data=data, raw="")]
        )
        return GemsService(mock_client), mock_client

    async def test_list_custom_gems(self):
        svc, mock = self._make_svc(SAMPLE_CUSTOM_GEMS_DATA)
        gems = await svc.list_gems()
        assert len(gems) == 2
        assert gems[0].id == "f999f1015c03"
        assert gems[0].name == "Pixel Art Creator"
        assert gems[0].description == "Creates pixel art assets"
        assert gems[0].prompt == "Act as an Exceptional Pixel Art Expert."
        assert gems[0].predefined is False
        assert gems[0].shared is False
        assert gems[0].resources == []
        assert gems[0].default_tool == 0

    async def test_list_custom_gems_second_entry(self):
        svc, _ = self._make_svc(SAMPLE_CUSTOM_GEMS_DATA)
        gems = await svc.list_gems()
        assert gems[1].id == "4d521c249aa1"
        assert gems[1].name == "Slide Deck Generator"
        assert gems[1].description == "Creates slides using Red Hat Branding"

    async def test_list_predefined_gems(self):
        svc, mock = self._make_svc(SAMPLE_PREDEFINED_GEMS_DATA)
        gems = await svc.list_gems(predefined=True)
        assert len(gems) == 2
        assert gems[0].id == "brainstormer"
        assert gems[0].name == "Brainstormer"
        assert gems[0].predefined is True

    async def test_list_shared_gems(self):
        svc, mock = self._make_svc(SAMPLE_SHARED_GEMS_DATA)
        gems = await svc.list_gems(shared=True)
        assert len(gems) == 1
        assert gems[0].id == "d891aedbb939"
        assert gems[0].name == "PlainSpeak"
        assert gems[0].shared is True

    async def test_list_empty(self):
        svc, _ = self._make_svc(SAMPLE_EMPTY_GEMS_DATA)
        gems = await svc.list_gems()
        assert gems == []

    async def test_list_null_data(self):
        svc, _ = self._make_svc(None)
        gems = await svc.list_gems()
        assert gems == []

    async def test_custom_payload_format(self):
        """Verify the payload uses the new format [category, ['en'], 0]."""
        svc, mock = self._make_svc(SAMPLE_EMPTY_GEMS_DATA)
        await svc.list_gems()
        call_args = mock.execute_rpc_with_browser_cookies.call_args
        payload = json.loads(call_args.kwargs["payload"])
        assert payload == [2, ["en"], 0]

    async def test_predefined_payload_format(self):
        svc, mock = self._make_svc(SAMPLE_EMPTY_GEMS_DATA)
        await svc.list_gems(predefined=True)
        call_args = mock.execute_rpc_with_browser_cookies.call_args
        payload = json.loads(call_args.kwargs["payload"])
        assert payload == [3, ["en"], 0]

    async def test_shared_payload_format(self):
        svc, mock = self._make_svc(SAMPLE_EMPTY_GEMS_DATA)
        await svc.list_gems(shared=True)
        call_args = mock.execute_rpc_with_browser_cookies.call_args
        payload = json.loads(call_args.kwargs["payload"])
        assert payload == [6, ["en"], 0]

    async def test_uses_correct_rpc_id(self):
        svc, mock = self._make_svc(SAMPLE_EMPTY_GEMS_DATA)
        await svc.list_gems()
        call_args = mock.execute_rpc_with_browser_cookies.call_args
        assert call_args.kwargs["rpc_id"] == "CNgdBe"

    async def test_no_results_returns_empty(self):
        mock_client = MagicMock()
        mock_client.execute_rpc_with_browser_cookies = AsyncMock(return_value=[])
        svc = GemsService(mock_client)
        gems = await svc.list_gems()
        assert gems == []


# ── _parse_resources ───────────────────────────────────────────────────────


class TestParseResources:
    def test_none_input(self):
        assert _parse_resources(None) == []

    def test_empty_list(self):
        assert _parse_resources([]) == []

    def test_non_list_input(self):
        assert _parse_resources("not a list") == []

    def test_no_file_entries(self):
        assert _parse_resources([None, [["", []]]]) == []

    def test_drive_file_with_url(self):
        """Drive file (type 16) with a Drive URL → source='drive'."""
        data = [
            [
                [
                    [None, ["abc123"], "uuid-1"],
                    16, "STYLE_DNA.md", None, None, None,
                    ["https://drive.google.com/file/d/abc123/view"],
                    None, 4, [1765161482, 820993000], None,
                    "text/markdown", None, [True],
                ],
            ],
            [["", []]],
        ]
        resources = _parse_resources(data)
        assert len(resources) == 1
        assert resources[0].name == "STYLE_DNA.md"
        assert resources[0].mime_type == "text/markdown"
        assert resources[0].source == "drive"
        assert "abc123" in resources[0].drive_url

    def test_uploaded_file_no_url(self):
        """Uploaded file (type 11 PDF) with no Drive URL → source='uploaded'."""
        data = [
            [
                [
                    [["00063a4c80227c05", 8], None, "uuid-2"],
                    11, "report.pdf", None, None, None,
                    None, None, 1, [1752950092, 196264000], None,
                    "application/pdf", None, [True],
                ],
            ],
            [["", []]],
        ]
        resources = _parse_resources(data)
        assert len(resources) == 1
        assert resources[0].name == "report.pdf"
        assert resources[0].mime_type == "application/pdf"
        assert resources[0].source == "uploaded"
        assert resources[0].drive_url == ""

    def test_drive_native_document(self):
        """Google Drive native doc (type 8) with Drive URL → source='drive'."""
        data = [
            [
                [
                    [None, ["1lmhLsc1"], "4d26d3fe"],
                    8, "My Google Doc", None, None, None,
                    ["https://drive.google.com/open?id=1lmhLsc1"],
                    None, 4, [1771792936, 780978000], None,
                    "application/vnd.google-apps.document", None, [True],
                ],
            ],
        ]
        resources = _parse_resources(data)
        assert len(resources) == 1
        assert resources[0].name == "My Google Doc"
        assert resources[0].mime_type == "application/vnd.google-apps.document"
        assert resources[0].source == "drive"

    def test_image_file(self):
        """Image file (type 1) with no Drive URL → source='uploaded'."""
        data = [
            [
                [
                    [["dc1376b9", 8], None, "b16b0fdd"],
                    1, "photo.jpg", None, None, None,
                    None, None, 6, [1767194329, 687393000], None,
                    "image/jpeg", None, [True],
                ],
            ],
        ]
        resources = _parse_resources(data)
        assert len(resources) == 1
        assert resources[0].name == "photo.jpg"
        assert resources[0].mime_type == "image/jpeg"
        assert resources[0].source == "uploaded"

    def test_multiple_resources(self):
        """Multiple file entries are all parsed."""
        data = [
            [
                [
                    [None, ["id1"], "uuid1"],
                    16, "file1.md", None, None, None,
                    ["https://drive.google.com/file/d/id1/view"],
                    None, 4, [0, 0], None, "text/markdown", None, [True],
                ],
                [
                    [["hash2", 8], None, "uuid2"],
                    11, "file2.pdf", None, None, None,
                    None, None, 1, [0, 0], None, "application/pdf", None, [True],
                ],
                [
                    [["hash3", 8], None, "uuid3"],
                    1, "img.jpg", None, None, None,
                    None, None, 6, [0, 0], None, "image/jpeg", None, [True],
                ],
            ],
        ]
        resources = _parse_resources(data)
        assert len(resources) == 3
        assert resources[0].source == "drive"
        assert resources[1].source == "uploaded"
        assert resources[2].source == "uploaded"

    def test_non_list_entry_skipped(self):
        """Non-list entries in the file list are skipped."""
        data = [[None, "invalid", [
            [None, None, "uuid"], 16, "ok.md", None, None, None,
            None, None, 1, [0, 0], None, "text/markdown", None, [True],
        ]]]
        resources = _parse_resources(data)
        assert len(resources) == 1
        assert resources[0].name == "ok.md"


# ── GemsService.list_gems with resources ──────────────────────────────────


class TestListGemsWithResources:
    def _make_svc(self, data):
        mock_client = MagicMock()
        mock_client.execute_rpc_with_browser_cookies = AsyncMock(
            return_value=[BatchResult(rpc_id="CNgdBe", data=data, raw="")]
        )
        return GemsService(mock_client)

    async def test_gem_resources_parsed(self):
        svc = self._make_svc(SAMPLE_GEM_WITH_RESOURCES_DATA)
        gems = await svc.list_gems()
        assert len(gems) == 1
        g = gems[0]
        assert g.id == "57a69e14347c"
        assert g.name == "Post My Voice"
        assert g.prompt == "You are a voice cloning expert."
        assert len(g.resources) == 4

    async def test_resource_types(self):
        svc = self._make_svc(SAMPLE_GEM_WITH_RESOURCES_DATA)
        gems = await svc.list_gems()
        resources = gems[0].resources

        assert resources[0].name == "WRITING_STYLE_DNA.md"
        assert resources[0].mime_type == "text/markdown"
        assert resources[0].source == "drive"

        assert resources[1].name == "All JBD LinkedIN Blogs.pdf"
        assert resources[1].mime_type == "application/pdf"
        assert resources[1].source == "uploaded"

        assert resources[2].name == "CSL Resource Doc"
        assert resources[2].mime_type == "application/vnd.google-apps.document"
        assert resources[2].source == "drive"

        assert resources[3].name == "thumbnail.jpg"
        assert resources[3].mime_type == "image/jpeg"
        assert resources[3].source == "uploaded"

    async def test_gem_without_resources(self):
        svc = self._make_svc(SAMPLE_CUSTOM_GEMS_DATA)
        gems = await svc.list_gems()
        assert gems[0].resources == []
        assert gems[1].resources == []

    async def test_default_tool_none(self):
        svc = self._make_svc(SAMPLE_GEM_WITH_RESOURCES_DATA)
        gems = await svc.list_gems()
        assert gems[0].default_tool == 0
        assert gems[0].default_tool_name == "No default tool"


# ── GemDefaultTool & aliases ───────────────────────────────────────────────


class TestGemDefaultTool:
    def test_enum_values(self):
        assert GemDefaultTool.NONE == 0
        assert GemDefaultTool.DEEP_RESEARCH == 1
        assert GemDefaultTool.CANVAS == 2
        assert GemDefaultTool.CREATE_VIDEO == 11
        assert GemDefaultTool.CREATE_IMAGE == 14
        assert GemDefaultTool.CREATE_MUSIC == 21
        assert GemDefaultTool.GUIDED_LEARNING == 24

    def test_tool_names_all_present(self):
        for member in GemDefaultTool:
            assert member.value in GEM_TOOL_NAMES

    def test_aliases_resolve(self):
        assert GEM_TOOL_ALIASES["image"] == 14
        assert GEM_TOOL_ALIASES["video"] == 11
        assert GEM_TOOL_ALIASES["music"] == 21
        assert GEM_TOOL_ALIASES["canvas"] == 2
        assert GEM_TOOL_ALIASES["research"] == 1
        assert GEM_TOOL_ALIASES["deep-research"] == 1
        assert GEM_TOOL_ALIASES["learning"] == 24
        assert GEM_TOOL_ALIASES["none"] == 0

    def test_full_name_aliases(self):
        assert GEM_TOOL_ALIASES["create image"] == 14
        assert GEM_TOOL_ALIASES["create video"] == 11
        assert GEM_TOOL_ALIASES["create music"] == 21
        assert GEM_TOOL_ALIASES["deep research"] == 1
        assert GEM_TOOL_ALIASES["guided learning"] == 24


# ── Default tool in list response ─────────────────────────────────────────

SAMPLE_GEM_WITH_TOOL_DATA = [
    None,
    None,
    [
        [
            "abc123tool",
            ["Image Gem", "Generates images", None, None, None, None,
             ["", None, None, ["#C88EE1", "#55226E"], ["#9700D2", "#F2CCFF"]],
             False, False, [], [], 14, None, False],
            ["Create beautiful images.", None, [2]],
            False,
            None,
            [True, True, True],
        ],
    ],
]


class TestListGemsWithDefaultTool:
    def _make_svc(self, data):
        mock_client = MagicMock()
        mock_client.execute_rpc_with_browser_cookies = AsyncMock(
            return_value=[BatchResult(rpc_id="CNgdBe", data=data, raw="")]
        )
        return GemsService(mock_client)

    async def test_parses_tool_code(self):
        svc = self._make_svc(SAMPLE_GEM_WITH_TOOL_DATA)
        gems = await svc.list_gems()
        assert gems[0].default_tool == 14

    async def test_resolves_tool_name(self):
        svc = self._make_svc(SAMPLE_GEM_WITH_TOOL_DATA)
        gems = await svc.list_gems()
        assert gems[0].default_tool_name == "Create image"

    async def test_no_tool_returns_zero(self):
        svc = self._make_svc(SAMPLE_CUSTOM_GEMS_DATA)
        gems = await svc.list_gems()
        assert gems[0].default_tool == 0
        assert gems[0].default_tool_name == "No default tool"


# ── GemsService.create ─────────────────────────────────────────────────────


class TestCreateGem:
    async def test_create_sends_correct_payload(self):
        mock_client = MagicMock()
        mock_client.execute_rpc_with_browser_cookies = AsyncMock(
            return_value=[BatchResult(rpc_id="oMH3Zd", data={"id": "new123"}, raw="")]
        )
        svc = GemsService(mock_client)
        result = await svc.create("Test Gem", "A test", "You are a test.")
        assert result["status"] == "created"

        call_args = mock_client.execute_rpc_with_browser_cookies.call_args
        assert call_args.kwargs["rpc_id"] == "oMH3Zd"
        payload = json.loads(call_args.kwargs["payload"])
        # Payload is [[name, desc, prompt, null×5, 0, null, 1, null×3, [], null×2, 0]]
        inner = payload[0]
        assert inner[0] == "Test Gem"
        assert inner[1] == "A test"
        assert inner[2] == "You are a test."
        assert inner[8] == 0   # confirmed from live capture Feb 2026
        assert inner[10] == 1  # confirmed from live capture Feb 2026
        assert inner[14] == [] # knowledge files (empty)
        assert inner[15] == 0  # default tool (none)

    async def test_create_no_results(self):
        mock_client = MagicMock()
        mock_client.execute_rpc_with_browser_cookies = AsyncMock(return_value=[])
        svc = GemsService(mock_client)
        result = await svc.create("Test", "", "prompt")
        assert result["status"] == "created"
        assert result["data"] is None

    async def test_create_with_knowledge_files(self):
        """Verify knowledge files are processed and embedded at payload position 14."""
        from unittest.mock import patch

        mock_client = MagicMock()
        mock_client.execute_rpc_with_browser_cookies = AsyncMock(
            return_value=[BatchResult(rpc_id="oMH3Zd", data=["newgem1", True], raw="")]
        )
        mock_client.process_gem_file = AsyncMock(return_value="$AedTestToken==")

        svc = GemsService(mock_client)

        with patch("gemini_web_mcp_cli.services.gems.FileService") as MockFileService:
            mock_file_svc = MagicMock()
            mock_file_svc.upload = AsyncMock(return_value="/contrib_service/ttl_1d/testfile123")
            MockFileService.return_value = mock_file_svc

            result = await svc.create(
                "Test Gem", "A test", "You are a test.", knowledge_files=["/tmp/knowledge.txt"]
            )

        assert result["status"] == "created"
        assert result["gem_id"] == "newgem1"

        call_args = mock_client.execute_rpc_with_browser_cookies.call_args
        payload = json.loads(call_args.kwargs["payload"])
        inner = payload[0]
        # Position 14: all entries wrapped in single inner array [[entry1, ...]]
        assert inner[14] == [[[None, None, None, None, None, "$AedTestToken=="]]]  # noqa: E501

    async def test_create_no_knowledge_files_has_empty_list(self):
        """Without knowledge files, position 14 is an empty list."""
        mock_client = MagicMock()
        mock_client.execute_rpc_with_browser_cookies = AsyncMock(
            return_value=[BatchResult(rpc_id="oMH3Zd", data=["gem1", True], raw="")]
        )
        svc = GemsService(mock_client)
        await svc.create("Test", "", "prompt")
        call_args = mock_client.execute_rpc_with_browser_cookies.call_args
        payload = json.loads(call_args.kwargs["payload"])
        assert payload[0][14] == []

    async def test_create_with_default_tool(self):
        """Default tool code goes at payload position 15."""
        mock_client = MagicMock()
        mock_client.execute_rpc_with_browser_cookies = AsyncMock(
            return_value=[BatchResult(rpc_id="oMH3Zd", data=["gem1", True], raw="")]
        )
        svc = GemsService(mock_client)
        await svc.create("Test", "", "prompt", default_tool=14)
        call_args = mock_client.execute_rpc_with_browser_cookies.call_args
        payload = json.loads(call_args.kwargs["payload"])
        assert payload[0][15] == 14


# ── GemsService.update ─────────────────────────────────────────────────────


class TestUpdateGem:
    async def test_update_sends_correct_payload(self):
        mock_client = MagicMock()
        mock_client.execute_rpc_with_browser_cookies = AsyncMock(
            return_value=[BatchResult(rpc_id="kHv0Vd", data={}, raw="")]
        )
        svc = GemsService(mock_client)
        result = await svc.update("gem123", "New Name", "New Desc", "New Prompt")
        assert result["status"] == "updated"

        call_args = mock_client.execute_rpc_with_browser_cookies.call_args
        assert call_args.kwargs["rpc_id"] == "kHv0Vd"
        payload = json.loads(call_args.kwargs["payload"])
        assert payload[0] == "gem123"
        assert payload[1][0] == "New Name"
        assert payload[1][1] == "New Desc"
        assert payload[1][2] == "New Prompt"
        assert payload[1][15] == 0  # default tool (none)

    async def test_update_with_default_tool(self):
        """Default tool code goes at payload position 15 in update."""
        mock_client = MagicMock()
        mock_client.execute_rpc_with_browser_cookies = AsyncMock(
            return_value=[BatchResult(rpc_id="kHv0Vd", data=[True], raw="")]
        )
        svc = GemsService(mock_client)
        await svc.update("gem123", "Name", "Desc", "Prompt", default_tool=21)
        call_args = mock_client.execute_rpc_with_browser_cookies.call_args
        payload = json.loads(call_args.kwargs["payload"])
        assert payload[1][15] == 21  # Create music

    async def test_update_with_knowledge_files(self):
        """Verify knowledge files are processed and embedded in update payload position 14."""
        from unittest.mock import patch

        mock_client = MagicMock()
        mock_client.execute_rpc_with_browser_cookies = AsyncMock(
            return_value=[BatchResult(rpc_id="kHv0Vd", data=[True], raw="")]
        )
        mock_client.process_gem_file = AsyncMock(return_value="$AedUpdateToken==")

        svc = GemsService(mock_client)

        with patch("gemini_web_mcp_cli.services.gems.FileService") as MockFileService:
            mock_file_svc = MagicMock()
            mock_file_svc.upload = AsyncMock(return_value="/contrib_service/ttl_1d/testfile456")
            MockFileService.return_value = mock_file_svc

            result = await svc.update(
                "gem123", "Updated", "Desc", "Prompt",
                knowledge_files=["/tmp/doc.txt"],
            )

        assert result["status"] == "updated"
        call_args = mock_client.execute_rpc_with_browser_cookies.call_args
        payload = json.loads(call_args.kwargs["payload"])
        inner = payload[1]
        assert inner[14] == [[[None, None, None, None, None, "$AedUpdateToken=="]]]


# ── GemsService.delete ─────────────────────────────────────────────────────


class TestDeleteGem:
    async def test_delete_sends_correct_payload(self):
        mock_client = MagicMock()
        mock_client.execute_rpc_with_browser_cookies = AsyncMock(
            return_value=[BatchResult(rpc_id="UXcSJb", data={}, raw="")]
        )
        svc = GemsService(mock_client)
        result = await svc.delete("gem456")
        assert result["status"] == "deleted"

        call_args = mock_client.execute_rpc_with_browser_cookies.call_args
        assert call_args.kwargs["rpc_id"] == "UXcSJb"
        payload = json.loads(call_args.kwargs["payload"])
        assert payload == ["gem456"]

    async def test_delete_no_results(self):
        mock_client = MagicMock()
        mock_client.execute_rpc_with_browser_cookies = AsyncMock(return_value=[])
        svc = GemsService(mock_client)
        result = await svc.delete("gem456")
        assert result["status"] == "deleted"
        assert result["data"] is None


# ── NotebookLM notebook integration ───────────────────────────────────────

# Live capture: gem with a NotebookLM notebook attached (Feb 2026)
SAMPLE_GEM_WITH_NOTEBOOK_DATA = [
    None,
    None,
    [
        [
            "2dea125ea874",
            ["YouTube Video MetaData Generator", "", None, None, None, None,
             ["", None, None, ["#EC8C4C", "#612B00"], ["#96490A", "#FFCFB4"]],
             False, False, [],
             [
                 [
                     [
                         [None, None, None, None, None, None, None, None,
                          None, None, None, None, None, None,
                          ["notebooks/32c3a781-0cc5-4b69-a1c4-4ce27d392a48"]],
                         20, "YouTube Test", None, None, None, None, None,
                         14, None, None, "",
                     ],
                 ],
             ]],
            ["You are an elite YouTube Growth Strategist.", None, [1]],
            False,
            None,
            [False, True, True],
        ],
    ],
]

# Live capture: gem with mixed Drive files and a NLM notebook
SAMPLE_GEM_WITH_MIXED_RESOURCES_DATA = [
    None,
    None,
    [
        [
            "mixed_gem_id",
            ["Mixed Gem", "Has both Drive and NLM resources", None, None, None, None,
             ["", None, None, ["#C88EE1", "#55226E"], ["#9700D2", "#F2CCFF"]],
             False, False, [],
             [
                 [
                     [
                         [None, ["1cdGJUcpxpFfSq1RehAW5QkB8APjXUkxv"],
                          "1cdGJUcpxpFfSq1RehAW5QkB8APjXUkxv"],
                         16, "guide.md", None, None, None,
                         ["https://drive.google.com/file/d/1cdGJUcpxpFfSq1RehAW5QkB8APjXUkxv/view"],
                         None, 4, [1765161482, 820993000], None,
                         "text/markdown", None, [True],
                     ],
                     [
                         [None, None, None, None, None, None, None, None,
                          None, None, None, None, None, None,
                          ["notebooks/d912b0e2-f9f9-4959-81f5-f2ffb02fcffd"]],
                         20, "Research Notebook", None, None, None, None, None,
                         14, None, None, "",
                     ],
                 ],
             ]],
            ["System prompt here.", None, [1]],
            False,
            None,
            [True, True, True],
        ],
    ],
]

# NXpLKc RPC response: list of NotebookLM notebooks
# Real response is wrapped: [[[path, title, [ts, ns], count], ...]]
SAMPLE_NLM_NOTEBOOKS_DATA = [
    [
        ["notebooks/d912b0e2-f9f9-4959-81f5-f2ffb02fcffd",
         "NotebookLM MCP & CLI Research", [1769749909, 305491000], 84],
        ["notebooks/32c3a781-0cc5-4b69-a1c4-4ce27d392a48",
         "YouTube Test", [1768097027, 16934000], 0],
        ["notebooks/f40920d0-64a7-42d1-8129-742fbe97aa0e",
         "BBQ Guide", [1748018433, 463546000], 31],
    ],
]


class TestBuildNotebookToken:
    """Verify the protobuf token builder produces correct output."""

    def test_known_token_matches(self):
        """Token for YouTube Test must match the byte-exact capture from Chrome."""
        expected = (
            "CjJ6MAoubm90ZWJvb2tzLzMyYzNhNzgxLTBjYzUtNGI2OS1hMWM0LTRjZTI3ZDM5MmE0OB"
            "AUGgxZb3VUdWJlIFRlc3RIDmIA"
        )
        token = _build_notebook_token(
            "notebooks/32c3a781-0cc5-4b69-a1c4-4ce27d392a48", "YouTube Test"
        )
        assert token == expected

    def test_token_is_valid_base64(self):
        token = _build_notebook_token("notebooks/abc-123", "My Notebook")
        raw = base64.b64decode(token)
        assert len(raw) > 0

    def test_token_contains_notebook_path(self):
        path = "notebooks/d912b0e2-f9f9-4959-81f5-f2ffb02fcffd"
        token = _build_notebook_token(path, "Research")
        raw = base64.b64decode(token)
        assert path.encode("utf-8") in raw

    def test_token_contains_title(self):
        token = _build_notebook_token("notebooks/abc", "My Great Notebook")
        raw = base64.b64decode(token)
        assert b"My Great Notebook" in raw

    def test_empty_title(self):
        token = _build_notebook_token("notebooks/abc", "")
        raw = base64.b64decode(token)
        assert b"notebooks/abc" in raw


class TestParseNotebookResource:
    """Test _parse_resources with NotebookLM notebook entries (type code 20)."""

    def test_notebook_entry(self):
        data = [
            [
                [
                    [None, None, None, None, None, None, None, None,
                     None, None, None, None, None, None,
                     ["notebooks/32c3a781-0cc5-4b69-a1c4-4ce27d392a48"]],
                    20, "YouTube Test", None, None, None, None, None,
                    14, None, None, "",
                ],
            ],
        ]
        resources = _parse_resources(data)
        assert len(resources) == 1
        r = resources[0]
        assert r.name == "YouTube Test"
        assert r.source == "notebook"
        assert r.notebook_id == "32c3a781-0cc5-4b69-a1c4-4ce27d392a48"
        assert r.mime_type == ""
        assert r.drive_url == ""

    def test_mixed_drive_and_notebook(self):
        data = [
            [
                [
                    [None, ["abc123"], "uuid-1"],
                    16, "guide.md", None, None, None,
                    ["https://drive.google.com/file/d/abc123/view"],
                    None, 4, [0, 0], None, "text/markdown", None, [True],
                ],
                [
                    [None, None, None, None, None, None, None, None,
                     None, None, None, None, None, None,
                     ["notebooks/d912b0e2-f9f9-4959-81f5-f2ffb02fcffd"]],
                    20, "Research NB", None, None, None, None, None,
                    14, None, None, "",
                ],
            ],
        ]
        resources = _parse_resources(data)
        assert len(resources) == 2
        assert resources[0].source == "drive"
        assert resources[0].name == "guide.md"
        assert resources[1].source == "notebook"
        assert resources[1].name == "Research NB"
        assert resources[1].notebook_id == "d912b0e2-f9f9-4959-81f5-f2ffb02fcffd"


class TestGemResourceNotebook:
    def test_notebook_resource_defaults(self):
        r = GemResource(
            name="My NB", mime_type="", source="notebook",
            notebook_id="32c3a781-0cc5-4b69-a1c4-4ce27d392a48",
        )
        assert r.source == "notebook"
        assert r.notebook_id == "32c3a781-0cc5-4b69-a1c4-4ce27d392a48"
        assert r.drive_url == ""


class TestListGemsWithNotebook:
    def _make_svc(self, data):
        mock_client = MagicMock()
        mock_client.execute_rpc_with_browser_cookies = AsyncMock(
            return_value=[BatchResult(rpc_id="CNgdBe", data=data, raw="")]
        )
        return GemsService(mock_client)

    async def test_notebook_resource_parsed(self):
        svc = self._make_svc(SAMPLE_GEM_WITH_NOTEBOOK_DATA)
        gems = await svc.list_gems()
        assert len(gems) == 1
        g = gems[0]
        assert g.id == "2dea125ea874"
        assert len(g.resources) == 1
        r = g.resources[0]
        assert r.source == "notebook"
        assert r.name == "YouTube Test"
        assert r.notebook_id == "32c3a781-0cc5-4b69-a1c4-4ce27d392a48"

    async def test_mixed_resources_parsed(self):
        svc = self._make_svc(SAMPLE_GEM_WITH_MIXED_RESOURCES_DATA)
        gems = await svc.list_gems()
        assert len(gems) == 1
        resources = gems[0].resources
        assert len(resources) == 2
        assert resources[0].source == "drive"
        assert resources[0].name == "guide.md"
        assert resources[1].source == "notebook"
        assert resources[1].name == "Research Notebook"


class TestListNotebooks:
    async def test_list_notebooks(self):
        mock_client = MagicMock()
        mock_client.execute_rpc_with_browser_cookies = AsyncMock(
            return_value=[BatchResult(
                rpc_id="NXpLKc", data=SAMPLE_NLM_NOTEBOOKS_DATA, raw=""
            )]
        )
        svc = GemsService(mock_client)
        notebooks = await svc.list_notebooks()
        assert len(notebooks) == 3
        assert notebooks[0]["id"] == "d912b0e2-f9f9-4959-81f5-f2ffb02fcffd"
        assert notebooks[0]["title"] == "NotebookLM MCP & CLI Research"
        assert notebooks[0]["source_count"] == 84
        assert notebooks[1]["id"] == "32c3a781-0cc5-4b69-a1c4-4ce27d392a48"
        assert notebooks[1]["title"] == "YouTube Test"
        assert notebooks[1]["source_count"] == 0

    async def test_list_notebooks_uses_correct_rpc(self):
        mock_client = MagicMock()
        mock_client.execute_rpc_with_browser_cookies = AsyncMock(
            return_value=[BatchResult(rpc_id="NXpLKc", data=[[]], raw="")]
        )
        svc = GemsService(mock_client)
        await svc.list_notebooks()
        call_args = mock_client.execute_rpc_with_browser_cookies.call_args
        assert call_args.kwargs["rpc_id"] == "NXpLKc"
        assert json.loads(call_args.kwargs["payload"]) == []

    async def test_list_notebooks_empty(self):
        mock_client = MagicMock()
        mock_client.execute_rpc_with_browser_cookies = AsyncMock(
            return_value=[BatchResult(rpc_id="NXpLKc", data=[[]], raw="")]
        )
        svc = GemsService(mock_client)
        notebooks = await svc.list_notebooks()
        assert notebooks == []

    async def test_list_notebooks_no_results(self):
        mock_client = MagicMock()
        mock_client.execute_rpc_with_browser_cookies = AsyncMock(
            return_value=[]
        )
        svc = GemsService(mock_client)
        notebooks = await svc.list_notebooks()
        assert notebooks == []


class TestCreateGemWithNotebooks:
    async def test_create_with_notebook_ids(self):
        mock_client = MagicMock()
        mock_client.execute_rpc_with_browser_cookies = AsyncMock(
            side_effect=[
                [BatchResult(rpc_id="NXpLKc", data=SAMPLE_NLM_NOTEBOOKS_DATA, raw="")],
                [BatchResult(rpc_id="oMH3Zd", data=["newgem1", True], raw="")],
            ]
        )
        svc = GemsService(mock_client)
        result = await svc.create(
            "Test", "", "prompt",
            notebook_ids=["32c3a781-0cc5-4b69-a1c4-4ce27d392a48"],
        )
        assert result["status"] == "created"

        create_call = mock_client.execute_rpc_with_browser_cookies.call_args_list[1]
        payload = json.loads(create_call.kwargs["payload"])
        knowledge = payload[0][14]
        assert len(knowledge) == 1
        token = knowledge[0][0][5]
        raw = base64.b64decode(token)
        assert b"notebooks/32c3a781-0cc5-4b69-a1c4-4ce27d392a48" in raw
        assert b"YouTube Test" in raw


class TestUpdateGemWithNotebooks:
    async def test_update_with_notebook_ids(self):
        mock_client = MagicMock()
        mock_client.execute_rpc_with_browser_cookies = AsyncMock(
            side_effect=[
                [BatchResult(rpc_id="NXpLKc", data=SAMPLE_NLM_NOTEBOOKS_DATA, raw="")],
                [BatchResult(rpc_id="kHv0Vd", data=[True], raw="")],
            ]
        )
        svc = GemsService(mock_client)
        result = await svc.update(
            "gem123", "Name", "Desc", "Prompt",
            notebook_ids=["d912b0e2-f9f9-4959-81f5-f2ffb02fcffd"],
        )
        assert result["status"] == "updated"

        update_call = mock_client.execute_rpc_with_browser_cookies.call_args_list[1]
        payload = json.loads(update_call.kwargs["payload"])
        knowledge = payload[1][14]
        assert len(knowledge) == 1
        token = knowledge[0][0][5]
        raw = base64.b64decode(token)
        assert b"notebooks/d912b0e2-f9f9-4959-81f5-f2ffb02fcffd" in raw
        assert b"NotebookLM MCP & CLI Research" in raw
