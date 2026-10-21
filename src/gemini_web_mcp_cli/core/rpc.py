"""RPC transport for the Gemini web interface.

Handles building and sending requests to:
- batchexecute: for CRUD operations and polling
- StreamGenerate: for chat, image gen, video gen, and research
"""

from __future__ import annotations

import json
import random
from urllib.parse import urlencode

import httpx
from loguru import logger

from .constants import (
    DEFAULT_MODEL,
    GEMINI_HEADERS,
    INNER_REQ_LIST_SIZE,
    REQID_INCREMENT,
    Endpoint,
    Model,
)
from .models import (
    BatchResult,
    Candidate,
    ConversationMetadata,
    RPCPayload,
    StreamResponse,
)
from .parser import (
    parse_batchexecute_response,
    parse_stream_response,
)


def build_batchexecute_body(
    payloads: list[RPCPayload],
    access_token: str,
) -> str:
    """Build the form-encoded body for a batchexecute request.

    Body has two fields:
    - f.req: JSON-encoded batch payload
    - at: access token (SNlM0e)
    """
    serialized = [[p.serialize() for p in payloads]]
    f_req = json.dumps(serialized)
    return urlencode({"f.req": f_req, "at": access_token}) + "&"


def build_batchexecute_url(
    rpc_ids: list[str],
    reqid: int,
    build_label: str | None = None,
    session_id: str | None = None,
    source_path: str = "/app",
) -> str:
    """Build the full URL for a batchexecute request."""
    params: dict[str, str | int] = {
        "rpcids": ",".join(rpc_ids),
        "source-path": source_path,
    }
    if build_label:
        params["bl"] = build_label
    if session_id:
        params["f.sid"] = session_id
    params["hl"] = "en"
    params["_reqid"] = reqid
    params["rt"] = "c"

    return f"{Endpoint.BATCH_EXEC}?{urlencode(params)}"


def build_streamgenerate_body(
    prompt: str,
    access_token: str,
    metadata: ConversationMetadata | None = None,
    file_data: list | None = None,
    gem_id: str | None = None,
    tool_id: int | None = None,
    style_preset: dict | None = None,
    botguard_token: str | None = None,
    botguard_hash: str | None = None,
    video_orientation: str | None = None,
    image_aspect: str | None = None,
) -> str:
    """Build the form-encoded body for a StreamGenerate request.

    The inner_req_list is a 70-element list. Fields are based on captures
    from the Gemini web UI (Feb 2026). Many fields are required for the
    server to properly route model selection and enable features.

    Args:
        botguard_token: BotGuard token for inner[3]. Required for tool-based
                        generation (music, image, video). Obtained via Token Factory.
        botguard_hash: Challenge hash for inner[4]. Accompanies the BotGuard token.
        video_orientation: "landscape" (16:9) or "portrait" (9:16). Writes the
                           Omni video aspect-ratio fields (inner[55] and the
                           video-options array at inner[0][9]).
        image_aspect: Image aspect ratio ("1:1", "9:16", "3:4", "4:3", "16:9").
                      Writes inner[55] and the image-options array at inner[0][9].
    """
    import time
    import uuid

    from .constants import (
        IMAGE_ASPECTS,
        VIDEO_ORIENTATION_FLAGS,
        VIDEO_ORIENTATIONS,
        normalize_image_aspect,
        normalize_video_orientation,
    )

    inner = [None] * INNER_REQ_LIST_SIZE

    # [0] Message content
    inner[0] = [prompt, 0, None, file_data, None, None, 0]

    # Extend inner[0] for music style preset (inner[0][9] holds preset file data)
    if style_preset:
        from .music_presets import build_preset_file_data

        inner[0].extend([None, None, build_preset_file_data(style_preset)])

    # Extend inner[0] with video options for the Omni video tool.
    # Chrome sends: [..., null, null, [null*6, [[null, null, null, 1|2]]]]
    orientation = normalize_video_orientation(video_orientation)
    if orientation:
        flag = VIDEO_ORIENTATION_FLAGS[orientation]
        while len(inner[0]) < 9:
            inner[0].append(None)
        inner[0].append(
            [None, None, None, None, None, None, [[None, None, None, flag]]]
        )

    # Extend inner[0] with image options for the Images tool.
    # Chrome sends: [..., null, null, [null*6, [null, [null, "16:9"]]]]
    aspect = normalize_image_aspect(image_aspect)
    if aspect:
        while len(inner[0]) < 9:
            inner[0].append(None)
        inner[0].append(
            [None, None, None, None, None, None, [None, [None, aspect]]]
        )

    # [1] Language
    inner[1] = ["en"]

    # [2] Conversation metadata for multi-turn
    if metadata:
        inner[2] = metadata.to_list()
    else:
        inner[2] = ["", "", ""] + [None] * 7

    # [3] BotGuard token — required for tool-based generation (music, image, video)
    if botguard_token:
        inner[3] = botguard_token

    # [4] BotGuard challenge hash — accompanies the token
    if botguard_hash:
        inner[4] = botguard_hash

    # [6] Unknown, but web UI always sends [1]
    inner[6] = [1]

    # [7] Enable snapshot streaming
    inner[7] = 1

    # [10] Unknown, web UI sends 1
    inner[10] = 1

    # [11] Unknown, web UI sends 0
    inner[11] = 0

    # [17] Unknown, web UI sends [[0]]
    inner[17] = [[0]]

    # [18] Unknown, web UI sends 0
    inner[18] = 0

    # [19] Optional gem (custom system prompt)
    if gem_id:
        inner[19] = gem_id

    # [27] Unknown, web UI sends 1
    inner[27] = 1

    # [30] Capabilities array - web UI sends [4]
    inner[30] = [4]

    # [41] Unknown, web UI sends [1]
    inner[41] = [1]

    # [49] Tool activation ID (e.g. 21 for music generation)
    if tool_id is not None:
        inner[49] = tool_id

    # [54]/[55] Tool options (video aspect ratio / image aspect ratio)
    if orientation:
        inner[54] = []
        inner[55] = [[VIDEO_ORIENTATIONS[orientation]]]
    elif aspect:
        inner[54] = []
        inner[55] = [[IMAGE_ASPECTS[aspect]]]

    # [53] Unknown, web UI sends 0
    inner[53] = 0

    # [59] Session UUID (matches x-goog-ext-525005358-jspb header)
    inner[59] = str(uuid.uuid4()).upper()

    # [61] Empty array
    inner[61] = []

    # [66] Timestamp [seconds, nanoseconds]
    now = time.time()
    inner[66] = [int(now), int((now % 1) * 1_000_000_000)]

    # [68] Value 2 -- possibly model tier or response format
    inner[68] = 2

    f_req = json.dumps([None, json.dumps(inner)])
    return urlencode({"f.req": f_req, "at": access_token}) + "&"


