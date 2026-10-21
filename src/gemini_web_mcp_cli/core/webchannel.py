"""Gemini's processSession chat transport (a Closure WebChannel session).

Some accounts send chats to ``geminiweb-pa.clients6.google.com/v1/processSession``
instead of ``StreamGenerate``. The request is the same StreamGenerate ``inner``
array (BotGuard token at ``inner[3]``) wrapped in a setup message; the prompt
travels in a separate message; the model header is sent as protobuf inside the
channel's ``$httpHeaders`` URL parameter; the response frames carry
StreamGenerate-shaped bodies. See docs/research/transport/processSession.md.

Token Factory captures the channel-open URL and the setup message in Chrome
(aborting the data POST, so Chrome sends nothing). ``replay()`` then opens a
fresh channel from Python with Chrome's cookies and sends the real prompt.
"""

from __future__ import annotations

import asyncio
import base64
import json
import random
import string
import time
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit

import httpx
from loguru import logger

from . import protojspb
from .exceptions import APIError, AuthError
from .exceptions import TimeoutError as GeminiTimeoutError
from .parser import _utf16_char_count
from .setup_shape import SETUP_SHAPE

TRANSPORT_STREAMGENERATE = "streamgenerate"
TRANSPORT_PROCESS_SESSION = "processSession"

PROCESS_SESSION_URL = "https://geminiweb-pa.clients6.google.com/v1/processSession"
MODEL_BIN_HEADER = "x-goog-ext-525001261-bin"
CONTENT_TYPE_HEADER = "X-WebChannel-Content-Type"
JSON_CONTENT_TYPE = "application/json+protobuf"



# Client -> server messages (see processSession.md, "Forward messages").
HALF_CLOSE_MESSAGE = [None, None, None, [1]]
# Server -> client: the stream is finished.
END_OF_STREAM = [None, None, None, []]

# How long to keep reading after the final candidate for the title/completion
# frames and the end-of-stream marker.
_TAIL_TIMEOUT = 8.0


def _zx() -> str:
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=12))


# --------------------------------------------------------------------------
# Framing
# --------------------------------------------------------------------------


def split_frames(text: str) -> tuple[list[tuple[int, Any]], str]:
    """Split backchannel text into ``(array_id, payload)`` entries.

    Frames are ``<length>\\n<json>`` where length counts the JSON's UTF-16 code
    units (the newline is not counted, unlike StreamGenerate). Each JSON is a
    list of ``[array_id, payload]``. Returns (entries, unparsed remainder).
    """
    entries: list[tuple[int, Any]] = []
    pos = 0
    while pos < len(text):
        nl = text.find("\n", pos)
        if nl == -1 or not text[pos:nl].strip().isdigit():
            break
        length = int(text[pos:nl])
        start = nl + 1
        count, units = _utf16_char_count(text, start, length)
        if units < length:
            break  # incomplete frame
        chunk = text[start:start + count]
        pos = start + count
        try:
            frame = json.loads(chunk)
        except ValueError:
            logger.debug(f"processSession: unparsable frame {chunk[:100]!r}")
            continue
        for item in frame if isinstance(frame, list) else []:
            if isinstance(item, list) and len(item) == 2 and isinstance(item[0], int):
                entries.append((item[0], item[1]))
    return entries, text[pos:]


def payload_entry(payload: Any) -> list | None:
    """Return ``[flag, [id], null, [null, null, null, body]]`` from a data payload."""
    try:
        entry = payload[0][1][6][0]
    except (IndexError, KeyError, TypeError):
        return None
    return entry if isinstance(entry, list) else None


def payload_body(payload: Any) -> list | None:
    """The StreamGenerate-shaped body inside a data payload, if any."""
    entry = payload_entry(payload)
    try:
        body = entry[3][3] if entry else None
    except (IndexError, TypeError):
        return None
    return body if isinstance(body, list) else None


def is_final_candidate(payload: Any) -> bool:
    """True for the payload that carries the finished candidate (flag = 1)."""
    entry = payload_entry(payload)
    return bool(entry) and entry[0] == 1


def is_end_of_stream(payload: Any) -> bool:
    return isinstance(payload, list) and bool(payload) and payload[0] == END_OF_STREAM


def bodies_from_text(text: str) -> list[list]:
    """All StreamGenerate-shaped bodies in a backchannel transcript."""
    entries, _ = split_frames(text)
    return [b for _, p in entries if (b := payload_body(p)) is not None]


# --------------------------------------------------------------------------
# Forward-channel messages
# --------------------------------------------------------------------------


