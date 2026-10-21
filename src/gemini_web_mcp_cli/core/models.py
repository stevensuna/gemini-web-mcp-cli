"""Pydantic models for Gemini web interface requests and responses."""

from __future__ import annotations

from pydantic import BaseModel, Field


class RPCPayload(BaseModel):
    """A single RPC call payload for batchexecute."""

    rpc_id: str
    payload: str = "[]"
    identifier: str = "generic"

    def serialize(self) -> list:
        """Serialize to the format expected by batchexecute: [rpc_id, payload, None, identifier]."""
        return [self.rpc_id, self.payload, None, self.identifier]


class ConversationMetadata(BaseModel):
    """Conversation context for multi-turn chat."""

    cid: str = ""  # Conversation ID
    rid: str = ""  # Response ID
    rcid: str = ""  # Reply candidate ID
    extra: list = Field(default_factory=lambda: [None] * 7)

    def to_list(self) -> list:
        """Convert to the 10-element list expected by StreamGenerate."""
        return [self.cid, self.rid, self.rcid] + self.extra

    @classmethod
    def from_list(cls, data: list) -> ConversationMetadata:
        """Parse from the metadata list in a StreamGenerate response."""
        if not data or not isinstance(data, list):
            return cls()
        return cls(
            cid=data[0] if len(data) > 0 and data[0] else "",
            rid=data[1] if len(data) > 1 and data[1] else "",
            rcid=data[2] if len(data) > 2 and data[2] else "",
            extra=data[3:10] if len(data) > 3 else [None] * 7,
        )


class Candidate(BaseModel):
    """A single response candidate from StreamGenerate."""

    rcid: str | None = None
    text: str | None = None
    thoughts: str | None = None
    web_images: list | None = None
    generated_images: list | None = None
    generated_music: list | None = None
    generated_video: list | None = None


class StreamResponse(BaseModel):
    """Parsed response from a StreamGenerate call."""

    metadata: ConversationMetadata = Field(default_factory=ConversationMetadata)
    candidates: list[Candidate] = Field(default_factory=list)
    text: str | None = None
    thoughts: str | None = None
    is_complete: bool = False
    server_model_hash: str | None = None
    server_model_label: str | None = None

    @property
    def has_images(self) -> bool:
        return any(
            c.generated_images
            for c in self.candidates
            if c.generated_images
        )

    @property
    def has_music(self) -> bool:
        return any(
            c.generated_music
            for c in self.candidates
            if c.generated_music
        )

    @property
    def has_video(self) -> bool:
        return any(
            c.generated_video
            for c in self.candidates
            if c.generated_video
        )


class BatchResult(BaseModel):
    """A single result from a batchexecute response."""

    rpc_id: str | None = None
    data: object = None
    raw: str | None = None
