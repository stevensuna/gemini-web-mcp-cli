"""Gems service: manage custom system prompts (Gems)."""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass, field
from enum import IntEnum

from gemini_web_mcp_cli.core.client import GeminiClient
from gemini_web_mcp_cli.core.constants import RPC
from gemini_web_mcp_cli.core.parser import get_nested
from gemini_web_mcp_cli.services.file import FileService


class GemCategory(IntEnum):
    """Gem list categories used in the CNgdBe RPC payload.

    Discovered via Chrome DevTools (Feb 2026). The first element of the
    payload array selects which gem category to list.
    """

    ALL = 1           # Custom + shared (combined view)
    CUSTOM = 2        # My Gems (user-created)
    PREDEFINED = 3    # Premade by Google
    SHARED = 6        # Shared with me (by other users)


class GemDefaultTool(IntEnum):
    """Default tool codes for Gems.

    Discovered via Chrome DevTools XHR capture (Feb 2026).
    Stored at payload position 15 (create/update) and response position [1][11] (list).
    """

    NONE = 0
    DEEP_RESEARCH = 1
    CANVAS = 2
    CREATE_VIDEO = 11
    CREATE_IMAGE = 14
    CREATE_MUSIC = 21
    GUIDED_LEARNING = 24


# Maps tool code → human-readable name for display
GEM_TOOL_NAMES: dict[int, str] = {
    GemDefaultTool.NONE: "No default tool",
    GemDefaultTool.DEEP_RESEARCH: "Deep research",
    GemDefaultTool.CANVAS: "Canvas",
    GemDefaultTool.CREATE_VIDEO: "Create video",
    GemDefaultTool.CREATE_IMAGE: "Create image",
    GemDefaultTool.CREATE_MUSIC: "Create music",
    GemDefaultTool.GUIDED_LEARNING: "Guided learning",
}

# Reverse map: name/alias → tool code (for CLI/MCP input)
GEM_TOOL_ALIASES: dict[str, int] = {}
for _code, _name in GEM_TOOL_NAMES.items():
    GEM_TOOL_ALIASES[_name.lower()] = _code
    GEM_TOOL_ALIASES[_name.lower().replace(" ", "_")] = _code
    GEM_TOOL_ALIASES[_name.lower().replace(" ", "-")] = _code
# Short aliases
GEM_TOOL_ALIASES.update({
    "none": 0, "image": 14, "video": 11, "music": 21,
    "canvas": 2, "research": 1, "deep-research": 1, "learning": 24,
})


@dataclass
class GemResource:
    """A knowledge resource attached to a Gem."""

    name: str
    mime_type: str
    source: str  # "drive", "uploaded", or "notebook"
    drive_url: str = ""
    notebook_id: str = ""


@dataclass
class Gem:
    """A Gemini Gem (custom system prompt)."""

    id: str
    name: str
    description: str = ""
    prompt: str = ""
    predefined: bool = False
    shared: bool = False
    resources: list[GemResource] = field(default_factory=list)
    default_tool: int = 0
    default_tool_name: str = "No default tool"