def build_streamgenerate_url(
    reqid: int,
    build_label: str | None = None,
    session_id: str | None = None,
) -> str:
    """Build the full URL for a StreamGenerate request."""
    params: dict[str, str | int] = {}
    if build_label:
        params["bl"] = build_label
    if session_id:
        params["f.sid"] = session_id
    params["hl"] = "en"
    params["_reqid"] = reqid
    params["rt"] = "c"

    return f"{Endpoint.GENERATE}?{urlencode(params)}"


def build_headers(model: Model | None = None) -> dict[str, str]:
    """Build request headers, optionally including model selection."""
    headers = dict(GEMINI_HEADERS)
    if model and model.header:
        headers.update(model.header)
    return headers


def build_stream_response(response_text: str) -> StreamResponse:
    """Parse StreamGenerate response text into a StreamResponse.

    Merges all frames into one StreamResponse. Media fields (generated_images,
    generated_music, generated_video) are preserved across frames — if a later
    frame's candidate lacks media data that an earlier frame had, the earlier
    data is kept. This prevents losing music/video data when a trailing frame
    has text-only candidates.

    Used by both RPCTransport.stream_generate() and Token Factory path.
    """
    return merge_stream_frames(parse_stream_response(response_text))


def build_process_session_response(transcript: str) -> StreamResponse:
    """Parse a processSession backchannel transcript into a StreamResponse."""
    from .parser import parse_stream_body
    from .webchannel import bodies_from_text

    return merge_stream_frames([parse_stream_body(b) for b in bodies_from_text(transcript)])