def decode_forward_body(body: str) -> list[Any]:
    """Decode ``count=N&ofs=K&req0___data__=...`` into JSPB messages.

    Messages are JSON arrays, or base64 binary protobuf on accounts whose page
    uses ``application/x-protobuf`` (converted to JSPB, see core/protojspb.py).
    """
    fields = dict(parse_qsl(body, keep_blank_values=True))
    count = int(fields.get("count", "0"))
    return [decode_message(fields[f"req{i}___data__"]) for i in range(count)]


def decode_message(data: str) -> Any:
    """One forward-channel message: JSON array or base64 binary protobuf."""
    if data.lstrip().startswith("["):
        return json.loads(data)
    try:
        raw = base64.b64decode(data + "=" * (-len(data) % 4), validate=True)
    except ValueError as e:
        raise ValueError(f"processSession message is neither JSON nor base64: {data[:40]!r}") from e
    return protojspb.to_jspb(raw, SETUP_SHAPE)


def use_json_encoding(open_url: str) -> str:
    """Declare JSON messages on the channel (the server accepts both encodings)."""
    parts = urlsplit(open_url)
    query = []
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        if key == "$httpHeaders":
            lines = [
                f"{CONTENT_TYPE_HEADER}:{JSON_CONTENT_TYPE}"
                if line.partition(":")[0].strip().lower() == CONTENT_TYPE_HEADER.lower()
                else line
                for line in value.split("\r\n")
            ]
            value = "\r\n".join(lines)
        query.append((key, value))
    return parts._replace(query=urlencode(query)).geturl()


def encode_forward_body(messages: list[Any], ofs: int) -> str:
    parts: dict[str, Any] = {"count": len(messages), "ofs": ofs}
    for i, m in enumerate(messages):
        parts[f"req{i}___data__"] = json.dumps(m, separators=(",", ":"), ensure_ascii=False)
    return urlencode(parts)


def find_setup_message(messages: list[Any]) -> list | None:
    """The setup message: ``[[[1, model_hash, lang, uuid], 0, ..., [.., [inner, ..]], ..]]``."""
    for m in messages:
        if isinstance(m, list) and m and isinstance(m[0], list) and setup_inner(m) is not None:
            return m
    return None


def setup_inner(setup: list) -> list | None:
    """The StreamGenerate ``inner`` array inside a setup message.

    ``setup[0][7] = [null, null, null, null, [inner, null, null, 1]]``.
    """
    try:
        inner = setup[0][7][4][0]
    except (IndexError, TypeError):
        return None
    return inner if isinstance(inner, list) else None


def extract_botguard(body: str) -> tuple[str | None, str | None]:
    """BotGuard token and challenge hash from a captured processSession data POST."""
    try:
        setup = find_setup_message(decode_forward_body(body))
    except (ValueError, KeyError, TypeError):
        return None, None
    inner = setup_inner(setup) if setup else None
    if not inner or len(inner) < 5:
        return None, None
    token = inner[3] if isinstance(inner[3], str) else None
    hash_val = inner[4] if isinstance(inner[4], str) else None
    return token, hash_val


# Conversation to continue: inner[71] = ["c_<cid>", null x6, ""] (processSession
# only; StreamGenerate uses inner[2]).
CONVERSATION_INDEX = 71


def set_conversation(inner: list, cid: str) -> None:
    """Point the setup at conversation ``cid`` unless Chrome already did."""
    cid = cid if cid.startswith("c_") else f"c_{cid}"
    current = inner[CONVERSATION_INDEX] if len(inner) > CONVERSATION_INDEX else None
    if isinstance(current, list) and current and current[0] == cid:
        return
    if len(inner) <= CONVERSATION_INDEX:
        inner.extend([None] * (CONVERSATION_INDEX + 1 - len(inner)))
    inner[CONVERSATION_INDEX] = [cid, None, None, None, None, None, None, ""]


def prompt_message(prompt: str) -> list:
    return [None, [1, None, None, None, None, None, None, None, [prompt]]]


# --------------------------------------------------------------------------
# Model header (protobuf) rewrite
# --------------------------------------------------------------------------


def _read_varint(b: bytes, i: int) -> tuple[int, int]:
    result = shift = 0
    while True:
        c = b[i]
        i += 1
        result |= (c & 0x7F) << shift
        shift += 7
        if c < 0x80:
            return result, i


def _varint(n: int) -> bytes:
    out = bytearray()
    while True:
        byte = n & 0x7F
        n >>= 7
        if n:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


def _pb_fields(b: bytes) -> list[tuple[int, int, bytes]]:
    """Top-level protobuf fields as (field number, wire type, encoded value)."""
    fields = []
    i = 0
    while i < len(b):
        key, j = _read_varint(b, i)
        field, wire = key >> 3, key & 7
        if wire == 0:
            _, k = _read_varint(b, j)
            value = b[j:k]
        elif wire == 2:
            n, k = _read_varint(b, j)
            k += n
            value = b[j:k]
        elif wire == 1:
            k = j + 8
            value = b[j:k]
        elif wire == 5:
            k = j + 4
            value = b[j:k]
        else:
            raise ValueError(f"unsupported protobuf wire type {wire}")
        fields.append((field, wire, value))
        i = k
    return fields


