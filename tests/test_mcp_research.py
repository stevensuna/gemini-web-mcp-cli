"""Exercise the research tool boundary and a real offline stdio server."""

import json
import os
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.server.fastmcp.exceptions import ToolError

from gemini_web_mcp_cli import mcp as server
from gemini_web_mcp_cli.core.exceptions import APIError, PromptEscaped
from gemini_web_mcp_cli.core.models import ConversationMetadata, StreamResponse


@pytest.fixture
def mcp_service(monkeypatch):
    svc = SimpleNamespace(
        create_plan=AsyncMock(return_value=StreamResponse(text="Plan")),
        start=AsyncMock(return_value=StreamResponse(metadata=ConversationMetadata(cid="c_123"))),
        poll_status=AsyncMock(return_value={"status": "running"}),
        report=AsyncMock(return_value="Completed research report"),
        download=AsyncMock(return_value=Path("report.md")),
    )
    monkeypatch.setattr(server, "_get_client", AsyncMock(return_value=object()))
    monkeypatch.setattr("gemini_web_mcp_cli.services.research.ResearchService", lambda c: svc)
    return svc


async def test_mcp_start_creates_plan_and_confirms(mcp_service):
    result = json.loads(await server.research("start", query="SI", model="flash"))
    assert result["status"] == "running"
    mcp_service.create_plan.assert_awaited_once_with("SI", model="flash")
    mcp_service.start.assert_awaited_once()


@pytest.mark.parametrize("action,expected", [
    ("status", {"status": "running"}),
    ("report", {"status": "completed", "text": "Completed research report"}),
    ("download", {"path": "report.md"}),
])
async def test_mcp_research_actions(mcp_service, action, expected):
    assert json.loads(await server.research(action, output_path="report.md")) == expected


@pytest.mark.parametrize("action", ["unknown", "start", "download"])
async def test_mcp_research_validates_before_client_init(monkeypatch, action):
    client = AsyncMock()
    monkeypatch.setattr(server, "_get_client", client)
    with pytest.raises(ToolError):
        await server.research(action)
    client.assert_not_called()


@pytest.mark.parametrize("error", [PromptEscaped("escaped"), APIError("rpc failed")])
async def test_mcp_research_failures_are_tool_errors(mcp_service, error):
    mcp_service.create_plan.side_effect = error
    with pytest.raises(ToolError, match=str(error)):
        await server.research("start", query="SI")
    mcp_service.start.assert_not_called()


async def test_stdio_research_error_does_not_close_server(tmp_path):
    import sys

    script = tmp_path / "server.py"
    script.write_text('''
from gemini_web_mcp_cli import mcp as server
from gemini_web_mcp_cli.core.exceptions import PromptEscaped
async def fail():
    raise PromptEscaped("synthetic escaped request")
server._get_client = fail
server.main()
''')
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1] / "src"))
    async with stdio_client(StdioServerParameters(
        command=sys.executable, args=[str(script)], env=env,
    )) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(
                "research", {"action": "start", "query": "synthetic"},
                read_timeout_seconds=timedelta(seconds=15),
            )
            assert result.isError is True
            assert "synthetic escaped request" in result.content[0].text
            await session.send_ping()
            assert (await session.list_tools()).tools

async def test_mcp_start_omitted_model_uses_browser_default(mcp_service):
    result = json.loads(await server.research("start", query="Metre Convention"))
    assert result["status"] == "running"
    mcp_service.create_plan.assert_awaited_once_with("Metre Convention", model=None)
    mcp_service.start.assert_awaited_once()


@pytest.mark.parametrize("method,action,kwargs", [
    ("start", "start", {"query": "topic"}),
    ("poll_status", "status", {}),
    ("report", "report", {}),
    ("download", "download", {"output_path": "report.md"}),
])
async def test_mcp_each_service_step_failure_is_tool_error(mcp_service, method, action, kwargs):
    getattr(mcp_service, method).side_effect = RuntimeError("synthetic step failure")
    with pytest.raises(ToolError, match="synthetic step failure"):
        await server.research(action, **kwargs)
