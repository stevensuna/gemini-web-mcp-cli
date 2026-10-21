"""Deep Research plans, confirmation, and durable per-profile progress."""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
import time
from pathlib import Path

from gemini_web_mcp_cli.core.client import GeminiClient
from gemini_web_mcp_cli.core.exceptions import ResearchError
from gemini_web_mcp_cli.core.models import ConversationMetadata, StreamResponse

SNAPSHOT_JS = r"""
(() => {
    const match = location.pathname.match(/\/app\/([a-zA-Z0-9]+)$/);
    const start = document.querySelector('button[aria-label="Start research"]');
    const plan = document.querySelector('deep-research-confirmation-widget');
    const panel = document.querySelector('deep-research-immersive-panel');
    const report = panel?.querySelector('message-content .markdown');
    const exportButton = panel?.querySelector('button[aria-label="Export menu"]');
    const text = document.querySelector('main')?.innerText || '';
    return {
        cid: match ? 'c_' + match[1] : null,
        plan_ready: !!start && !start.disabled,
        report_ready: !!report?.innerText?.trim() && !!exportButton && !exportButton.disabled,
        report: report?.innerText || '',
        text: plan?.innerText || '',
        failed: /Something went wrong|I seem to be encountering an error/.test(text)
    };
})()
"""


