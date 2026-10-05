"""Tools Control — the local web app (http://127.0.0.1:8450)."""
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import claude_run, create, launch, mcp, mcp_client, sessions, skills, store, suggest

STATIC = store.APP / "static"


@asynccontextmanager
async def lifespan(_app):
    if store.DEMO:
        from . import demo
        demo.ensure()
    yield


app = FastAPI(title="Tools Control", lifespan=lifespan)


def bad(e: Exception, code: int = 400):
    raise HTTPException(code, str(e))


def _cwd_of(session_id: str) -> str:
    info = sessions.get(session_id)
    return info["cwd"] if info else ""


# ---- chats ----------------------------------------------------------------------------------------------

@app.get("/api/chats")
def chats(q: str = "", project: str = ""):
    return sessions.list_sessions(q, project)


@app.get("/api/projects")
def projects():
    return sessions.projects()


@app.get("/api/chats/{sid}")
def chat(sid: str):
    info = sessions.get(sid)
    if not info:
        bad(ValueError("Chat not found"), 404)
    return {"info": info, "profile": store.get_profile(sid)}


@app.get("/api/chats/{sid}/messages")
def chat_messages(sid: str, offset: int = 0, limit: int = 60):
    return sessions.messages(sid, offset, limit)


@app.post("/api/chats/{sid}/about")
def chat_about(sid: str, body: dict = Body(...)):
    return store.save_profile(sid, about=str(body.get("about", ""))[:4000])


@app.get("/api/chats/{sid}/tools")
def chat_tools(sid: str):
    """Everything the chat page needs to choose tools: all skills and servers, what's on, suggestions."""
    info = sessions.get(sid)
    if not info:
        bad(ValueError("Chat not found"), 404)
    prof = store.get_profile(sid)
    try:
        sug = suggest.local(sid)
    except ValueError:
        sug = {"skills": [], "mcp": []}
    return {"skills": skills.all_skills(info["cwd"]),
            "mcp": [dict(s, config=mcp.mask(s["config"])) for s in mcp.all_servers(info["cwd"])],
            "profile": prof, "suggested": sug, "claude_skills_checked": skills.claude_seen().get("checked")}


@app.post("/api/chats/{sid}/tools")
def set_chat_tools(sid: str, body: dict = Body(...)):
    fields = {}
    for k in ("skills", "mcp"):
        if k in body:
            v = body[k]
            if v is not None and not isinstance(v, list):
                bad(ValueError(f"{k} must be a list or null"))
            fields[k] = v
    return store.save_profile(sid, **fields)


@app.post("/api/chats/{sid}/ask-claude")
def chat_ask_claude(sid: str):
    return {"job": claude_run.start_job("ask", suggest.ask_claude, sid)}


@app.get("/api/chats/{sid}/command")
def chat_command(sid: str, new: bool = False):
    try:
        return launch.command(sid, new=new)
    except (ValueError, OSError) as e:
        bad(e)


@app.post("/api/chats/{sid}/open")
def chat_open(sid: str, body: dict = Body(default={})):
    try:
        cmd = launch.command(sid, new=bool(body.get("new")))
        if store.DEMO:
            return {"message": "Demo: this would open a terminal running the command below", "command": cmd}
        return {"message": launch.open_terminal(cmd), "command": cmd}
    except (ValueError, OSError, RuntimeError) as e:
        bad(e)


@app.post("/api/chats/{sid}/apply-to-project")
def chat_apply_project(sid: str):
    try:
        return {"path": launch.apply_to_project(sid)}
    except ValueError as e:
        bad(e)


@app.get("/api/jobs/{jid}")
def job(jid: str):
    j = claude_run.job(jid)
    if not j:
        bad(ValueError("No such job"), 404)
    return j


# ---- skills ----------------------------------------------------------------------------------------------

@app.get("/api/skills")
def skill_list(cwd: str = ""):
    return {"skills": skills.all_skills(cwd), "claude": skills.claude_seen()}


@app.get("/api/skills/text")
def skill_text(id: str, cwd: str = ""):
    s = skills.get(id, cwd)
    if not s:
        bad(ValueError("Skill not found"), 404)
    return {"skill": s, "text": skills.read_text(s) if s.get("path") else f"---\nname: {s['invoke']}\ndescription: "
            f"{s['description']}\n---\n\n(This skill is built into Claude Code or a synced plugin; its file is not on this PC.)"}


@app.post("/api/skills/text")
def skill_save_text(body: dict = Body(...)):
    s = skills.get(body.get("id", ""), body.get("cwd", ""))
    if not s:
        bad(ValueError("Skill not found"), 404)
    try:
        return skills.write_text(s, body.get("text", ""))
    except ValueError as e:
        bad(e)


@app.post("/api/skills")
def skill_create(body: dict = Body(...)):
    try:
        return create.save_skill(body)
    except ValueError as e:
        bad(e)


@app.post("/api/skills/copy")
def skill_copy(body: dict = Body(...)):
    s = skills.get(body.get("id", ""), body.get("cwd", ""))
    if not s:
        bad(ValueError("Skill not found"), 404)
    try:
        return skills.copy(s, body.get("scope", "library"), body.get("to_cwd", ""))
    except (ValueError, OSError) as e:
        bad(e)


@app.post("/api/skills/delete")
def skill_delete(body: dict = Body(...)):
    s = skills.get(body.get("id", ""), body.get("cwd", ""))
    if not s:
        bad(ValueError("Skill not found"), 404)
    try:
        skills.delete(s)
    except ValueError as e:
        bad(e)
    return {"ok": True}


