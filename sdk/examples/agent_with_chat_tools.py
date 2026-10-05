"""Continue a Claude Code chat from a script, with exactly the tools chosen for it in Tools Control.

    pip install claude-agent-sdk
    python agent_with_chat_tools.py <chat-id-start> "What's left to do?"
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from claude_agent_sdk import AssistantMessage, ClaudeAgentOptions, TextBlock, query  # noqa: E402
from tools_control import ToolsControl  # noqa: E402


async def main(short_id: str, prompt: str):
    tc = ToolsControl()
    chat_id = next(c["id"] for c in tc.chats() if c["id"].startswith(short_id))
    options = ClaudeAgentOptions(**tc.agent_options(chat_id), permission_mode="default")
    async for msg in query(prompt=prompt, options=options):
        if isinstance(msg, AssistantMessage):
            for block in msg.content:
                if isinstance(block, TextBlock):
                    print(block.text)


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1], " ".join(sys.argv[2:]) or "Summarise where we are."))