def rewrite_model_header(value: str, model_hash: str, category: int, toggle: int) -> str:
    """Set hash (field 5) and the category/thinking pair (fields 15/16).

    Field numbers are the JSPB header's array indexes + 1; other fields are kept
    byte for byte.
    """
    raw = base64.b64decode(value + "=" * (-len(value) % 4))
    replacements = {
        5: (2, _varint(len(model_hash)) + model_hash.encode()),
        15: (0, _varint(category)),
        16: (0, _varint(toggle)),
    }
    out = bytearray()
    seen = set()
    for field, wire, encoded in _pb_fields(raw):
        if field in replacements:
            wire, encoded = replacements[field]
            seen.add(field)
        out += _varint(field << 3 | wire) + encoded
    for field in sorted(set(replacements) - seen):
        wire, encoded = replacements[field]
        out += _varint(field << 3 | wire) + encoded
    return base64.b64encode(bytes(out)).decode()


def _header_tail(model) -> tuple[int, int] | None:
    parts = str(getattr(model, "header_tail", "")).split(",")
    if len(parts) != 2:
        return None
    try:
        return int(parts[0]), int(parts[1])
    except ValueError:
        return None


def apply_model(open_url: str, setup: list, model) -> str:
    """Point the captured channel at ``model``. Returns the new open URL.

    Chrome's UI picker decides the captured model; like the StreamGenerate path
    (which overwrites the JSPB header), the requested model wins.
    """
    tail = _header_tail(model)
    if not getattr(model, "hash", None) or tail is None:
        return open_url
    try:
        setup[0][0][1] = model.hash
    except (IndexError, TypeError):
        pass
    parts = urlsplit(open_url)
    query = parse_qsl(parts.query, keep_blank_values=True)
    new_query = []
    for key, value in query:
        if key == "$httpHeaders":
            lines = value.split("\r\n")
            for i, line in enumerate(lines):
                name, sep, val = line.partition(":")
                if sep and name.strip().lower() == MODEL_BIN_HEADER:
                    lines[i] = f"{name}:{rewrite_model_header(val.strip(), model.hash, *tail)}"
            value = "\r\n".join(lines)
        new_query.append((key, value))
    return parts._replace(query=urlencode(new_query)).geturl()


# --------------------------------------------------------------------------
# Replay
# --------------------------------------------------------------------------