def _parse_resources(resource_data: list | None) -> list[GemResource]:
    """Parse knowledge resources from gem_data[1][10].

    Resource array structure (discovered via live API capture, Feb 2026):
      resource_data[0] = list of file entries
      resource_data[1] = metadata (e.g., [["", []]])

    Each file entry is an array where:
      entry[1]  = type code: 8 (Drive native doc), 16 (uploaded file),
                  1 (image), 11 (PDF), 20 (NotebookLM notebook)
      entry[2]  = filename or document title
      entry[6]  = Drive URL array (or None for direct uploads)
      entry[8]  = source indicator: 4 (Drive), 1 (uploaded), 6 (other), 14 (NotebookLM)
      entry[11] = MIME type
      entry[0][14] = notebook path array (for type 20 only)
    """
    if not resource_data or not isinstance(resource_data, list):
        return []

    file_entries = get_nested(resource_data, [0])
    if not file_entries or not isinstance(file_entries, list):
        return []

    resources = []
    for entry in file_entries:
        if not isinstance(entry, list):
            continue
        type_code = get_nested(entry, [1])
        name = get_nested(entry, [2], "")
        mime_type = get_nested(entry, [11], "")

        if type_code == 20:
            nb_path_arr = get_nested(entry, [0, 14])
            nb_path = nb_path_arr[0] if isinstance(nb_path_arr, list) and nb_path_arr else ""
            nb_id = nb_path.removeprefix("notebooks/") if nb_path else ""
            resources.append(GemResource(
                name=name,
                mime_type=mime_type,
                source="notebook",
                notebook_id=nb_id,
            ))
        else:
            urls = get_nested(entry, [6])
            drive_url = urls[0] if isinstance(urls, list) and urls else ""
            source = "drive" if drive_url else "uploaded"
            resources.append(GemResource(
                name=name,
                mime_type=mime_type,
                source=source,
                drive_url=drive_url,
            ))
    return resources


def _encode_varint(value: int) -> bytes:
    """Encode an integer as a protobuf varint."""
    result = bytearray()
    while value > 0x7F:
        result.append((value & 0x7F) | 0x80)
        value >>= 7
    result.append(value & 0x7F)
    return bytes(result)


def _encode_len_field(field_number: int, data: bytes) -> bytes:
    """Encode a protobuf length-delimited (wire type 2) field."""
    tag = _encode_varint((field_number << 3) | 2)
    return tag + _encode_varint(len(data)) + data


def _encode_varint_field(field_number: int, value: int) -> bytes:
    """Encode a protobuf varint (wire type 0) field."""
    tag = _encode_varint((field_number << 3) | 0)
    return tag + _encode_varint(value)


def _build_notebook_token(notebook_path: str, title: str) -> str:
    """Build the base64 protobuf token for a NotebookLM notebook.

    Protobuf structure (discovered via Chrome DevTools XHR capture, Feb 2026):
      field 1 (LEN) → field 15 (LEN) → field 1 (LEN): "notebooks/{uuid}"
      field 2 (VARINT): 20   — type code for NLM notebook
      field 3 (LEN): title
      field 9 (VARINT): 14   — source indicator for NLM
      field 12 (LEN): ""     — empty MIME type

    The resulting base64 string is placed at knowledge[i][0][5] in the
    create/update payload, the same position as $Aed tokens for Drive files.
    """
    inner = _encode_len_field(1, notebook_path.encode("utf-8"))
    field15 = _encode_len_field(15, inner)
    proto = (
        _encode_len_field(1, field15)
        + _encode_varint_field(2, 20)
        + _encode_len_field(3, title.encode("utf-8"))
        + _encode_varint_field(9, 14)
        + _encode_len_field(12, b"")
    )
    return base64.b64encode(proto).decode("ascii")