def merge_stream_frames(parsed_frames: list[dict]) -> StreamResponse:
    """Merge parsed StreamGenerate-shaped frames into one StreamResponse."""
    result = StreamResponse()
    # Track media data from previous frames, keyed by candidate index.
    # Used to preserve generated_images/music/video across frame overwrites.
    _prev_media: dict[int, dict] = {}

    for frame in parsed_frames:
        if frame.get("metadata"):
            result.metadata = ConversationMetadata.from_list(frame["metadata"])

        if frame.get("candidates"):
            new_candidates = []
            for i, c in enumerate(frame["candidates"]):
                prev = _prev_media.get(i, {})
                candidate = Candidate(
                    rcid=c.get("rcid"),
                    text=c.get("text"),
                    thoughts=c.get("thoughts"),
                    web_images=c.get("web_images"),
                    generated_images=c.get("generated_images") or prev.get("images"),
                    generated_music=c.get("generated_music") or prev.get("music"),
                    generated_video=c.get("generated_video") or prev.get("video"),
                )
                new_candidates.append(candidate)
                # Update media tracking for this candidate index
                _prev_media[i] = {
                    "images": candidate.generated_images,
                    "music": candidate.generated_music,
                    "video": candidate.generated_video,
                }
            result.candidates = new_candidates

        if frame.get("text"):
            result.text = frame["text"]
        if frame.get("thoughts"):
            result.thoughts = frame["thoughts"]
        if frame.get("completion") is not None:
            result.is_complete = True

        # Server-confirmed model (appears in the final frame)
        if frame.get("server_model_hash"):
            result.server_model_hash = frame["server_model_hash"]
            result.server_model_label = frame.get("server_model_label")

    # The ids frame carries [cid, rid]; the reply candidate id lives on the
    # candidate. Follow-ups reply to it (to_list() -> [cid, rid, rcid, ...]).
    if result.metadata and not result.metadata.rcid and result.candidates:
        result.metadata.rcid = result.candidates[0].rcid or ""

    return result


class RPCTransport:
    """Handles HTTP communication with the Gemini web interface.

    Manages:
    - Request ID incrementing
    - batchexecute requests
    - StreamGenerate requests
    - Cookie management
    """

    def __init__(
        self,
        client: httpx.AsyncClient,
        access_token: str,
        build_label: str | None = None,
        session_id: str | None = None,
    ):
        self.client = client
        self.access_token = access_token
        self.build_label = build_label
        self.session_id = session_id
        self._reqid = random.randint(10000, 99999)

    def _next_reqid(self) -> int:
        """Get the next request ID and increment."""
        current = self._reqid
        self._reqid += REQID_INCREMENT
        return current

    async def batchexecute(
        self,
        payloads: list[RPCPayload],
        source_path: str = "/app",
    ) -> list[BatchResult]:
        """Execute one or more RPC calls via batchexecute.

        Returns a list of BatchResult objects.
        """
        rpc_ids = [p.rpc_id for p in payloads]
        url = build_batchexecute_url(
            rpc_ids=rpc_ids,
            reqid=self._next_reqid(),
            build_label=self.build_label,
            session_id=self.session_id,
            source_path=source_path,
        )
        body = build_batchexecute_body(payloads, self.access_token)
        headers = build_headers()

        logger.debug(f"batchexecute: {rpc_ids}")
        response = await self.client.post(url, content=body, headers=headers)
        response.raise_for_status()

        parsed = parse_batchexecute_response(response.text)
        return [
            BatchResult(rpc_id=r["rpc_id"], data=r["data"], raw=r["raw"])
            for r in parsed
        ]

    async def stream_generate(
        self,
        prompt: str,
        model: Model | None = None,
        metadata: ConversationMetadata | None = None,
        file_data: list | None = None,
        gem_id: str | None = None,
        tool_id: int | None = None,
        style_preset: dict | None = None,
        video_orientation: str | None = None,
        image_aspect: str | None = None,
    ) -> StreamResponse:
        """Send a message via StreamGenerate and parse the response.

        This is the primary endpoint for all generation: chat, images, video, music.
        """
        url = build_streamgenerate_url(
            reqid=self._next_reqid(),
            build_label=self.build_label,
            session_id=self.session_id,
        )
        body = build_streamgenerate_body(
            prompt=prompt,
            access_token=self.access_token,
            metadata=metadata,
            file_data=file_data,
            gem_id=gem_id,
            tool_id=tool_id,
            style_preset=style_preset,
            video_orientation=video_orientation,
            image_aspect=image_aspect,
        )
        headers = build_headers(model or DEFAULT_MODEL)

        logger.debug(f"StreamGenerate: {prompt[:50]}...")
        response = await self.client.post(url, content=body, headers=headers)
        response.raise_for_status()

        return build_stream_response(response.text)
