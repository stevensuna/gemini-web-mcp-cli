"""Response parser for Google's batchexecute and StreamGenerate protocols.

Handles:
- JSONP prefix stripping (`)]}' `)
- Length-prefixed frame parsing (UTF-16 code units)
- Nested JSON extraction from batchexecute responses
- Safe navigation of deeply nested response structures
"""

from __future__ import annotations

import re
from typing import Any

import orjson
from loguru import logger

# Regex for matching the length marker at the start of a frame
_LENGTH_MARKER_RE = re.compile(r"(\d+)\n")

JSONP_PREFIX = ")]}\'\n"


def strip_jsonp_prefix(text: str) -> str:
    """Remove the JSONP protection prefix `)]}'` from the response."""
    if text.startswith(")]}'"):
        return text[4:].lstrip("\n")
    return text


def _utf16_char_count(s: str, start: int, utf16_units: int) -> tuple[int, int]:
    """Count Python characters needed to consume `utf16_units` UTF-16 code units.

    Google uses JavaScript's String.length for frame lengths, which counts
    in UTF-16 code units. BMP chars (U+0000-U+FFFF) = 1 unit, supplementary
    chars (U+10000+) = 2 units (surrogate pair).

    Returns (python_char_count, actual_utf16_units_consumed).
    """
    count = 0
    units = 0
    length = len(s)

    while units < utf16_units and (start + count) < length:
        cp = ord(s[start + count])
        u = 2 if cp > 0xFFFF else 1
        if units + u > utf16_units:
            break
        units += u
        count += 1

    return count, units


def parse_frames(content: str) -> tuple[list[Any], str]:
    """Parse length-prefixed frames from a streaming response buffer.

    Frame format: `[length]\\n[json_payload]\\n`
    Length is in UTF-16 code units (JavaScript String.length).

    Returns (parsed_frames, remaining_buffer).
    """
    pos = 0
    total = len(content)
    frames: list[Any] = []

    while pos < total:
        # Skip whitespace between frames
        while pos < total and content[pos].isspace():
            pos += 1

        if pos >= total:
            break

        # Match length marker
        match = _LENGTH_MARKER_RE.match(content, pos=pos)
        if not match:
            break

        length_str = match.group(1)
        frame_length = int(length_str)

        # Content starts after the digits (not after the newline -- the newline
        # is counted in the length)
        content_start = match.start() + len(length_str)

        # Convert UTF-16 length to Python character count
        char_count, units_found = _utf16_char_count(content, content_start, frame_length)

        if units_found < frame_length:
            # Incomplete frame -- keep in buffer
            break

        end_pos = content_start + char_count
        chunk = content[content_start:end_pos].strip()
        pos = end_pos

        if not chunk:
            continue

        try:
            parsed = orjson.loads(chunk)
            if isinstance(parsed, list):
                frames.extend(parsed)
            else:
                frames.append(parsed)
        except (orjson.JSONDecodeError, ValueError):
            logger.debug(f"Failed to parse frame JSON: {chunk[:100]}...")

    return frames, content[pos:]


def extract_json_from_response(text: str) -> list[Any]:
    """Extract and normalize JSON content from a Google API response.

    Handles:
    1. JSONP prefix removal
    2. Length-prefixed frame parsing
    3. Fallback to plain JSON parsing
    4. Fallback to NDJSON (line-by-line)
    """
    content = strip_jsonp_prefix(text)
    content = content.lstrip()

    # Try frame-based parsing first
    frames, _ = parse_frames(content)
    if frames:
        return frames

    # Try parsing as plain JSON
    try:
        parsed = orjson.loads(content.strip())
        return parsed if isinstance(parsed, list) else [parsed]
    except (orjson.JSONDecodeError, ValueError):
        pass

    # Try NDJSON (line-by-line)
    collected = []
    for line in content.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            parsed = orjson.loads(line)
            if isinstance(parsed, list):
                collected.extend(parsed)
            elif isinstance(parsed, dict):
                collected.append(parsed)
        except (orjson.JSONDecodeError, ValueError):
            continue

    if collected:
        return collected

    raise ValueError("Could not parse any valid JSON from the response.")


