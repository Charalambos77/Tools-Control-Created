"""Open a chat with exactly the skills and MCP servers chosen for it.

Uses only Claude Code's own switches (checked against Claude Code 2.1):
- `--settings <file>` with "skillOverrides": {"<skill>": "off"} hides every skill that isn't chosen
  (works for personal, project, plugin and built-in skills);
- `--add-dir <folder>` whose .claude/skills holds copies of chosen skills from this app's library;
- `--mcp-config <file> --strict-mcp-config` loads only the chosen MCP servers;
- `--resume <id>` continues the chat (run in the chat's own folder), `--session-id <uuid>` starts a new one.
Nothing in Claude Code's own settings changes; each chat gets its files in data/chats/<id>/."""
import os
import shlex
import shutil
import subprocess
import uuid
from pathlib import Path

from . import claude_run, mcp, sessions, skills, store


def chat_dir(session_id: str) -> Path:
    return store.DATA / "chats" / session_id


def build(session_id: str, cwd: str, profile: dict) -> dict:
    """Write this chat's launch files. Returns the pieces and the argument list (without the claude exe)."""
    d = chat_dir(session_id)
    d.mkdir(parents=True, exist_ok=True)
    args: list[str] = []
    notes: list[str] = []
    all_sk = skills.all_skills(cwd)
    if profile.get("skills") is not None:
        on = set(profile["skills"])
        off = sorted({s["invoke"] for s in all_sk if s["id"] not in on and s["source"] != "library"})
        settings = {"skillOverrides": {name: "off" for name in off}}
        store.write_json(d / "settings.json", settings)
        args += ["--settings", str(d / "settings.json")]
        lib_dir = d / "skills" / ".claude" / "skills"
        if lib_dir.exists():
            shutil.rmtree(lib_dir)
        lib_on = [s for s in all_sk if s["source"] == "library" and s["id"] in on]
        if lib_on:
            for s in lib_on:
                shutil.copytree(s["path"], lib_dir / s["folder"])
            args += ["--add-dir", str(d / "skills")]
        n_on = sum(1 for s in all_sk if s["id"] in on)
        notes.append(f"{n_on} skills on, {len(off)} switched off for this chat")
    if profile.get("mcp") is not None:
        chosen = {}
        for sid in profile["mcp"]:
            srv = mcp.get(sid, cwd)
            if srv and srv["name"] not in chosen:
                chosen[srv["name"]] = srv["config"]
            elif not srv:
                notes.append(f"MCP server {sid} no longer exists — skipped")
        store.write_json(d / "mcp.json", {"mcpServers": chosen})
        args += ["--mcp-config", str(d / "mcp.json"), "--strict-mcp-config"]
        notes.append(f"{len(chosen)} MCP servers on ({', '.join(chosen) or 'none'})")
    return {"args": args, "notes": notes, "dir": str(d)}


def _quote_ps(a: str) -> str:
    return a if a and all(c.isalnum() or c in "-_./:\\=" for c in a) else "'" + a.replace("'", "''") + "'"


def command(session_id: str, new: bool = False, extra: list[str] | None = None) -> dict:
    """The full command for a chat: resume it (or start a new chat that uses this chat's tool choice)."""
    if new:
        src = sessions.get(session_id) if session_id != "new" else None
        cwd = (src or {}).get("cwd") or str(Path.home())
        new_id = str(uuid.uuid4())
        prof = store.get_profile(session_id) if src else store.get_profile("new")
        store.save_profile(new_id, skills=prof.get("skills"), mcp=prof.get("mcp"),
                           about=f"Started from “{src['title']}”" if src else "")
        b = build(new_id, cwd, store.get_profile(new_id))
        run = ["--session-id", new_id, *b["args"]]
        target = new_id
    else:
        info = sessions.get(session_id)
        if not info:
            raise ValueError("Chat not found")
        cwd = info["cwd"]
        b = build(session_id, cwd, store.get_profile(session_id))
        run = ["--resume", session_id, *b["args"]]
        target = session_id
    run += extra or []
    try:
        exe = claude_run.exe()
    except claude_run.ClaudeError:
        exe = "claude"
    ps = f"Set-Location {_quote_ps(cwd)}; & {_quote_ps(exe)} " + " ".join(_quote_ps(a) for a in run)
    sh = f"cd {shlex.quote(cwd)} && {shlex.quote(exe)} " + " ".join(shlex.quote(a) for a in run)
    return {"session_id": target, "cwd": cwd, "exe": exe, "args": run, "powershell": ps, "shell": sh,
            "notes": b["notes"]}


def open_terminal(cmd: dict) -> str:
    """Start Claude Code in a new terminal window on this PC."""
    cwd = cmd["cwd"] if os.path.isdir(cmd["cwd"]) else str(Path.home())
    if os.name == "nt":
        term = store.settings().get("terminal", "powershell")
        ps = cmd["powershell"]
        if term == "wt" and shutil.which("wt"):
            subprocess.Popen(["wt", "-d", cwd, "powershell", "-NoExit", "-Command", ps])
        elif term == "cmd":
            line = subprocess.list2cmdline([cmd["exe"], *cmd["args"]])
            subprocess.Popen(["cmd", "/c", "start", "Claude", "cmd", "/k", line], cwd=cwd)
        else:
            subprocess.Popen(["powershell", "-NoExit", "-Command", ps], cwd=cwd,
                             creationflags=subprocess.CREATE_NEW_CONSOLE)
        return "Opened a new terminal window"
    for t in (["x-terminal-emulator", "-e"], ["gnome-terminal", "--"], ["konsole", "-e"]):
        if shutil.which(t[0]):
            subprocess.Popen([*t, "bash", "-lc", cmd["shell"] + "; exec bash"], cwd=cwd)
            return "Opened a new terminal window"
    if shutil.which("osascript"):
        script = cmd["shell"].replace("\\", "\\\\").replace('"', '\\"')
        subprocess.Popen(["osascript", "-e", f'tell app "Terminal" to do script "{script}"'])
        return "Opened Terminal"
    raise RuntimeError("No terminal found — copy the command instead")


def apply_to_project(session_id: str) -> str:
    """Make the chat's skill choice the default for its whole folder (.claude/settings.local.json)."""
    info = sessions.get(session_id)
    if not info or not info["cwd"]:
        raise ValueError("Chat not found")
    prof = store.get_profile(session_id)
    if prof.get("skills") is None:
        raise ValueError("Choose the skills for this chat first")
    on = set(prof["skills"])
    path = Path(info["cwd"]) / ".claude" / "settings.local.json"
    data = store.read_json(path, {})
    over = data.get("skillOverrides") or {}
    for s in skills.all_skills(info["cwd"]):
        if s["source"] == "library":
            continue
        if s["id"] in on:
            over.pop(s["invoke"], None)
        else:
            over[s["invoke"]] = "off"
    data["skillOverrides"] = over
    store.write_json(path, data, backup=True)
    return str(path)
