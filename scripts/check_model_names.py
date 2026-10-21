#!/usr/bin/env python3
"""Inspect and verify live Gemini model hashes from WIZ_global_data.

This utility dynamically connects to the active Chrome daemon, extracts
window.WIZ_global_data in real-time via CDP, recursively decodes Google's
nested string-serialized arrays, and prints detected model hashes with
their UI labels.

Usage:
    python scripts/check_model_names.py
"""

import json
from typing import Any

# Import core CDP and daemon helpers from our package
try:
    from gemini_web_mcp_cli.core.cdp import find_or_create_gemini_page, run_js
    from gemini_web_mcp_cli.core.chrome_manager import load_daemon_info
except ImportError:
    print("Error: Could not import package modules. Please run inside the virtual environment:")
    print("       source .venv/bin/activate && python scripts/check_model_names.py")
    exit(1)

# Current known model hashes for validation
# Note: model is selected by the full header tail, not the hash alone.
# Thinking level is the tail's second number (Low=1, Medium=4, High=2).
KNOWN_HASHES = {
    "8c46e95b1a07cecc": "Gemini 3.5 Flash-Lite",
    "56fdd199312815e2": "Gemini 3.8 Flash (also older 3.7/3.6 labels)",
    "95a4c0abcba24364": "Gemini 4 Argon",
    "e6fa609c3fa255c0": "Gemini 3.1 Pro",
    "fbb127bbb056c959": "Legacy Gemini Flash (direct)",
    "5bf011840784117a": "Legacy Gemini Thinking",
    "e051ce1aa80aa576": "Legacy Gemini Thinking (alternative)",
    "9d8ca3786ebdfbea": "Gemini 3.1 Pro (Omni)",
    "1d44b34bcaa1c04d": "Legacy Gemini Flash-Lite variant",
    "797f3d0293f288ad": "Legacy Gemini Thinking variant",
    "cf41b0e0dd7d53e5": "Legacy Gemini Flash-Lite variant",
}


def expand_object(obj: Any) -> Any:
    """Recursively parse nested, string-escaped WIZ array JSON."""
    if isinstance(obj, str):
        if obj.startswith("%.@."):
            clean = obj.replace("%.@", "")
            try:
                parsed = json.loads(clean)
                return expand_object(parsed)
            except Exception:
                pass
        try:
            if obj.strip().startswith("[") or obj.strip().startswith("{"):
                parsed = json.loads(obj)
                return expand_object(parsed)
        except Exception:
            pass
        return obj
    elif isinstance(obj, dict):
        return {k: expand_object(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [expand_object(x) for x in obj]
    return obj


def scan_for_models(obj: Any, path: str = "") -> None:
    """Scan expanded WIZ structure for known and new model hashes."""
    obj_str = str(obj)
    found_hashes = [h for h in KNOWN_HASHES if h in obj_str]
    if not found_hashes:
        return

    if isinstance(obj, dict):
        for k, v in obj.items():
            scan_for_models(v, f"{path}/{k}")
    elif isinstance(obj, list):
        element_strings = [str(x) for x in obj]
        keywords = [
            "Flash", "Pro", "Lite", "Thinking", "Argon",
            "Fastest", "All-around", "Advanced", "Complex",
        ]
        has_label = any(
            any(label in x for label in keywords) for x in element_strings if isinstance(x, str)
        )
        if has_label and len(found_hashes) > 0:
            print(f"\n✨ Association found at path {path}:")
            print(f"  Hashes located: {found_hashes}")
            for idx, x in enumerate(obj):
                print(f"    [{idx}]: {str(x)[:200]}...")
        else:
            for idx, x in enumerate(obj):
                scan_for_models(x, f"{path}[{idx}]")


def main() -> None:
    # 1. Detect active Chrome daemon port
    info = load_daemon_info()
    if info:
        port = info.port
        print(f"Connected to Chrome daemon '{info.profile_name}' on port {port} (PID: {info.pid})")
    else:
        port = 9223
        print(f"No active daemon file found. Attempting connection on default port {port}...")

    # 2. Locate active Gemini page
    try:
        page = find_or_create_gemini_page(port)
    except Exception as e:
        print(f"Error: Could not connect to browser on port {port}: {e}")
        print("       Ensure Chrome daemon is running via: gemcli chrome start")
        exit(1)

    if not page:
        print(f"Error: Gemini page not found in browser on port {port}.")
        exit(1)

    ws_url = page.get("webSocketDebuggerUrl")
    if not ws_url:
        print("Error: Could not retrieve WebSocket debugger URL from Gemini page.")
        exit(1)

    # 3. Pull WIZ_global_data from page
    print("Extracting window.WIZ_global_data from active browser tab...")
    try:
        wiz_data = run_js(ws_url, "window.WIZ_global_data")
    except Exception as e:
        print(f"Error: JavaScript execution failed: {e}")
        exit(1)

    if not wiz_data:
        print("Error: WIZ_global_data object is empty or could not be retrieved.")
        exit(1)

    # 4. Process and unescape the nested WIZ structure
    print("Expanding nested JSON arrays inside WIZ structure...")
    expanded = expand_object(wiz_data)

    # 5. Search and verify
    print("\n🔍 Scanning structures for active model hashes...")
    scan_for_models(expanded)
    print("\n✅ Model scan complete.")


if __name__ == "__main__":
    main()
