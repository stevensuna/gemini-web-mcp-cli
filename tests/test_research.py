"""Research must never substitute a plan or ordinary answer for a report."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from gemini_web_mcp_cli.core.exceptions import ResearchError
from gemini_web_mcp_cli.services.research import ResearchService


@pytest.fixture
def client(tmp_path):
    return SimpleNamespace(
        profile_manager=SimpleNamespace(profiles_dir=tmp_path),
        auth_manager=SimpleNamespace(resolved_profile_name="test"),
        _ensure_token_factory=Mock(),
    )


def test_state_is_atomic_private_and_survives_instances(client):
    svc = ResearchService(client)
    state = {"version": 1, "cid": "c_abc123", "status": "running", "target_id": "page"}
    svc._save(state)
    assert svc.state_path.stat().st_mode & 0o777 == 0o600
    assert ResearchService(client)._load() == state
    assert list(svc.state_path.parent.iterdir()) == [svc.state_path]
    client.auth_manager.resolved_profile_name = "other"
    assert ResearchService(client)._load() == {}


@pytest.mark.parametrize("value", ["{", "[]", '{"version":2}',
                                   '{"version":1,"cid":"c_../other"}'])
def test_invalid_state_fails_closed(client, value):
    svc = ResearchService(client)
    svc.state_path.parent.mkdir()
    svc.state_path.write_text(value)
    with pytest.raises(ResearchError):
        svc._load()


async def test_only_completed_report_can_be_returned_or_downloaded(client, tmp_path):
    svc = ResearchService(client)
    svc.poll_status = AsyncMock(return_value={"status": "running", "text": "research plan"})
    with pytest.raises(ResearchError, match="not ready"):
        await svc.download(tmp_path / "report.md")
    assert not (tmp_path / "report.md").exists()
    svc.poll_status.return_value = {"status": "completed", "text": "Actual report with citations"}
    assert await svc.report() == "Actual report with citations"
    assert (await svc.download(tmp_path / "report.md")).read_text() == svc.poll_status.return_value[
        "text"
    ]


async def test_completion_timeout_does_not_resend(client):
    svc = ResearchService(client)
    svc.poll_status = AsyncMock(return_value={"status": "running"})
    with pytest.raises(ResearchError, match="timed out"):
        await svc.wait_for_completion(max_wait=0)
    client._ensure_token_factory.assert_not_called()


async def test_status_caches_report_and_fresh_instance_returns_it(client, monkeypatch):
    svc = ResearchService(client)
    svc._save({"version": 1, "cid": "c_123", "status": "running", "target_id": "page"})
    monkeypatch.setattr(svc, "_page", lambda state: "ws")
    monkeypatch.setattr(svc, "_snapshot", lambda ws: {
        "cid": "c_123", "report_ready": True, "report": "Real research report",
    })
    assert (await svc.poll_status())["status"] == "completed"
    other = ResearchService(client)
    other._page = Mock(side_effect=AssertionError("Must use completed durable report"))
    assert await other.report() == "Real research report"


async def test_status_rejects_wrong_conversation(client, monkeypatch):
    svc = ResearchService(client)
    svc._save({"version": 1, "cid": "c_123", "status": "running"})
    monkeypatch.setattr(svc, "_page", lambda state: "ws")
    monkeypatch.setattr(svc, "_snapshot", lambda ws: {
        "cid": "c_other", "report_ready": True, "report": "Unrelated report",
    })
    with pytest.raises(ResearchError, match="not loaded"):
        await svc.report()
    assert "report" not in svc._load()


@pytest.mark.parametrize("activation", ["not_found", "disabled"])
def test_plan_fails_before_send_if_dr_cannot_be_enabled(client, monkeypatch, activation):
    svc = ResearchService(client)
    monkeypatch.setattr(svc, "_page", lambda state, **kw: "dedicated-ws")
    calls = []

    def js(ws, script):
        calls.append(script)
        if "!!document.querySelector" in script:
            return True
        return activation

    monkeypatch.setattr("gemini_web_mcp_cli.core.cdp.run_js", js)
    with pytest.raises(ResearchError, match="nothing sent"):
        svc._create_plan("topic", None)
    assert not any("send-button" in script for script in calls)
    assert not svc.state_path.exists()


def test_plan_then_confirmation_uses_pinned_page_once(client, monkeypatch):
    svc = ResearchService(client)

    def page(state, **kw):
        state["target_id"] = "dedicated-target"
        return "dedicated-ws"

    monkeypatch.setattr(svc, "_page", page)
    monkeypatch.setattr("gemini_web_mcp_cli.services.research.time.sleep", lambda _: None)
    calls = []

    def js(ws, script):
        assert ws == "dedicated-ws"
        calls.append(script)
        if "!!document.querySelector" in script:
            return True
        if "toolNames" in script:
            assert 'Deep research' in script
            return "activated"
        if 'aria-label="Start research"' in script:
            assert svc._load()["status"] == "starting"
            return True

    monkeypatch.setattr("gemini_web_mcp_cli.core.cdp.run_js", js)
    monkeypatch.setattr(svc, "_snapshot", lambda ws: {
        "cid": "c_123", "plan_ready": True, "text": "Plan",
    })
    assert svc._create_plan("topic", None).text == "Plan"
    assert ResearchService(client)._load()["target_id"] == "dedicated-target"
    assert svc._start().metadata.cid == "c_123"
    assert svc._load()["status"] == "running"
    with pytest.raises(ResearchError, match="No unconfirmed"):
        svc._start()
    assert sum('aria-label="Start research"' in s for s in calls) == 1


def test_browser_chooses_saved_target_instead_of_first_tab(client, monkeypatch):
    from gemini_web_mcp_cli.core import cdp

    client._ensure_token_factory.return_value._port = 9224
    monkeypatch.setattr(cdp, "get_pages", lambda port: [
        {"id": "unrelated", "webSocketDebuggerUrl": "wrong"},
        {"id": "research", "webSocketDebuggerUrl": "correct"},
    ])
    svc = ResearchService(client)
    assert svc._page({"target_id": "research", "cid": "c_123"}) == "correct"


@pytest.mark.parametrize("scenario,ready", [
    ("ordinary-answer", False), ("plan", False), ("report-streaming", False),
    ("report", True),
])
def test_snapshot_requires_research_report_and_export_control(scenario, ready):
    import shutil
    import subprocess

    from gemini_web_mcp_cli.services.research import SNAPSHOT_JS

    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js required to execute snapshot")
    harness = r'''
const fs = require('fs');
const {script, scenario} = JSON.parse(fs.readFileSync(0, 'utf8'));
global.location = {pathname:'/app/abc123'};
const panel = {
    querySelector(selector) {
        if(selector === 'message-content .markdown') return {innerText:'Actual report'};
        if(selector.includes('Export menu')) return scenario === 'report' ? {disabled:false} : null;
    }
};
global.document = {
    querySelector(selector) {
        if(selector === 'deep-research-immersive-panel') {
            return scenario.startsWith('report') ? panel : null;
        }
        if(selector.includes('Start research')) {
            return scenario === 'plan' ? {disabled:false} : null;
        }
        if(selector === 'main') return {innerText:'A plain answer or plan is not a report'};
        return null;
    }
};
console.log(JSON.stringify(eval(script)));
'''
    result = subprocess.run(
        [node, "-e", harness], input=json.dumps({"script": SNAPSHOT_JS, "scenario": scenario}),
        text=True, capture_output=True, check=True, timeout=15,
    )
    snapshot = json.loads(result.stdout)
    assert snapshot["report_ready"] is ready
    assert snapshot["cid"] == "c_abc123"