async def replay(
    client: httpx.AsyncClient,
    open_url: str,
    messages: list[Any],
    cookies: dict[str, str],
    headers: dict[str, str],
    timeout: float,
) -> str:
    """Open a channel, send ``messages`` and return the backchannel transcript.

    Reads until the final candidate plus its title/completion frames arrive (or
    the server ends the stream), then half-closes and terminates the channel.
    """
    base = {
        "Origin": "https://gemini.google.com",
        "Referer": "https://gemini.google.com/",
    }
    ua = headers.get("user-agent") or headers.get("User-Agent")
    if ua:
        base["User-Agent"] = ua
    form = {**base, "Content-Type": "application/x-www-form-urlencoded"}

    parts = urlsplit(open_url)
    open_query = dict(parse_qsl(parts.query, keep_blank_values=True))
    rid = random.randint(10000, 89999)
    open_query.update(RID=str(rid), zx=_zx(), t="1")

    resp = await client.post(
        PROCESS_SESSION_URL, params=open_query, content="count=0",
        headers=form, cookies=cookies,
    )
    if resp.status_code in (401, 403):
        raise AuthError(f"processSession rejected the session (HTTP {resp.status_code}).")
    if resp.status_code != 200:
        raise APIError(f"processSession open failed: HTTP {resp.status_code}")
    gsid = resp.headers.get("x-http-session-id")
    entries, _ = split_frames(resp.text)
    sid = None
    for _, payload in entries:
        if isinstance(payload, list) and payload and payload[0] == "c":
            sid = payload[1]
    if not gsid or not sid:
        raise APIError(f"processSession open: no session ids in {resp.text[:120]!r}")

    state = {"aid": max((a for a, _ in entries), default=0), "rid": rid}

    def fwd_params(extra: dict | None = None) -> dict:
        state["rid"] += 1
        p = {"VER": "8", "gsessionid": gsid, "SID": sid, "RID": str(state["rid"]),
             "AID": str(state["aid"]), "zx": _zx(), "t": "1"}
        p.update(extra or {})
        return p

    async def post_messages(msgs: list[Any], ofs: int) -> None:
        r = await client.post(
            PROCESS_SESSION_URL, params=fwd_params(),
            content=encode_forward_body(msgs, ofs), headers=form, cookies=cookies,
        )
        if r.status_code != 200:
            raise APIError(f"processSession send failed: HTTP {r.status_code}")

    transcript: list[str] = []
    deadline = time.monotonic() + timeout
    final_at: float | None = None
    done = False
    sent = False
    half_closed = False
    completion_seen = False
    server_error: str | None = None
    closed = False
    empty_reopens = 0

    try:
        while not done and time.monotonic() < deadline:
            q = {"gsessionid": gsid, "VER": "8", "RID": "rpc", "SID": sid,
                 "AID": str(state["aid"]), "CI": "0", "TYPE": "xmlhttp", "zx": _zx(), "t": "1"}
            async with client.stream(
                "GET", PROCESS_SESSION_URL, params=q, headers=base, cookies=cookies,
            ) as back:
                if back.status_code != 200:
                    raise APIError(f"processSession backchannel: HTTP {back.status_code}")
                if not sent:
                    await post_messages(messages, 0)
                    sent = True
                buf = ""
                got_data = False
                chunks = back.aiter_text()
                while True:
                    remaining = deadline - time.monotonic()
                    if final_at is not None:
                        remaining = min(remaining, final_at + _TAIL_TIMEOUT - time.monotonic())
                    if remaining <= 0:
                        done = True
                        break
                    try:
                        chunk = await asyncio.wait_for(chunks.__anext__(), timeout=remaining)
                    except StopAsyncIteration:
                        break  # server closed the backchannel; reopen it
                    except asyncio.TimeoutError:
                        done = final_at is not None
                        break
                    transcript.append(chunk)
                    got_data = got_data or bool(chunk)
                    buf += chunk
                    parsed, buf = split_frames(buf)
                    for aid, payload in parsed:
                        state["aid"] = max(state["aid"], aid)
                        error = status_error(payload)
                        if error:
                            server_error = error
                            done = True
                        if payload == ["close"]:
                            closed = True
                            done = True
                        body = payload_body(payload)
                        if body is not None and _has_completion(body):
                            completion_seen = True
                        if final_at is None and is_final_candidate(payload):
                            final_at = time.monotonic()
                        if is_end_of_stream(payload):
                            done = True
                    # Title and completion token follow the final candidate;
                    # then half-close so the server ends the stream.
                    if final_at is not None and completion_seen and not half_closed and not done:
                        await post_messages([HALF_CLOSE_MESSAGE], len(messages))
                        half_closed = True
                    if done:
                        break
            if not done:
                # Backchannel closed by the server: reopen it (WebChannel does
                # the same), backing off if it keeps closing without data.
                empty_reopens = 0 if got_data else empty_reopens + 1
                if empty_reopens > 5:
                    break
                if not got_data:
                    await asyncio.sleep(0.5 * empty_reopens)
    finally:
        try:
            await client.post(
                PROCESS_SESSION_URL,
                params={"VER": "8", "gsessionid": gsid, "SID": sid,
                        "RID": str(state["rid"] + 1), "TYPE": "terminate", "zx": _zx()},
                headers=base, cookies=cookies,
            )
        except Exception as e:  # best effort; the server times the channel out anyway
            logger.debug(f"processSession terminate failed: {e}")

    text = "".join(transcript)
    if server_error:
        logger.debug(f"processSession transcript: {text[:2000]}")
        raise APIError(f"Gemini rejected the request (processSession): {server_error}")
    if final_at is None:
        logger.debug(f"processSession transcript: {text[:2000]}")
        if closed:
            raise APIError("Gemini closed the processSession channel without an answer.")
        raise GeminiTimeoutError(f"No answer from Gemini (processSession) within {timeout:.0f}s.")
    return text


def status_error(payload: Any) -> str | None:
    """Message of a ``{"__sm__": {"status": [code, message, details]}}`` error frame."""
    if not isinstance(payload, dict) or "__sm__" not in payload:
        return None
    status = payload["__sm__"].get("status") if isinstance(payload["__sm__"], dict) else None
    # [[[code, message, details]]] in the captures; unwrap whatever nesting arrives.
    while isinstance(status, list) and status and isinstance(status[0], list):
        status = status[0]
    if not isinstance(status, list) or not status:
        return f"unrecognised status {json.dumps(payload)[:200]}"
    code = status[0]
    if code in (0, None):
        return None
    message = status[1] if len(status) > 1 else ""
    return f"status {code}: {message}"


def _has_completion(body: list) -> bool:
    return len(body) > 25 and body[25] is not None
