"""Create new MCP servers and skills (by hand, or drafted by Claude)."""
import json
import re
import shutil
import sys
from pathlib import Path

from . import claude_run, mcp, skills, store

TYPES = {"string": "str", "number": "float", "integer": "int", "boolean": "bool", "array": "list", "object": "dict"}
PY_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def servers_dir() -> Path:
    return store.library() / "mcp-servers"


def _check_tools(tools: list[dict]) -> list[dict]:
    out = []
    for t in tools:
        name = (t.get("name") or "").strip()
        if not PY_IDENT.match(name):
            raise ValueError(f"Tool name '{name}' must be letters, digits and _ (like get_weather)")
        params = []
        for p in t.get("params") or []:
            pn = (p.get("name") or "").strip()
            if not PY_IDENT.match(pn):
                raise ValueError(f"Parameter '{pn}' in {name} must be letters, digits and _")
            params.append({"name": pn, "type": p.get("type") if p.get("type") in TYPES else "string",
                           "description": p.get("description", "")})
        out.append({"name": name, "description": (t.get("description") or "").strip() or name, "params": params,
                    "body": t.get("body") or ""})
    if not out:
        raise ValueError("Add at least one tool")
    return out


def _mini_server(name: str, description: str, tools: list[dict]) -> str:
    blocks = []
    for t in tools:
        schema = {"type": "object", "properties": {p["name"]: {"type": p["type"], **(
            {"description": p["description"]} if p["description"] else {})} for p in t["params"]},
                  "required": [p["name"] for p in t["params"]]}
        sig = ", ".join(f"{p['name']}: {TYPES[p['type']]}" for p in t["params"])
        body = t["body"].strip() or (f'return "TODO: {t["name"]} is not written yet. Use \\"Write the tools with '
                                     f'Claude\\" in Tools Control, or edit server.py."')
        body = "\n".join("    " + line for line in body.splitlines())
        blocks.append(f'@app.tool({t["name"]!r}, {t["description"]!r},\n          {json.dumps(schema)})\n'
                      f'def {t["name"]}({sig}):\n{body}\n')
    return f'''"""{name} — MCP server made with Tools Control.

{description}

Runs with plain Python (no packages needed): python server.py
"""
from mini_mcp import Server, log  # noqa: F401  (log() prints to stderr for debugging)

app = Server({name!r}, "1.0.0", instructions={description!r})


{chr(10).join(blocks)}

if __name__ == "__main__":
    app.run()
'''


def _fastmcp_server(name: str, description: str, tools: list[dict]) -> str:
    blocks = []
    for t in tools:
        sig = ", ".join(f"{p['name']}: {TYPES[p['type']]}" for p in t["params"])
        doc = t["description"] + "".join(f"\n\n    {p['name']}: {p['description']}" for p in t["params"] if p["description"])
        body = t["body"].strip() or f'return "TODO: {t["name"]} is not written yet."'
        body = "\n".join("    " + line for line in body.splitlines())
        blocks.append(f'@mcp.tool()\ndef {t["name"]}({sig}):\n    """{doc}"""\n{body}\n')
    return f'''"""{name} — MCP server made with Tools Control (FastMCP, needs: pip install "mcp<2")."""
from mcp.server.fastmcp import FastMCP

mcp = FastMCP({name!r}, instructions={description!r})


{chr(10).join(blocks)}

if __name__ == "__main__":
    mcp.run(transport="stdio")
'''


