"""Tools Control SDK — use Tools Control from your own Python scripts (standard library only).

    from tools_control import ToolsControl
    tc = ToolsControl()                                  # the app must be running (start.ps1)
    chat = tc.chats("instagram")[0]
    tc.set_about(chat["id"], "Captions for the bakery launch")
    tc.use_suggested(chat["id"])                         # switch on the suggested skills + MCP servers
    print(tc.command(chat["id"])["powershell"])          # how to open it with those tools

    # Run the chat headless with its tools through the Claude Agent SDK (pip install claude-agent-sdk):
    from claude_agent_sdk import ClaudeAgentOptions, query
    opts = ClaudeAgentOptions(**tc.agent_options(chat["id"]))
"""
import json
import time
import urllib.error
import urllib.parse
import urllib.request

__all__ = ["ToolsControl", "ToolsControlError"]
__version__ = "1.0.0"


class ToolsControlError(RuntimeError):
    pass


class ToolsControl:
    def __init__(self, url: str = "http://127.0.0.1:8450", timeout: float = 60):
        self.url = url.rstrip("/")
        self.timeout = timeout

    # ---- plumbing -----------------------------------------------------------------------------------

    def _call(self, method: str, path: str, body=None, **params):
        q = {k: v for k, v in params.items() if v not in (None, "")}
        full = self.url + path + (("?" + urllib.parse.urlencode(q)) if q else "")
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(full, data=data, method=method,
                                     headers={"Content-Type": "application/json"} if data else {})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                raw = r.read()
        except urllib.error.HTTPError as e:
            try:
                detail = json.loads(e.read()).get("detail")
            except ValueError:
                detail = e.reason
            raise ToolsControlError(f"{e.code}: {detail}") from None
        except urllib.error.URLError as e:
            raise ToolsControlError(f"Tools Control is not running at {self.url} ({e.reason})") from None
        return json.loads(raw) if raw else None

    def wait(self, job_id: str, timeout: float = 600, every: float = 1.5) -> dict:
        """Wait for a background job (Ask Claude, drafts, implement) and return its result."""
        end = time.time() + timeout
        while time.time() < end:
            j = self._call("GET", f"/api/jobs/{job_id}")
            if j["status"] == "done":
                return j["result"]
            if j["status"] == "failed":
                raise ToolsControlError(j["error"])
            time.sleep(every)
        raise ToolsControlError("Timed out waiting for Claude")

    # ---- chats -----------------------------------------------------------------------------------------

    def chats(self, query: str = "", project: str = "") -> list[dict]:
        return self._call("GET", "/api/chats", q=query, project=project)

    def chat(self, session_id: str) -> dict:
        return self._call("GET", f"/api/chats/{session_id}")

    def messages(self, session_id: str, offset: int = 0, limit: int = 60) -> dict:
        return self._call("GET", f"/api/chats/{session_id}/messages", offset=offset, limit=limit)

    def set_about(self, session_id: str, about: str) -> dict:
        return self._call("POST", f"/api/chats/{session_id}/about", {"about": about})

    def tools(self, session_id: str) -> dict:
        """All skills and MCP servers for the chat's folder, what's on, and the suggestions."""
        return self._call("GET", f"/api/chats/{session_id}/tools")

    def set_tools(self, session_id: str, skills: list[str] | None = ..., mcp: list[str] | None = ...) -> dict:
        """Lists of ids (from tools()). None = Claude Code's normal set. Leave out to keep as is."""
        body = {}
        if skills is not ...:
            body["skills"] = skills
        if mcp is not ...:
            body["mcp"] = mcp
        return self._call("POST", f"/api/chats/{session_id}/tools", body)

    def use_suggested(self, session_id: str, ask_claude: bool = False) -> dict:
        """Switch on exactly the suggested tools (local match, or Claude's suggestions)."""
        if ask_claude:
            res = self.ask_claude(session_id)
            sk, mc = [x["id"] for x in res["skills"]], [x["id"] for x in res["mcp"]]
        else:
            sug = self.tools(session_id)["suggested"]
            sk, mc = [x["id"] for x in sug["skills"]], [x["id"] for x in sug["mcp"]]
        return self.set_tools(session_id, skills=sk, mcp=mc)

    def ask_claude(self, session_id: str) -> dict:
        """Claude writes what the chat is about and suggests tools (uses your subscription)."""
        return self.wait(self._call("POST", f"/api/chats/{session_id}/ask-claude")["job"])

    def command(self, session_id: str, new: bool = False) -> dict:
        return self._call("GET", f"/api/chats/{session_id}/command", new=str(new).lower())

    def open(self, session_id: str, new: bool = False) -> dict:
        """Open the chat in a new terminal window with its tools."""
        return self._call("POST", f"/api/chats/{session_id}/open", {"new": new})

    def agent_options(self, session_id: str, new: bool = False) -> dict:
        """Keyword arguments for claude_agent_sdk.ClaudeAgentOptions that give the chat its chosen tools."""
        c = self.command(session_id, new=new)
        a = c["args"]
        opts: dict = {"cwd": c["cwd"]}

        def val(flag):
            return a[a.index(flag) + 1] if flag in a else None
        if val("--resume"):
            opts["resume"] = val("--resume")
        if val("--session-id"):
            opts["session_id"] = val("--session-id")
        if val("--settings"):
            opts["settings"] = val("--settings")
        if val("--add-dir"):
            opts["add_dirs"] = [val("--add-dir")]
        if val("--mcp-config"):
            with open(val("--mcp-config"), encoding="utf-8") as f:
                opts["mcp_servers"] = json.load(f).get("mcpServers", {})
            opts["strict_mcp_config"] = True
        return opts

    # ---- skills ----------------------------------------------------------------------------------------

    def skills(self, cwd: str = "") -> list[dict]:
        return self._call("GET", "/api/skills", cwd=cwd)["skills"]

    def create_skill(self, name: str, description: str, body: str, scope: str = "library", cwd: str = "") -> dict:
        """scope: library (this app), personal (~/.claude/skills) or project (<cwd>/.claude/skills)."""
        return self._call("POST", "/api/skills", {"name": name, "description": description, "body": body,
                                                  "scope": scope, "cwd": cwd})

    def draft_skill(self, request: str) -> dict:
        return self.wait(self._call("POST", "/api/skills/draft", {"request": request})["job"])

    # ---- MCP servers -------------------------------------------------------------------------------------

    def mcp_servers(self, cwd: str = "") -> list[dict]:
        return self._call("GET", "/api/mcp", cwd=cwd)

    def add_mcp(self, name: str, config: dict, description: str = "") -> dict:
        """config: {"command": "npx", "args": [...], "env": {...}} or {"type": "http", "url": "...", "headers": {...}}"""
        return self._call("POST", "/api/mcp/library", {"name": name, "config": config, "description": description})

    def test_mcp(self, server_id: str = "", config: dict | None = None, cwd: str = "") -> dict:
        return self._call("POST", "/api/mcp/test", {"id": server_id, "config": config, "cwd": cwd})

    def call_mcp_tool(self, server_id: str, tool: str, arguments: dict | None = None, cwd: str = "") -> dict:
        return self._call("POST", "/api/mcp/call", {"id": server_id, "tool": tool, "arguments": arguments or {},
                                                    "cwd": cwd})

    def connect_mcp(self, server_id: str, scope: str = "user", project_dir: str = "") -> dict:
        """Write the server into Claude Code's own config: scope 'user' (all projects) or 'project' (.mcp.json)."""
        return self._call("POST", "/api/mcp/install", {"id": server_id, "scope": scope, "to_cwd": project_dir})

    def create_mcp(self, name: str, description: str, tools: list[dict], template: str = "python") -> dict:
        """tools: [{"name": "get_x", "description": "...", "params": [{"name": "q", "type": "string"}],
        "body": "return q.upper()"}]. Body optional: implement_mcp() lets Claude write it."""
        return self._call("POST", "/api/mcp/create", {"name": name, "description": description, "tools": tools,
                                                      "template": template})

    def implement_mcp(self, name: str, request: str = "") -> dict:
        return self.wait(self._call("POST", f"/api/mcp/implement/{name}", {"request": request})["job"], timeout=1200)