class GemsService:
    """Service for managing Gemini Gems (custom system prompts).

    Uses batchexecute RPCs for all CRUD operations.
    """

    def __init__(self, client: GeminiClient):
        self.client = client

    async def list_gems(
        self,
        predefined: bool = False,
        shared: bool = False,
    ) -> list[Gem]:
        """List available gems.

        Args:
            predefined: If True, list Google's premade gems.
            shared: If True, list gems shared with you by other users.
            If both are False (default), lists your custom gems.
        """
        if predefined:
            category = GemCategory.PREDEFINED
        elif shared:
            category = GemCategory.SHARED
        else:
            category = GemCategory.CUSTOM

        # Payload format: [category, ["en"], detail_level]
        # detail_level: 0 = truncated prompts, 1 = full prompts
        # List uses 0 (lightweight); use get_gem() for full instructions.
        payload = json.dumps([category, ["en"], 0])

        results = await self.client.execute_rpc_with_browser_cookies(
            rpc_id=RPC.LIST_GEMS,
            payload=payload,
        )

        gems = []
        for result in results:
            if result.data and isinstance(result.data, list):
                gem_list = get_nested(result.data, [2]) or []
                for gem_data in gem_list:
                    if isinstance(gem_data, list):
                        resources = _parse_resources(get_nested(gem_data, [1, 10]))
                        tool_code = get_nested(gem_data, [1, 11], 0) or 0

                        gems.append(Gem(
                            id=get_nested(gem_data, [0], ""),
                            name=get_nested(gem_data, [1, 0], ""),
                            description=get_nested(gem_data, [1, 1], ""),
                            prompt=get_nested(gem_data, [2, 0], ""),
                            predefined=predefined,
                            shared=shared,
                            resources=resources,
                            default_tool=tool_code,
                            default_tool_name=GEM_TOOL_NAMES.get(
                                tool_code, f"Unknown ({tool_code})"
                            ),
                        ))
        return gems

    async def _process_knowledge_files(self, file_paths: list[str]) -> list:
        """Upload local files and process them into gem knowledge entries.

        Each file goes through a 3-step flow (discovered via Chrome DevTools, Feb 2026):
        1. Resumable upload to push.clients6.google.com → upload_id
        2. POST to ProcessFile endpoint with upload_id → $Aed... token
        3. Token embedded in create/update payload at position 14

        Returns flat list of entries: [[None×5, token], ...].
        """
        import mimetypes
        from pathlib import Path

        file_svc = FileService(self.client)
        entries = []

        for file_path in file_paths:
            path = Path(file_path)
            filename = path.name
            mime_type, _ = mimetypes.guess_type(filename)
            if not mime_type:
                mime_type = "application/octet-stream"

            upload_id = await file_svc.upload(file_path)
            token = await self.client.process_gem_file(upload_id, filename, mime_type)
            entries.append([None, None, None, None, None, token])

        return entries

    async def _process_drive_files(self, file_ids: list[str]) -> list:
        """Resolve Google Drive file IDs into gem knowledge entries.

        No upload step needed — Drive files are passed by reference directly
        to the ProcessFile endpoint (discovered via Chrome DevTools, Feb 2026).

        Args:
            file_ids: List of Google Drive file IDs.

        Returns:
            Flat list of entries: [[None×5, token], ...].
        """
        entries = []
        for file_id in file_ids:
            info = await self.client.get_drive_file_info(file_id)
            token = await self.client.process_gem_drive_file(
                file_id=file_id,
                file_name=info["name"],
                mime_type=info["mime_type"],
            )
            entries.append([None, None, None, None, None, token])
        return entries

    async def list_notebooks(self) -> list[dict]:
        """List NotebookLM notebooks available for gem attachment.

        Uses the NXpLKc RPC (discovered via Chrome DevTools, Feb 2026).
        Response structure: [[[path, title, [ts, ns], count], ...]]

        Returns:
            List of dicts with keys: id, title, source_count.
        """
        payload = json.dumps([])
        results = await self.client.execute_rpc_with_browser_cookies(
            rpc_id=RPC.LIST_NLM_NOTEBOOKS,
            payload=payload,
        )
        notebooks = []
        for result in results:
            if not result.data or not isinstance(result.data, list):
                continue
            nb_list = get_nested(result.data, [0])
            if not isinstance(nb_list, list):
                continue
            for entry in nb_list:
                if not isinstance(entry, list) or len(entry) < 2:
                    continue
                path = entry[0] or ""
                if not isinstance(path, str):
                    continue
                nb_id = path.removeprefix("notebooks/")
                notebooks.append({
                    "id": nb_id,
                    "title": entry[1] or "",
                    "source_count": entry[3] if len(entry) > 3 else 0,
                })
        return notebooks

    async def _process_notebook_ids(self, notebook_ids: list[str]) -> list:
        """Build gem knowledge entries for NotebookLM notebooks.

        Unlike Drive/uploaded files, notebook tokens are generated client-side
        as base64-encoded protobuf — no server round-trip needed.
        (Discovered via Chrome DevTools XHR capture, Feb 2026.)

        Args:
            notebook_ids: List of NotebookLM notebook UUIDs.

        Returns:
            Flat list of entries: [[None×5, token], ...].
        """
        all_notebooks = await self.list_notebooks()
        title_map = {nb["id"]: nb["title"] for nb in all_notebooks}

        entries = []
        for nb_id in notebook_ids:
            title = title_map.get(nb_id, "")
            path = f"notebooks/{nb_id}"
            token = _build_notebook_token(path, title)
            entries.append([None, None, None, None, None, token])
        return entries

    async def create(
        self,
        name: str,
        description: str,
        prompt: str,
        knowledge_files: list[str] | None = None,
        drive_file_ids: list[str] | None = None,
        notebook_ids: list[str] | None = None,
        default_tool: int = 0,
    ) -> dict:
        """Create a new custom gem.

        Payload format confirmed via Chrome DevTools (Feb 2026).
        The inner array has 18 elements; the whole thing is wrapped in an outer array.
        Response data is [gem_id, true] on success.

        Args:
            knowledge_files: Optional list of local file paths to attach as knowledge files.
            drive_file_ids: Optional list of Google Drive file IDs to attach.
            notebook_ids: Optional list of NotebookLM notebook UUIDs to attach.
            default_tool: Tool code from GemDefaultTool (0=none, 14=image, etc.).
        """
        entries = await self._process_knowledge_files(knowledge_files) if knowledge_files else []
        if drive_file_ids:
            entries += await self._process_drive_files(drive_file_ids)
        if notebook_ids:
            entries += await self._process_notebook_ids(notebook_ids)
        knowledge = [entries] if entries else []
        # fmt: off
        inner = [name, description, prompt, None, None, None, None, None, 0, None, 1, None, None, None, knowledge, default_tool, None, 0]  # noqa: E501
        # fmt: on
        payload = json.dumps([inner])
        results = await self.client.execute_rpc_with_browser_cookies(
            rpc_id=RPC.CREATE_GEM,
            payload=payload,
        )
        data = results[0].data if results else None
        gem_id = get_nested(data, [0]) if isinstance(data, list) else None
        return {"status": "created", "gem_id": gem_id, "data": data}

    async def update(
        self,
        gem_id: str,
        name: str,
        description: str,
        prompt: str,
        knowledge_files: list[str] | None = None,
        drive_file_ids: list[str] | None = None,
        notebook_ids: list[str] | None = None,
        default_tool: int = 0,
    ) -> dict:
        """Update an existing custom gem.

        Payload format confirmed via Chrome DevTools (Feb 2026).
        Inner array mirrors the create format (18 elements).
        Response data is [true] on success.

        Args:
            knowledge_files: Optional list of local file paths to replace knowledge files.
            drive_file_ids: Optional list of Google Drive file IDs to attach.
            notebook_ids: Optional list of NotebookLM notebook UUIDs to attach.
            default_tool: Tool code from GemDefaultTool (0=none, 14=image, etc.).
        """
        entries = await self._process_knowledge_files(knowledge_files) if knowledge_files else []
        if drive_file_ids:
            entries += await self._process_drive_files(drive_file_ids)
        if notebook_ids:
            entries += await self._process_notebook_ids(notebook_ids)
        knowledge = [entries] if entries else []
        # fmt: off
        inner = [name, description, prompt, None, None, None, None, None, 0, None, 1, None, None, None, knowledge, default_tool, None, 0]  # noqa: E501
        # fmt: on
        payload = json.dumps([gem_id, inner])
        results = await self.client.execute_rpc_with_browser_cookies(
            rpc_id=RPC.UPDATE_GEM,
            payload=payload,
        )
        return {"status": "updated", "data": results[0].data if results else None}

    async def delete(self, gem_id: str) -> dict:
        """Delete a custom gem."""
        payload = json.dumps([gem_id])
        results = await self.client.execute_rpc_with_browser_cookies(
            rpc_id=RPC.DELETE_GEM,
            payload=payload,
        )
        return {"status": "deleted", "data": results[0].data if results else None}
