import asyncio
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main():
    action = sys.argv[1]
    args = {"action": action}
    tag = sys.argv[2] if len(sys.argv) > 2 else action
    if action == "start":
        args["query"] = (
            "In what year was the Metre Convention signed? Produce a brief factual report."
        )
        if tag == "flash":
            args["model"] = "flash"
    if action == "download":
        args["output_path"] = "/tmp/round3-dr-download.txt"
    if action == "invalid":
        args = {"action": "start"}
    record = {
        "time": datetime.now().astimezone().isoformat(),
        "client_pid": os.getpid(),
        "arguments": args,
    }
    print(json.dumps(record), flush=True)
    env = dict(os.environ, GEMCLI_PROFILE="default", GEMCLI_CHROME_IDLE_TIMEOUT="0")
    async with stdio_client(
        StdioServerParameters(command=os.path.expanduser("~/.local/bin/gemini-web-mcp"), env=env)
    ) as (r, w):
        async with ClientSession(r, w) as session:
            await session.initialize()
            result = await session.call_tool(
                "research", args, read_timeout_seconds=timedelta(seconds=240)
            )
            record["result"] = result.model_dump(mode="json")
            await session.send_ping()
            record["server_alive_after_result"] = bool((await session.list_tools()).tools)
            record["finished"] = datetime.now().astimezone().isoformat()
            Path(f"docs/research/mcp-start/{tag}.json").write_text(
                json.dumps(record, indent=2) + "\n"
            )
            print(json.dumps(record), flush=True)


asyncio.run(main())