def get_nested(data: Any, path: list[int | str], default: Any = None) -> Any:
    """Safely navigate a nested structure using a sequence of keys/indices.

    Example:
        get_nested(data, [4, 0, 1, 0]) safely accesses data[4][0][1][0]

    Handles Google's sparse protobuf-to-JSON format where arrays with many null
    elements are compressed into ``[{string_key: value, ...}]``. In this format,
    keys are 1-based protobuf field numbers (list_index + 1 = dict_key).
    Example: ``candidate[12]`` may be ``[{"7": [0], "87": music_data}]`` instead
    of an 87-element list.

    Returns default if any step in the path fails.
    """
    current = data
    for key in path:
        try:
            if isinstance(key, int):
                if isinstance(current, list) and -len(current) <= key < len(current):
                    current = current[key]
                elif isinstance(current, list) and len(current) == 1 and isinstance(
                    current[0], dict
                ):
                    # Sparse dict wrapped in a single-element list: [{"field": val}]
                    # Keys are 1-based protobuf field numbers.
                    sparse = current[0]
                    proto_key = str(key + 1)
                    if proto_key in sparse:
                        current = sparse[proto_key]
                    else:
                        return default
                elif isinstance(current, dict):
                    # Direct sparse dict (not wrapped in a list)
                    proto_key = str(key + 1)
                    if proto_key in current:
                        current = current[proto_key]
                    else:
                        return default
                else:
                    return default
            elif isinstance(key, str):
                if isinstance(current, dict) and key in current:
                    current = current[key]
                else:
                    return default
            else:
                return default
        except (TypeError, IndexError, KeyError):
            return default

    return current if current is not None else default


def parse_batchexecute_response(text: str) -> list[dict[str, Any]]:
    """Parse a batchexecute response into a list of RPC results.

    Each result is a dict with:
    - rpc_id: str -- the RPC ID (e.g., "MaZiqc")
    - data: Any -- the parsed inner JSON payload
    - raw: str -- the raw JSON string
    """
    frames = extract_json_from_response(text)
    results = []

    for frame in frames:
        if not isinstance(frame, list):
            continue

        # batchexecute frames look like: ["wrb.fr", "rpc_id", "json_string", ...]
        if len(frame) >= 3 and frame[0] == "wrb.fr":
            rpc_id = frame[1]
            raw_json = frame[2]

            data = None
            if raw_json and isinstance(raw_json, str):
                try:
                    data = orjson.loads(raw_json)
                except (orjson.JSONDecodeError, ValueError):
                    data = raw_json

            results.append({
                "rpc_id": rpc_id,
                "data": data,
                "raw": raw_json,
            })

    return results


# Known model hashes for server-side verification
_KNOWN_MODEL_HASHES = {
    # Current (Jul 2026, from UI model picker)
    "1d44b34bcaa1c04d",  # 3.5 Flash-Lite
    "56fdd199312815e2",  # 3.6 Flash
    "e6fa609c3fa255c0",  # 3.6 Thinking
    "9d8ca3786ebdfbea",  # 3.1 Pro (Omni)
    # Legacy hashes (server may return these)
    "8c46e95b1a07cecc",  # 3.1 Flash-Lite (older)
    "95a4c0abcba24364",  # 4 Argon
    "fbb127bbb056c959",  # 3.5 Flash (older)
    "5bf011840784117a",  # 3.5 Thinking (older)
    "e051ce1aa80aa576",  # Thinking (older)
}


_KNOWN_MODEL_LABELS = {
    "Fast",
    "Thinking",
    "Pro",
    "Flash",
    "Flash-Lite",
    "Flash Lite",
    "3.5 Flash-Lite",
    "3.6 Flash",
    "3.6 Thinking",
    "3.1 Pro",
    "Extended thinking",
    "Argon",
    "4 Argon",
    "3.8 Flash",
}

# Versioned labels ("3.8 Flash", "3.1 Pro", "3.5 Flash-Lite", ...) change with
# every model release, so match the shape instead of listing each one.
_VERSIONED_LABEL_RE = re.compile(
    r"^\d+(?:\.\d+)*\s+(?:Flash[- ]Lite|Flash|Pro|Thinking|Argon)$"
)


