"""Hack CLI command for seamless integration with other AI tools.

Provides the `gemcli hack claude` command to launch Claude Code
connected to the local Gemini API server.
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request


def _get_free_port() -> int:
    """Find an available ephemeral port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


def _check_server_ready(url: str, timeout: int = 15) -> bool:
    """Poll the server until it responds or timeout is reached."""
    start = time.time()
    while time.time() - start < timeout:
        try:
            with urllib.request.urlopen(url, timeout=1) as response:
                if response.status == 200:
                    return True
        except Exception:
            pass
        time.sleep(0.5)
    return False


def cmd_hack_claude(args: list[str], model: str | None = None) -> int:
    """Launch Claude Code connected to the local Gemini API server."""
    # 1. Verify claude is installed
    claude_path = shutil.which("claude")
    if not claude_path:
        print(
            "Error: 'claude' command not found.\n\n"
            "Please install Claude Code first:\n"
            "npm install -g @anthropic-ai/claude-code\n"
            "or run it via: npx @anthropic-ai/claude-code",
            file=sys.stderr,
        )
        return 1

    # 1.5 Verify API dependencies
    try:
        import fastapi  # noqa: F401
        import uvicorn  # noqa: F401
    except ImportError:
        print(
            "Error: Missing required dependencies (fastapi, uvicorn).\n"
            "Please ensure gemini-web-mcp-cli is installed correctly with all dependencies.",
            file=sys.stderr,
        )
        return 1

    # 2. Launch API Server
    port = _get_free_port()
    print(f"Starting local Gemini API server on port {port}...", file=sys.stderr)

    server_env = os.environ.copy()
    server_env["PORT"] = str(port)

    server_process = subprocess.Popen(
        [sys.executable, "-m", "gemini_web_mcp_cli.api.server"],
        env=server_env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    try:
        # 3. Wait for API Server to be ready
        if not _check_server_ready(f"http://127.0.0.1:{port}/health"):
            print(
                "Error: Failed to start API server or timed out.",
                file=sys.stderr,
            )
            return 1

        print("API server ready! Launching Claude Code...\n", file=sys.stderr)

        # 4. Prepare environment variables
        env = os.environ.copy()

        for key in list(env.keys()):
            if key.startswith("ANTHROPIC_") or key.startswith("CLAUDE_"):
                del env[key]

        env["ANTHROPIC_BASE_URL"] = f"http://127.0.0.1:{port}"
        env["ANTHROPIC_API_KEY"] = "gemini"

        # 5. Check/Append model argument
        model_map = {
            "flash": "gemini-3.8-flash",
            "gemini-3.8-flash": "gemini-3.8-flash",
            "gemini-3.7-flash": "gemini-3.7-flash",
            "gemini-3.7-flash-extended": "gemini-3.7-flash-extended",
            "gemini-4-argon": "gemini-4-argon",
            "pro": "gemini-pro",
            "thinking": "gemini-thinking",
        }
        claude_args = args[:]
        if "-m" not in claude_args and "--model" not in claude_args:
            gemini_model = model_map.get(model, "gemini-auto") if model else "gemini-auto"
            claude_args.extend(["--model", gemini_model])

        # 6. Execute Claude Code interactively
        cmd = [claude_path] + claude_args
        result = subprocess.run(cmd, env=env)

        return result.returncode

    finally:
        # 7. Clean up the API server
        if server_process.poll() is None:
            print("\nShutting down local API server...", file=sys.stderr)
            server_process.terminate()
            try:
                server_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                server_process.kill()