@app.post("/api/skills/draft")
def skill_draft(body: dict = Body(...)):
    if not str(body.get("request", "")).strip():
        bad(ValueError("Describe the skill first"))
    return {"job": claude_run.start_job("draft", create.draft_skill, body["request"], body.get("context", ""))}


@app.post("/api/skills/detect")
def skill_detect(body: dict = Body(default={})):
    return {"job": claude_run.start_job("detect", suggest.detect_claude_skills, body.get("cwd", ""))}


# ---- MCP servers -------------------------------------------------------------------------------------------

@app.get("/api/mcp")
def mcp_list(cwd: str = ""):
    return [dict(s, config=mcp.mask(s["config"])) for s in mcp.all_servers(cwd)]


@app.get("/api/mcp/library/{name}")
def mcp_library_get(name: str):
    cfg = mcp.library().get(name)
    if not cfg:
        bad(ValueError("Not in your library"), 404)
    meta = store.read_json(store.library() / "mcp_meta.json", {}).get(name, {})
    made = (create.servers_dir() / name / "server.py").exists()
    return {"name": name, "config": cfg, "description": meta.get("description", ""), "made_here": made}


@app.post("/api/mcp/library")
def mcp_library_save(body: dict = Body(...)):
    try:
        return mcp.save_library(body.get("name", ""), body.get("config", {}), body.get("description", ""),
                                body.get("old_name", ""))
    except ValueError as e:
        bad(e)


@app.delete("/api/mcp/library/{name}")
def mcp_library_delete(name: str):
    return {"ok": mcp.delete_library(name)}


@app.post("/api/mcp/import")
def mcp_import(body: dict = Body(...)):
    try:
        return {"added": mcp.import_json(body.get("json", ""))}
    except ValueError as e:
        bad(e)


def _full_config(server_id: str, cwd: str) -> dict:
    s = mcp.get(server_id, cwd)
    if not s:
        bad(ValueError("Server not found"), 404)
    return s


@app.post("/api/mcp/test")
def mcp_test(body: dict = Body(...)):
    if body.get("config"):
        cfg = body["config"]
    else:
        cfg = _full_config(body.get("id", ""), body.get("cwd", ""))["config"]
    return mcp_client.probe(cfg, timeout=float(body.get("timeout", 40)))


@app.post("/api/mcp/call")
def mcp_call(body: dict = Body(...)):
    s = _full_config(body.get("id", ""), body.get("cwd", ""))
    try:
        return mcp_client.call_tool(s["config"], body["tool"], body.get("arguments") or {})
    except (mcp_client.MCPError, KeyError) as e:
        bad(e)


@app.post("/api/mcp/install")
def mcp_install(body: dict = Body(...)):
    s = _full_config(body.get("id", ""), body.get("cwd", ""))
    try:
        return {"path": mcp.install(s["name"], s["config"], body.get("scope", "user"), body.get("to_cwd", ""))}
    except ValueError as e:
        bad(e)


@app.post("/api/mcp/uninstall")
def mcp_uninstall(body: dict = Body(...)):
    s = _full_config(body.get("id", ""), body.get("cwd", ""))
    try:
        return {"path": mcp.uninstall(s, body.get("cwd", ""))}
    except ValueError as e:
        bad(e)


@app.post("/api/mcp/create")
def mcp_create(body: dict = Body(...)):
    try:
        return create.create_server(body.get("name", ""), body.get("description", ""), body.get("tools", []),
                                    body.get("template", "python"))
    except ValueError as e:
        bad(e)


@app.get("/api/mcp/code/{name}")
def mcp_code(name: str):
    try:
        return create.server_code(name)
    except ValueError as e:
        bad(e, 404)


@app.post("/api/mcp/code/{name}")
def mcp_code_save(name: str, body: dict = Body(...)):
    try:
        create.save_server_code(name, body.get("code", ""))
    except (ValueError, SyntaxError) as e:
        bad(e)
    return {"ok": True}


@app.post("/api/mcp/implement/{name}")
def mcp_implement(name: str, body: dict = Body(default={})):
    return {"job": claude_run.start_job("implement", create.implement_with_claude, name, body.get("request", ""))}


def self_server_config() -> dict:
    cfg = {"command": sys.executable, "args": ["-m", "tctl.mcp_server"], "cwd": str(store.APP)}
    env = {}
    if str(store.DATA) != str(store.APP / "data"):
        env["TC_DATA"] = str(store.DATA)
    if store.DEMO:
        env["TC_DEMO"] = "1"
    if env:
        cfg["env"] = env
    return cfg


@app.get("/api/self-mcp")
def self_mcp():
    cfg = self_server_config()
    cj = store.read_json(store.claude_json(), {})
    return {"config": cfg, "connected": "tools-control" in (cj.get("mcpServers") or {}),
            "command": f'claude mcp add tools-control -s user -- "{cfg["command"]}" -m tctl.mcp_server'}


@app.post("/api/self-mcp/connect")
def self_mcp_connect():
    return {"path": mcp.install("tools-control", self_server_config(), "user")}


# ---- settings + UI ----------------------------------------------------------------------------------------

@app.get("/api/settings")
def get_settings():
    try:
        exe = claude_run.exe()
    except claude_run.ClaudeError as e:
        exe = f"not found ({e})"
    return {**store.settings(), "demo": store.DEMO, "data_dir": str(store.DATA),
            "claude_dir_used": str(store.claude_dir()), "claude_json_used": str(store.claude_json()),
            "claude_found": exe}


@app.post("/api/settings")
def set_settings(body: dict = Body(...)):
    return store.update_settings(body)


app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")
