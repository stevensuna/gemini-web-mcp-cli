"""Execute the browser hook offline against both browser request APIs."""

import json
import shutil
import subprocess
from pathlib import Path
from urllib.parse import parse_qs, urlencode

import pytest

from gemini_web_mcp_cli.core.client import GeminiClient
from gemini_web_mcp_cli.core.token_factory import XHR_INTERCEPTOR_JS

NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="Node.js required to execute browser hook")
HARNESS = r"""
const fs = require('fs');
const {hook, scenario, drBody} = JSON.parse(fs.readFileSync(0, 'utf8'));
global.window = global;
let sent = [];
global.fetch = async function(input, init) { sent.push('fetch'); return 'forwarded'; };
global.XMLHttpRequest = class {
    open() {}
    setRequestHeader() {}
    send() { sent.push('xhr'); }
    abort() { this.aborted = true; }
};
eval(hook);
const stream = 'https://gemini.google.com/_/BardChatUi/data/assistant.lamda.BardFrontendService/StreamGenerate';
const open = 'https://geminiweb-pa.clients6.google.com/v1/processSession?X-HTTP-Session-Id=gsessionid';
const data = 'https://geminiweb-pa.clients6.google.com/v1/processSession?SID=synthetic';
const body = 'f.req=synthetic&at=synthetic';
async function attempt(input, init) {
    try { return await fetch(input, init); }
    catch(e) { return e.name; }
}
(async () => {
    let result;
    if (scenario === 'fetch-dr-request') {
        result = await attempt(new Request(stream, {method:'POST', body:drBody}));
    } else if (scenario === 'fetch-string') {
        result = await attempt(stream, {method:'POST', body, headers:{'X-Test':'synthetic'}});
    } else if (scenario === 'fetch-request') {
        const request = new Request(stream, {method:'POST', body, headers:{'X-Test':'original'}});
        result = await attempt(request);
        if (await request.text() !== body) throw Error('Request was consumed');
    } else if (scenario === 'fetch-override') {
        const request = new Request(stream, {method:'POST', body:'old', headers:{'X-Old':'old'}});
        result = await attempt(request, {body, headers:[['X-Test','override']]});
    } else if (scenario === 'fetch-form-duplicate') {
        result = await attempt(stream, {method:'POST', body:new URLSearchParams(body)});
        await attempt(stream, {method:'POST', body:'second'});
    } else if (scenario === 'fetch-session') {
        await attempt(open, {method:'POST', body:'count=0'});
        result = await attempt(data, {method:'POST', body:'count=1&req0___data__=synthetic'});
        await attempt(data, {method:'POST', body:'count=1&req0___data__=second'});
    } else if (scenario === 'passthrough') {
        await attempt('https://gemini.google.com/batchexecute', {method:'POST', body});
        await attempt(data, {method:'GET'});
        result = await attempt(data, {method:'POST', body:'count=0'});
    } else {
        const xhr = new XMLHttpRequest();
        if (scenario === 'xhr-session') {
            xhr.open('POST', open); xhr.send('count=0');
            xhr.open('POST', data); xhr.send('count=1&req0___data__=synthetic');
        } else {
            xhr.open('POST', '/_/BardChatUi/data/StreamGenerate');
            xhr.setRequestHeader('X-Test','synthetic'); xhr.send(body);
        }
        result = xhr.aborted;
    }
    console.log(JSON.stringify({result, sent, cap:window.__cap}));
})().catch(e => { console.error(e); process.exit(1); });
"""


def run_hook(scenario, hook=XHR_INTERCEPTOR_JS, dr_body=None):
    result = subprocess.run(
        [NODE, "-e", HARNESS],
        input=json.dumps({"hook": hook, "scenario": scenario, "drBody": dr_body}),
        text=True, capture_output=True, check=True, timeout=15,
    )
    return json.loads(result.stdout)


@pytest.mark.parametrize("scenario", ["fetch-string", "fetch-request", "fetch-override"])
def test_fetch_captures_body_and_headers_without_sending(scenario):
    result = run_hook(scenario)
    assert result["result"] == "AbortError"
    assert result["sent"] == []
    assert result["cap"]["transport"] == "streamgenerate"
    assert result["cap"]["body"] == "f.req=synthetic&at=synthetic"
    expected = {
        "fetch-string": {"x-test": "synthetic"},
        "fetch-request": {"x-test": "original", "content-type": "text/plain;charset=UTF-8"},
        "fetch-override": {"x-test": "override"},
    }
    assert result["cap"]["headers"] == expected[scenario]


def test_fetch_aborts_duplicates_and_keeps_first_capture():
    result = run_hook("fetch-form-duplicate")
    assert result["sent"] == []
    assert result["cap"]["body"] == "f.req=synthetic&at=synthetic"


@pytest.mark.parametrize("surface", ["fetch", "xhr"])
def test_session_open_passes_but_data_is_aborted(surface):
    result = run_hook(f"{surface}-session")
    assert result["sent"] == [surface]
    assert result["cap"]["transport"] == "processSession"
    assert "X-HTTP-Session-Id" in result["cap"]["url"]
    assert result["cap"]["body"] == "count=1&req0___data__=synthetic"


def test_other_requests_are_forwarded():
    result = run_hook("passthrough")
    assert result["sent"] == ["fetch"] * 3
    assert result["result"] == "forwarded"
    assert result["cap"] is None


def test_xhr_streamgenerate_still_aborts():
    result = run_hook("xhr-stream")
    assert result["sent"] == []
    assert result["result"] is True
    assert result["cap"]["headers"] == {"X-Test": "synthetic"}


def test_captured_fetch_envelope_is_compatible_with_existing_patcher():
    capture = Path(__file__).resolve().parents[1] / (
        "docs/research/transport/2026-10-21-fetch-streamgenerate.json"
    )
    fields = json.loads(capture.read_text())["body"]
    outer = fields["f.req"]["json"]
    original = outer[1]["json"]
    body = urlencode({"f.req": json.dumps([None, json.dumps(original)]), "at": "synthetic"})
    patched = GeminiClient._patch_captured_body(body, "new\nprompt")
    parsed = parse_qs(patched)
    inner = json.loads(json.loads(parsed["f.req"][0])[1])
    assert inner[0][0] == "new\nprompt"
    expected = json.loads(json.dumps(original))
    expected[0][0] = "new\nprompt"
    assert inner == expected
    assert parsed["at"] == ["synthetic"]


def test_live_dr_request_shape_is_captured_without_forwarding():
    fixture = Path(__file__).resolve().parents[1] / (
        "docs/research/transport/2026-10-21-dr-wire.json"
    )
    outer = json.loads(fixture.read_text())["capture2"][0]["payload"]
    inner = outer[1]
    assert inner[30] == [4, 16, 19]
    assert inner[49] == 1
    body = urlencode({"f.req": json.dumps([None, json.dumps(inner)]), "at": "synthetic"})
    result = run_hook("fetch-dr-request", dr_body=body)
    assert result["result"] == "AbortError"
    assert result["sent"] == []
    assert result["cap"]["body"] == body
    patched = GeminiClient._patch_captured_body(result["cap"]["body"], "research topic")
    actual = json.loads(json.loads(parse_qs(patched)["f.req"][0])[1])
    expected = json.loads(json.dumps(inner))
    expected[0][0] = "research topic"
    assert actual == expected