def create_server(name: str, description: str, tools: list[dict], template: str = "python") -> dict:
    if not mcp.NAME_RE.match(name or ""):
        raise ValueError("Server names use letters, digits, - and _")
    tools = _check_tools(tools)
    d = servers_dir() / name
    if d.exists():
        raise ValueError(f"A server called {name} already exists in your library")
    d.mkdir(parents=True)
    if template == "fastmcp":
        (d / "server.py").write_text(_fastmcp_server(name, description, tools), encoding="utf-8")
        (d / "requirements.txt").write_text("mcp>=1.2,<2\n", encoding="utf-8")
    else:
        (d / "server.py").write_text(_mini_server(name, description, tools), encoding="utf-8")
        shutil.copy(Path(__file__).with_name("mini_mcp.py"), d / "mini_mcp.py")
    (d / "tools.json").write_text(json.dumps({"name": name, "description": description, "template": template,
                                              "tools": tools}, indent=2), encoding="utf-8")
    (d / "README.md").write_text(
        f"# {name}\n\n{description}\n\nMCP server made with Tools Control. Tools:\n\n"
        + "".join(f"- **{t['name']}**: {t['description']}\n" for t in tools)
        + f"\nRun: `python server.py` (Claude Code starts it for you once connected).\n", encoding="utf-8")
    cfg = {"command": sys.executable, "args": [str(d / "server.py")], "cwd": str(d)}
    entry = mcp.save_library(name, cfg, description)
    return {"server": entry, "folder": str(d)}


def server_code(name: str) -> dict:
    d = servers_dir() / name
    if not (d / "server.py").exists():
        raise ValueError("No such server in your library")
    return {"folder": str(d), "code": (d / "server.py").read_text(encoding="utf-8"),
            "spec": store.read_json(d / "tools.json", {})}


def save_server_code(name: str, code: str) -> None:
    d = servers_dir() / name
    if not d.exists():
        raise ValueError("No such server in your library")
    compile(code, "server.py", "exec")  # refuse to save code with syntax errors
    (d / "server.py").write_text(code, encoding="utf-8")


def implement_with_claude(name: str, request: str = "") -> dict:
    """Claude Code writes the tool bodies inside the server folder only, then the server is tested."""
    d = servers_dir() / name
    spec = store.read_json(d / "tools.json", {})
    prompt = f"""In this folder is an MCP server (server.py) whose tools still return TODO.
Write working Python for every tool so it does what its description says. Rules:
- Edit only files in this folder. Prefer the Python standard library; if a package is truly needed, list it in
  requirements.txt and import it inside the function.
- Keep each tool's name, parameters and the decorator exactly as they are.
- Return short, useful text or JSON-serialisable data. Never print to stdout (it carries the protocol);
  use log(...) for debugging.
- Handle bad input with a clear error message (raise ValueError).
Server: {name} — {spec.get('description', '')}
{('Extra instructions from the owner: ' + request) if request else ''}
When done, reply with one short paragraph saying what each tool does now."""
    summary = claude_run.ask(prompt, cwd=str(d), tools="Read,Edit,Write,Glob,Grep",
                             extra=["--permission-mode", "acceptEdits", "--add-dir", str(d)], timeout=900)
    compile((d / "server.py").read_text(encoding="utf-8"), "server.py", "exec")
    from . import mcp_client
    srv = mcp.get(f"library/{name}")
    test = mcp_client.probe(srv["config"]) if srv else {"ok": False, "error": "not in library"}
    return {"summary": summary, "test": test}


# ---- skills ------------------------------------------------------------------------------------------------

SKILL_SCHEMA = {"type": "object", "properties": {
    "name": {"type": "string", "description": "lowercase-hyphenated, max 64 chars"},
    "description": {"type": "string", "description": "What it does AND when Claude should use it (one or two sentences)"},
    "body": {"type": "string", "description": "The SKILL.md body in Markdown: steps, rules, examples"}},
    "required": ["name", "description", "body"]}


def draft_skill(request: str, context: str = "") -> dict:
    prompt = f"""Write a Claude Code skill (a SKILL.md) for this request:

{request}

{('Context: ' + context) if context else ''}

Good skills: a description that says what it does and exactly when to use it (Claude reads only the description
to decide); a body with clear numbered steps, the rules that matter, the output format, and one short example.
Keep it under 300 lines. Plain, direct language."""
    res = claude_run.ask(prompt, SKILL_SCHEMA)
    res["name"] = re.sub(r"[^a-z0-9-]", "-", res.get("name", "new-skill").lower()).strip("-")[:64] or "new-skill"
    return res


def save_skill(data: dict) -> dict:
    return skills.save(data["name"], data["description"], data.get("body", ""), data.get("scope", "library"),
                       data.get("cwd", ""), overwrite=bool(data.get("overwrite")))