def _is_model_label(value: object) -> bool:
    return isinstance(value, str) and (
        value in _KNOWN_MODEL_LABELS or bool(_VERSIONED_LABEL_RE.match(value))
    )


def _extract_server_model(data: Any, _depth: int = 0) -> tuple[str | None, str | None]:
    """Extract the server-confirmed model hash and label from a StreamGenerate response.

    The model hash (16-char hex) and label ("Fast", "Thinking", "Pro") appear
    in the context section of the response inner JSON. We do a deep recursive
    scan to find a known hash followed by its label.

    Returns (model_hash, model_label) or (None, None) if not found.
    """
    if _depth > 10 or not isinstance(data, list):
        return None, None

    # Scan this list for a known model hash
    for i, item in enumerate(data):
        if isinstance(item, str) and len(item) == 16 and item in _KNOWN_MODEL_HASHES:
            # Found a known hash. Look ahead for the label.
            label = None
            for offset in range(1, 6):
                if i + offset < len(data):
                    val = data[i + offset]
                    if _is_model_label(val):
                        label = val
                        break
            return item, label

    # Recurse into nested lists
    for item in data:
        if isinstance(item, list):
            found_hash, found_label = _extract_server_model(item, _depth + 1)
            if found_hash:
                return found_hash, found_label

    return None, None


def parse_stream_body(inner: list) -> dict[str, Any]:
    """Parse one StreamGenerate-shaped body (the decoded ``wrb.fr`` inner JSON).

    The processSession transport carries the same body shape, so both use this.
    """
    result: dict[str, Any] = {
        "metadata": get_nested(inner, [1]),
        "candidates": [],
        "text": None,
        "thoughts": None,
        "completion": get_nested(inner, [25]),
        "server_model_hash": None,
        "server_model_label": None,
    }

    # Extract candidates
    candidates_data = get_nested(inner, [4])
    if isinstance(candidates_data, list):
        for candidate in candidates_data:
            if not isinstance(candidate, list):
                continue
            c = {
                "rcid": get_nested(candidate, [0]),
                "text": get_nested(candidate, [1, 0]),
                "thoughts": get_nested(candidate, [37, 0, 0]),
                "web_images": get_nested(candidate, [12, 1]),
                "generated_images": get_nested(candidate, [12, 7, 0]),
                "generated_music": get_nested(candidate, [12, 86]),
                "generated_video": get_nested(candidate, [12, 59]),
            }
            result["candidates"].append(c)

        # Set top-level text/thoughts from first candidate
        if result["candidates"]:
            result["text"] = result["candidates"][0]["text"]
            result["thoughts"] = result["candidates"][0]["thoughts"]

    # Extract server-confirmed model hash and label
    model_hash, model_label = _extract_server_model(inner)
    if model_hash:
        result["server_model_hash"] = model_hash
        result["server_model_label"] = model_label

    return result


def parse_stream_response(text: str) -> list[dict[str, Any]]:
    """Parse a StreamGenerate streaming response into structured data.

    Returns a list of parsed frames, each containing:
    - metadata: conversation context (cid, rid, rcid, ...)
    - candidates: list of candidate responses
    - text: the latest text content (from first candidate)
    - thoughts: thinking process text (if present)
    - completion: whether generation is complete
    - server_model_hash: model hash confirmed by the server (if present)
    - server_model_label: model label confirmed by the server (if present)
    """
    frames = extract_json_from_response(text)
    results = []

    for frame in frames:
        if not isinstance(frame, list):
            continue

        # StreamGenerate frames look like: ["wrb.fr", null, "inner_json_string", ...]
        if len(frame) < 3 or frame[0] != "wrb.fr":
            continue

        raw_inner = frame[2]
        if not raw_inner or not isinstance(raw_inner, str):
            continue

        try:
            inner = orjson.loads(raw_inner)
        except (orjson.JSONDecodeError, ValueError):
            continue

        if not isinstance(inner, list):
            continue

        results.append(parse_stream_body(inner))

    return results
