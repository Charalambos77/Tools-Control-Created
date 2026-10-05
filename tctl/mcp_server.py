"""Tools Control as an MCP server, so Claude can look up chats and choose tools itself.

Connect it from the app (MCP servers › Connect Tools Control to Claude Code), or by hand:
    claude mcp add tools-control -s user -- <path>/.venv/Scripts/python.exe -m tctl.mcp_server
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tctl import launch, mcp, sessions, skills, store, suggest  # noqa: E402
from tctl.mini_mcp import Server  # noqa: E402

app = Server("tools-control", "1.0.0", instructions=(
    "Manage which Claude Code skills and MCP servers are switched on per conversation. Changes apply the next "
    "time the chat is opened from Tools Control (or with the launch command); they never change a running chat."))


def _brief(s: dict) -> dict:
    return {k: s.get(k) for k in ("id", "title", "cwd", "updated", "prompts", "about")}


@app.tool("list_conversations", "List Claude Code conversations on this PC, newest first. Optional search words.",
          {"type": "object", "properties": {"query": {"type": "string"}, "limit": {"type": "integer"}}})
def list_conversations(query: str = "", limit: int = 20):
    return [_brief(s) for s in sessions.list_sessions(query)[: max(1, min(limit, 100))]]


@app.tool("conversation_details", "What a conversation is about, the tools it used and the tools chosen for it.",
          {"session_id": "string"})
def conversation_details(session_id: str):
    info = sessions.get(session_id)
    if not info:
        raise ValueError("No conversation with that id")
    prof = store.get_profile(session_id)
    return {"title": info["title"], "cwd": info["cwd"], "about": prof["about"], "about_by_claude": prof["about_auto"],
            "first_prompt": info["first_prompt"][:600], "tools_used": info["tools"],
            "skills_on": prof["skills"], "mcp_on": prof["mcp"],
            "note": "skills_on / mcp_on = null means not chosen yet (everything as usual)"}


@app.tool("set_conversation_about", "Write what a conversation is about (shown in Tools Control).",
          {"session_id": "string", "about": "string"})
def set_conversation_about(session_id: str, about: str):
    store.save_profile(session_id, about=about)
    return "Saved."


@app.tool("suggest_tools", "Suggest skills and MCP servers for a conversation (fast local match).",
          {"session_id": "string"})
def suggest_tools(session_id: str):
    return suggest.local(session_id)


@app.tool("list_skills", "All skills Claude Code can use on this PC (with ids for set_conversation_tools).",
          {"type": "object", "properties": {"cwd": {"type": "string"}}})
def list_skills(cwd: str = ""):
    return [{"id": s["id"], "name": s["invoke"], "source": s["source"], "description": s["description"][:200]}
            for s in skills.all_skills(cwd)]


@app.tool("list_mcp_servers", "All MCP servers configured on this PC (with ids for set_conversation_tools).",
          {"type": "object", "properties": {"cwd": {"type": "string"}}})
def list_mcp_servers(cwd: str = ""):
    return [{"id": s["id"], "name": s["name"], "scope": s["scope"], "type": s["type"]} for s in mcp.all_servers(cwd)]


@app.tool("set_conversation_tools",
          "Choose exactly which skills and/or MCP servers are on for a conversation (lists of ids). Omit a list to "
          "leave it unchanged; pass null via reset=true to go back to Claude Code's normal set.",
          {"type": "object", "properties": {
              "session_id": {"type": "string"},
              "skills": {"type": "array", "items": {"type": "string"}},
              "mcp": {"type": "array", "items": {"type": "string"}},
              "reset": {"type": "boolean"}}, "required": ["session_id"]})
def set_conversation_tools(session_id: str, skills: list | None = None, mcp: list | None = None, reset: bool = False):
    if reset:
        store.save_profile(session_id, skills=None, mcp=None)
        return "Back to the normal set of tools."
    fields = {}
    if skills is not None:
        fields["skills"] = list(skills)
    if mcp is not None:
        fields["mcp"] = list(mcp)
    store.save_profile(session_id, **fields)
    return "Saved. It applies the next time the chat is opened from Tools Control."


@app.tool("launch_command", "The command that opens a conversation with its chosen tools.", {"session_id": "string"})
def launch_command(session_id: str):
    c = launch.command(session_id)
    return {"powershell": c["powershell"], "shell": c["shell"], "notes": c["notes"]}


if __name__ == "__main__":
    os.chdir(Path(__file__).resolve().parent.parent)
    app.run()
