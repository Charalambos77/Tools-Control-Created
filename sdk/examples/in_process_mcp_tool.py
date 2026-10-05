"""An agent with its own in-process MCP tool (Claude Agent SDK) that reads your Tools Control chats.

    pip install claude-agent-sdk
    python in_process_mcp_tool.py "Which of my chats are about Instagram?"
"""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from claude_agent_sdk import ClaudeAgentOptions, create_sdk_mcp_server, query, tool  # noqa: E402
from tools_control import ToolsControl  # noqa: E402

tc = ToolsControl()


@tool("find_chats", "Find Claude Code chats on this PC by search words", {"query": str})
async def find_chats(args):
    rows = [{"id": c["id"][:8], "title": c["title"], "about": c["about"]} for c in tc.chats(args["query"])[:15]]
    return {"content": [{"type": "text", "text": json.dumps(rows, indent=2)}]}


server = create_sdk_mcp_server(name="chats", version="1.0.0", tools=[find_chats])


async def main(prompt: str):
    options = ClaudeAgentOptions(mcp_servers={"chats": server}, allowed_tools=["mcp__chats__find_chats"],
                                 tools=[], strict_mcp_config=True)
    async for msg in query(prompt=prompt, options=options):
        if type(msg).__name__ == "ResultMessage":
            print(msg.result)


if __name__ == "__main__":
    asyncio.run(main(" ".join(sys.argv[1:]) or "List my most recent chats."))
