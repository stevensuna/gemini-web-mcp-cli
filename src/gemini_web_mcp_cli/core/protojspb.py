"""Convert binary protobuf messages to JSPB arrays (the JSON+protobuf format).

Some accounts' Gemini pages encode processSession messages as binary protobuf
(``X-WebChannel-Content-Type: application/x-protobuf``, seen 2026-09-29) instead
of JSON arrays. The server still accepts JSON on those accounts, so the replay
converts Chrome's binary setup message to JSPB and keeps the channel in JSON
mode; responses then use the existing JSON parser.

JSPB puts protobuf field N at array index N-1. Without the schema a
length-delimited value is ambiguous (the byte 0x3d is both "=" and the int 61),
so ``shape`` — a type skeleton from JSON captures (core/setup_shape.py) — says
whether a field is a string (``""``) or a message/list. Where the skeleton has
no entry, the value is read as printable text, else a nested message, else
packed varints. Empty values are ``""`` for string fields, else ``[]`` (empty
strings are normally omitted on the wire). A wrong guess is rejected loudly by
the server ("Invalid value at '<field>'"), never silently accepted.
"""

from __future__ import annotations

from typing import Any

MAX_FIELD = 1000


def _read_varint(b: bytes, i: int) -> tuple[int, int]:
    result = shift = 0
    while True:
        c = b[i]
        i += 1
        result |= (c & 0x7F) << shift
        shift += 7
        if c < 0x80:
            return result, i


def parse_fields(b: bytes) -> list[tuple[int, int, bytes]]:
    """Top-level fields as (field number, wire type, value bytes).

    For wire type 2 the value is the payload without its length prefix.
    Raises ValueError on malformed input.
    """
    fields = []
    i = 0
    try:
        while i < len(b):
            key, i = _read_varint(b, i)
            field, wire = key >> 3, key & 7
            if wire == 0:
                start = i
                _, i = _read_varint(b, i)
                value = b[start:i]
            elif wire == 2:
                n, i = _read_varint(b, i)
                value = b[i:i + n]
                if len(value) != n:
                    raise ValueError("truncated field")
                i += n
            elif wire == 1:
                value = b[i:i + 8]
                i += 8
            elif wire == 5:
                value = b[i:i + 4]
                i += 4
            else:
                raise ValueError(f"unsupported wire type {wire}")
            if not 1 <= field <= MAX_FIELD or i > len(b):
                raise ValueError(f"bad field {field}")
            fields.append((field, wire, value))
    except IndexError as e:
        raise ValueError("truncated message") from e
    return fields


def _is_text(b: bytes) -> bool:
    try:
        s = b.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return all(ord(c) >= 0x20 and ord(c) != 0x7F for c in s)


def _packed(b: bytes) -> list[int] | None:
    out, i = [], 0
    try:
        while i < len(b):
            v, i = _read_varint(b, i)
            out.append(v)
    except IndexError:
        return None
    return out


def to_jspb(b: bytes, shape: Any = None) -> list:
    """Decode a binary protobuf message into a JSPB array, typed by ``shape``."""
    fields = parse_fields(b)
    out: list[Any] = [None] * max((f for f, _, _ in fields), default=0)
    counts: dict[int, int] = {}
    for f, _, _ in fields:
        counts[f] = counts.get(f, 0) + 1
    for f, wire, raw in fields:
        child = shape[f - 1] if isinstance(shape, list) and f - 1 < len(shape) else None
        value = _value(wire, raw, child)
        if counts[f] > 1:
            out[f - 1] = (out[f - 1] or []) + [value]
        else:
            out[f - 1] = value
    return out


def _value(wire: int, raw: bytes, shape: Any) -> Any:
    if wire == 0:
        return _read_varint(raw, 0)[0]
    if wire in (1, 5):
        return int.from_bytes(raw, "little")
    if isinstance(shape, str):
        return raw.decode("utf-8", "replace")
    if not raw:
        return []
    if shape is None and _is_text(raw):
        return raw.decode("utf-8")
    try:
        return to_jspb(raw, shape if isinstance(shape, list) else None)
    except ValueError:
        pass
    packed = _packed(raw)
    if packed is not None:
        return packed
    return raw.decode("utf-8", "replace")