class ResearchService:
    """Keep the active research conversation across CLI and MCP processes."""

    def __init__(self, client: GeminiClient):
        self.client = client
        self.state_path = (
            client.profile_manager.profiles_dir
            / client.auth_manager.resolved_profile_name / "research.json"
        )

    def _load(self) -> dict:
        try:
            state = json.loads(self.state_path.read_text())
        except FileNotFoundError:
            return {}
        except (ValueError, OSError) as e:
            raise ResearchError("Cannot read research state.") from e
        if not isinstance(state, dict) or state.get("version") != 1:
            raise ResearchError("Unsupported research state.")
        cid = state.get("cid")
        if cid is not None and (
            not isinstance(cid, str) or not cid.startswith("c_") or not cid[2:].isalnum()
        ):
            raise ResearchError("Invalid research conversation id.")
        return state

    def _save(self, state: dict) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix=".research-", dir=self.state_path.parent)
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(state, f)
                f.flush()
                os.fsync(f.fileno())
            os.replace(name, self.state_path)
        finally:
            Path(name).unlink(missing_ok=True)

    def _page(self, state: dict, *, new: bool = False) -> str:
        import httpx

        from gemini_web_mcp_cli.core.cdp import get_pages, navigate_to_url

        factory = self.client._ensure_token_factory()
        factory.ensure_ready()
        pages = get_pages(factory._port)
        page = next((p for p in pages if p.get("id") == state.get("target_id")), None)
        if new or not page:
            response = httpx.put(
                f"http://127.0.0.1:{factory._port}/json/new?https://gemini.google.com/app",
                timeout=15,
            )
            response.raise_for_status()
            page = response.json()
            state["target_id"] = page["id"]
            if state.get("cid"):
                navigate_to_url(page["webSocketDebuggerUrl"],
                                f"https://gemini.google.com/app/{state['cid'][2:]}")
        return page["webSocketDebuggerUrl"]

    def _snapshot(self, ws: str) -> dict:
        from gemini_web_mcp_cli.core.cdp import run_js

        return run_js(ws, SNAPSHOT_JS) or {}

    def _create_plan(self, query: str, model: str | None) -> StreamResponse:
        from gemini_web_mcp_cli.core.cdp import run_js
        from gemini_web_mcp_cli.core.locks import profile_lock
        from gemini_web_mcp_cli.core.token_factory import (
            ACTIVATE_TOOL_JS,
            CLICK_SEND_JS,
            SET_MODEL_PICKER_JS,
            TYPE_PROMPT_JS,
        )

        factory = self.client._ensure_token_factory()
        factory.ensure_ready()
        with profile_lock(self.client.auth_manager.resolved_profile_name):
            state = self._load()
            if state.get("status") in ("planning", "starting", "running"):
                raise ResearchError("Research already active for this profile.")
            state = {"version": 1, "status": "planning"}
            ws = self._page(state, new=True)
            for _ in range(30):
                if run_js(ws, "!!document.querySelector('[contenteditable=true]')"):
                    break
                time.sleep(1)
            else:
                raise ResearchError("Research composer did not load; nothing sent.")
            if model:
                resolved = self.client._resolve_model(model, None)
                result = run_js(ws, SET_MODEL_PICKER_JS.replace(
                    "{hash}", resolved.hash
                ).replace("{level}", resolved.thinking_label))
                if result != "set":
                    raise ResearchError(f"Cannot select research model ({result}); nothing sent.")
            result = run_js(ws, ACTIVATE_TOOL_JS.format(
                tool_names_json=json.dumps(["Deep research"])
            ))
            if result not in ("activated", "already_active"):
                raise ResearchError(f"Cannot activate Deep research ({result}); nothing sent.")
            run_js(ws, TYPE_PROMPT_JS.format(prompt=" ".join(query.split())))
            time.sleep(0.5)
            self._save(state)
            run_js(ws, CLICK_SEND_JS)
            for _ in range(120):
                snapshot = self._snapshot(ws)
                if snapshot.get("cid"):
                    state["cid"] = snapshot["cid"]
                    self._save(state)
                if snapshot.get("plan_ready") and state.get("cid"):
                    state["status"] = "planned"
                    self._save(state)
                    return StreamResponse(
                        text=snapshot.get("text"),
                        metadata=ConversationMetadata(cid=state["cid"]),
                    )
                if snapshot.get("failed"):
                    raise ResearchError("Gemini could not create the research plan.")
                time.sleep(1)
        raise ResearchError("Research plan timed out; no second send attempted.")

    async def create_plan(self, query: str, model: str | None = None) -> StreamResponse:
        return await asyncio.to_thread(self._create_plan, query, model)

    def _start(self) -> StreamResponse:
        from gemini_web_mcp_cli.core.cdp import run_js
        from gemini_web_mcp_cli.core.locks import profile_lock

        self.client._ensure_token_factory().ensure_ready()
        with profile_lock(self.client.auth_manager.resolved_profile_name):
            state = self._load()
            if state.get("status") != "planned":
                raise ResearchError("No unconfirmed research plan.")
            ws = self._page(state)
            state["status"] = "starting"
            self._save(state)
            result = run_js(ws, """(() => {
                const b = document.querySelector('button[aria-label="Start research"]');
                if (!b || b.disabled) return false;
                b.click(); return true;
            })()""")
            if not result:
                state["status"] = "planned"
                self._save(state)
                raise ResearchError("Research plan has no Start research control; nothing sent.")
            state["status"] = "running"
            self._save(state)
            return StreamResponse(metadata=ConversationMetadata(cid=state["cid"]))

    async def start(self) -> StreamResponse:
        return await asyncio.to_thread(self._start)

    def _poll_status(self) -> dict:
        from gemini_web_mcp_cli.core.locks import profile_lock

        with profile_lock(self.client.auth_manager.resolved_profile_name):
            state = self._load()
            if not state:
                raise ResearchError("No active research for this profile.")
            if state.get("status") == "completed":
                return {"status": "completed", "text": state["report"], "cid": state["cid"]}
            ws = self._page(state)
            snapshot = self._snapshot(ws)
            if state["status"] == "planning" and snapshot.get("cid"):
                state["cid"] = snapshot["cid"]
            if snapshot.get("cid") != state.get("cid"):
                raise ResearchError("Research conversation is not loaded; try status later.")
            if snapshot.get("failed"):
                state["status"] = "failed"
            elif snapshot.get("plan_ready") and state["status"] == "planning":
                state["status"] = "planned"
            elif snapshot.get("report_ready"):
                state["status"] = "completed"
                state["report"] = snapshot["report"]
            self._save(state)
            result = {"status": state["status"], "cid": state.get("cid")}
            if state.get("report"):
                result["text"] = state["report"]
            return result

    async def poll_status(self) -> dict:
        return await asyncio.to_thread(self._poll_status)

    async def report(self) -> str:
        result = await self.poll_status()
        if result.get("status") != "completed" or not result.get("text"):
            raise ResearchError("Research report is not ready.")
        return result["text"]

    async def download(self, output_path: str | Path) -> Path:
        text = await self.report()
        path = Path(output_path).expanduser()
        path.write_text(text, encoding="utf-8")
        return path

    async def wait_for_completion(
        self, poll_interval: float = 10.0, max_wait: float = 600.0,
    ) -> dict:
        deadline = time.monotonic() + max_wait
        while time.monotonic() < deadline:
            result = await self.poll_status()
            if result["status"] == "completed":
                return result
            await asyncio.sleep(poll_interval)
        raise ResearchError("Research timed out; use research status/report to resume.")
