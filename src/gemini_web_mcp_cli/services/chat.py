"""Chat service: send messages, stream responses, manage conversations."""

from __future__ import annotations

import os
import re

from gemini_web_mcp_cli.core.client import GeminiClient
from gemini_web_mcp_cli.core.constants import Model
from gemini_web_mcp_cli.core.exceptions import AttachmentNotRead
from gemini_web_mcp_cli.core.models import ConversationMetadata, StreamResponse

# Replies that mean Gemini never saw the attachment (issue #6). Only the start
# of the reply is checked: that is where Gemini says it, and it keeps normal
# answers that later discuss "unable to view" content from matching.
_ATTACHMENT_NOT_READ = re.compile(
    r"\b(?:can(?:no|')t|could(?:n't| not)|unable to|am not able to|I'm not able to)\s+"
    r"(?:open|view|access|read|see|play|watch|load|process)\s+"
    r"(?:the |this |that |your |any )?(?:attached |uploaded )?"
    r"(?:file|files|attachment|attachments|video|videos|image|images|document|pdf|audio)\b"
    r"|\b(?:no|don't see an?y?|do not see an?y?)\s+(?:file|attachment|video|image|document)s?\s+"
    r"(?:was |were |is |has been )?(?:attached|uploaded|provided|included)\b",
    re.IGNORECASE,
)
_CHECK_CHARS = 600


def attachment_not_read(text: str) -> bool:
    """True if the reply opens by saying the attachment could not be read."""
    return bool(_ATTACHMENT_NOT_READ.search((text or "")[:_CHECK_CHARS]))


class ChatService:
    """Service for chat interactions with Gemini.

    Wraps GeminiClient.send() with conversation state management
    and convenience methods.
    """

    def __init__(self, client: GeminiClient):
        self.client = client
        self._metadata: ConversationMetadata | None = None

    async def send(
        self,
        prompt: str,
        model: str | Model | None = None,
        conversation_id: str | None = None,
        gem_id: str | None = None,
        files: list[str] | None = None,
        extended_thinking: bool | None = None,
        thinking_level: str | None = None,
        task: bool = False,
    ) -> StreamResponse:
        """Send a message and get a complete response.

        For multi-turn conversations, the metadata is automatically
        tracked between calls.

        Args:
            files: Optional list of file paths to upload and attach.
            extended_thinking: Independently enable or disable Thinking
                               level High (formerly Extended thinking).
            thinking_level: ``low``, ``medium``, or ``high``. Wins over
                            ``extended_thinking`` when set.
            task: Send through the Task composer control instead of Chat.
        """
        import mimetypes
        from pathlib import Path

        from gemini_web_mcp_cli.services.file import FileService, build_file_data

        file_data = None
        if files:
            file_data = []
            file_service = FileService(self.client)
            for fpath in files:
                p = Path(fpath)
                file_id = await file_service.upload(p)
                mime_type, _ = mimetypes.guess_type(p)
                mime_type = mime_type or "application/octet-stream"

                file_data.append(build_file_data(file_id, p.name, mime_type))

        # Use stored metadata for multi-turn, or start fresh
        metadata = self._metadata if self._metadata and not conversation_id else None

        response = await self.client.send(
            prompt=prompt,
            model=model,
            extended_thinking=extended_thinking,
            thinking_level=thinking_level,
            task=task,
            metadata=metadata,
            gem_id=gem_id,
            file_data=file_data,
        )

        # Update metadata for next turn
        if response.metadata and response.metadata.cid:
            self._metadata = response.metadata

        if (
            files
            and os.environ.get("GEMCLI_ATTACHMENT_CHECK", "1") != "0"
            and attachment_not_read(response.text)
        ):
            names = ", ".join(os.path.basename(f) for f in files)
            raise AttachmentNotRead(
                f"Gemini did not read the attachment ({names}); its reply says it "
                "could not open it, so the answer was withheld (it is often "
                "invented). Retry, check `gemcli -p <profile> doctor --deep`, or "
                "try another profile. Set GEMCLI_ATTACHMENT_CHECK=0 to disable.",
                reply=response.text,
            )

        return response

    def reset(self) -> None:
        """Reset conversation state (start a new conversation)."""
        self._metadata = None

    @property
    def conversation_id(self) -> str | None:
        """Get the current conversation ID, if in a multi-turn conversation."""
        if self._metadata:
            return self._metadata.cid
        return None
