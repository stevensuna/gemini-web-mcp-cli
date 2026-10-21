"""Deep Research service: start research, poll progress, get reports."""

from __future__ import annotations

import asyncio

from loguru import logger

from gemini_web_mcp_cli.core.client import GeminiClient
from gemini_web_mcp_cli.core.constants import RPC
from gemini_web_mcp_cli.core.models import ConversationMetadata, StreamResponse


class ResearchService:
    """Service for Gemini Deep Research.

    Deep Research flow:
    1. Send query via StreamGenerate -> get research plan
    2. Confirm "Start research" via StreamGenerate -> research begins
    3. Poll with kwDCne RPC for progress updates
    4. Final result delivered as stream response

    The Deep Research tool must be enabled in the prompt or UI.
    """

    def __init__(self, client: GeminiClient):
        self.client = client
        self._metadata: ConversationMetadata | None = None

    async def create_plan(self, query: str, model: str | None = None) -> StreamResponse:
        """Send a research query and get back a research plan.

        The plan contains numbered steps that Gemini will follow.
        """
        response = await self.client.send(prompt=query, model=model)
        if response.metadata and response.metadata.cid:
            self._metadata = response.metadata
        return response

    async def start(self) -> StreamResponse:
        """Confirm and start the research (after reviewing the plan).

        Must be called after create_plan() in the same conversation.
        """
        response = await self.client.send(
            prompt="Start research",
            metadata=self._metadata,
        )
        if response.metadata and response.metadata.cid:
            self._metadata = response.metadata
        return response

    async def poll_status(self, source_path: str | None = None) -> dict:
        """Poll for research progress using kwDCne RPC.

        Returns status data including thinking process and sources found.
        """
        path = source_path or "/app"
        if self._metadata and self._metadata.cid:
            path = f"/app/{self._metadata.cid.replace('c_', '')}"

        results = await self.client.execute_rpc(
            rpc_id=RPC.ASYNC_POLL,
            source_path=path,
        )
        if results:
            return {"status": "polled", "data": results[0].data}
        return {"status": "no_result"}

    async def wait_for_completion(
        self,
        poll_interval: float = 10.0,
        max_wait: float = 600.0,
    ) -> dict:
        """Poll repeatedly until research completes or timeout."""
        elapsed = 0.0
        while elapsed < max_wait:
            result = await self.poll_status()
            logger.debug(f"Research poll ({elapsed:.0f}s): {result.get('status')}")
            # Check if research is complete (heuristic based on response structure)
            if result.get("data") and isinstance(result["data"], list):
                data = result["data"]
                if len(data) > 0 and data[0] is True:
                    return result
            await asyncio.sleep(poll_interval)
            elapsed += poll_interval

        return {"status": "timeout", "elapsed": elapsed}
