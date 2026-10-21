"""Shared JSON file read/write helpers.

Centralises the read-parse-fallback and write-format-mkdir patterns used
across profiles, cdp, chrome_manager, and setup modules.
"""

from __future__ import annotations

import json
from pathlib import Path


def read_json_dict(path: Path) -> dict:
    """Read *path* as a JSON object, returning ``{}`` if missing, corrupt, or non-dict."""
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def write_json_file(
    path: Path,
    data: dict | list,
    *,
    compact: bool = False,
    trailing_newline: bool = False,
    mkdir: bool = True,
) -> None:
    """Write *data* as JSON to *path*.

    Args:
        path: Target file.
        data: Serialisable dict or list.
        compact: Use single-line format with no indentation (for machine-only
            files like port maps where readability doesn't matter).
        trailing_newline: Append ``\\n`` after the JSON (useful for config files
            consumed by tools that expect POSIX line endings).
        mkdir: Create parent directories if they don't exist.
    """
    text = json.dumps(data, separators=(",", ":")) if compact else json.dumps(data, indent=2)
    if trailing_newline:
        text += "\n"
    if mkdir:
        path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
