# Tools Control

Choose which **skills** and **MCP servers** Claude Code uses for each conversation.

- Pick a chat and see what it's about, or write that yourself.
- Get suggestions for the tools that fit it, and switch on only those.
- Open the chat with exactly that set.

You can also connect MCP servers, test them, and create new MCP servers and skills. Claude can write the code for them. Tools Control can also be driven by Claude itself (through its own MCP server), by your own scripts (a Python SDK, which also works with the Claude Agent SDK), or from the command line.

Get it: `git clone https://github.com/Charalambos77/Tools-Control-Created.git` (a standalone app; its sister app is [Graphics-Control](https://github.com/Charalambos77/Graphics-Control)).

## Start

```powershell
cd Tools-Control-Created
.\start.ps1            # opens http://127.0.0.1:8450
.\start.ps1 -Demo      # pretend chats, skills and MCP servers (your real setup is not touched)
```

You need Python 3.10+ and Claude Code (`claude`) installed. It reads `%USERPROFILE%\.claude` (your chats and skills) and `%USERPROFILE%\.claude.json` (your MCP servers). If yours are somewhere else, change the paths in Settings. It only listens on `127.0.0.1`.

## Pages

| Page | What it's for |
| --- | --- |
| **Chats** | Every Claude Code conversation on the PC, newest first, searchable and filterable by project. |
| **Skills** | Every skill Claude Code can use: yours, the project's, plugin skills, built-in ones (press **Ask Claude which skills it has**) and the library. You can read and edit them, copy them between places, delete them (they go to a trash folder), or create a new one. |
| **MCP servers** | Every MCP server Claude Code knows about: user, this folder, a project's `.mcp.json`, plugins and the library. |
| **Create** | Build a new MCP server. |
| **SDK & connect** | Connect Tools Control to Claude as an MCP server, or use the Python SDK, the Claude Agent SDK or the command line. |
| **Settings** | Where your Claude Code files are, the `claude` program, which terminal **Open** uses, and the model used for summaries. |

On the **Chats** page, opening a chat shows:
- **What it's about**: your own description, plus **Ask Claude**, which reads the chat, summarises it and suggests tools. It also tells you about useful tools you don't have yet.
- **Tools used so far** in that chat.
- **Tools for this chat**, a Skills tab and an MCP servers tab:
  - *Normal*: everything Claude Code has, as usual.
  - *Only what I choose*: you tick what you want. ★ marks suggestions, each with the reason.
- **Inside the chat**: the conversation itself, with the tools used in each answer.
- **Open with these tools**: continues the chat in a new terminal window with exactly that set.
- **New chat with these tools** and **Command…**, which shows the command so you can copy it.
- **Make default for this folder**: makes the skill choice apply to every chat in that folder, including from VS Code or the desktop app.

On the **MCP servers** page you can:
- **Test** a server: connects and lists its tools.
- **Try** a tool: runs it with arguments you give.
- **Add server** with a form, or **Paste JSON** straight from a README.
- **Connect** a library server to Claude Code for every project or for one project.
- **Disconnect** a server.
- Connect **Tools Control itself**.

On the **Create** page:
1. Give the server a name.
2. Add its tools and their parameters.
3. Press **Write the tools with Claude**. Claude Code writes the Python inside the server's folder only.
4. The server is tested automatically.

By default a new server runs on plain Python with no packages. A FastMCP version is also available.

## How choosing tools per chat works

Everything uses Claude Code's own command-line switches. All of them were tested with Claude Code 2.1, including a real run where Claude saw only the 3 chosen skills out of 46.

| What | How |
| --- | --- |
| Skills off for this chat | `--settings <file>` with `"skillOverrides": {"<skill>": "off"}`. Works for your skills, project skills, plugin skills and built-in ones. |
| Skills from the library | `--add-dir <folder>`, whose `.claude/skills` holds copies of the chosen library skills. |
| Only the chosen MCP servers | `--mcp-config <file> --strict-mcp-config` |
| Continue the chat / start a new one | `--resume <id>` (run in the chat's folder) / `--session-id <new id>` |

Each chat's files are kept in `data/chats/<id>/`. Nothing in Claude Code's own settings changes unless you press:
- **Connect** or **Disconnect** (writes `~/.claude.json` or `.mcp.json`);
- **Make default for this folder** (writes `.claude/settings.local.json`).

Each of those keeps a `.tools-control.bak` copy of the file it changed. Chats are only ever read.

Choices apply when a chat is opened from Tools Control (or with its command). A chat that is already running keeps the tools it started with.

## Use it from Claude, scripts and the command line

- **Claude (MCP)**: press *Connect* on the SDK page. Claude then gets these tools:
  - `list_conversations`, `conversation_details`, `set_conversation_about`;
  - `suggest_tools`, `list_skills`, `list_mcp_servers`;
  - `set_conversation_tools`, `launch_command`.

  So you can tell Claude "switch on only the SEO skills for my bakery chat".
- **Python SDK**: `sdk/tools_control.py` is one file with no packages.

  ```python
  from tools_control import ToolsControl
  tc = ToolsControl()
  chat = tc.chats("instagram")[0]
  tc.use_suggested(chat["id"])                 # or ask_claude=True
  tc.open(chat["id"])
  ```
- **Claude Agent SDK** (`pip install claude-agent-sdk`): `ClaudeAgentOptions(**tc.agent_options(chat_id))` runs a chat from a script with exactly its tools. Examples:
  - `sdk/examples/agent_with_chat_tools.py`;
  - `sdk/examples/in_process_mcp_tool.py`, an agent with its own in-process MCP tool.
- **Command line**: `python sdk/toolsctl.py chats bakery`, `suggest <id> --claude`, `use-suggested <id>`, `open <id>`, `set <id> --skills a,b --mcp c`.

## For whoever maintains it

The code is in `tctl/`:

| File | What it does |
| --- | --- |
| `sessions.py` | Reads the transcripts and caches them by file size and date |
| `skills.py` | Finds skills (folder name = the name Claude Code uses) |
| `mcp.py` | Finds MCP servers and holds the library, connect and disconnect |
| `mcp_client.py` | The Test / Try client (stdio, Streamable HTTP, SSE) |
| `mini_mcp.py` | A dependency-free MCP server runtime, used by created servers and by `mcp_server.py` |
| `suggest.py` | Local matching, plus Claude's suggestions through `claude -p --json-schema` |
| `launch.py` | The per-chat files and commands |
| `create.py` | Makes MCP servers and skills |
| `demo.py` | The pretend setup |
| `main.py` | The API |

The UI is `static/`: plain HTML, CSS and JS with no build step.

```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt pytest
.venv/bin/python -m pytest -q          # 22 tests (demo setup, real MCP servers over stdio, SDK + CLI)
```
