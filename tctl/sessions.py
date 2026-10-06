"""Read Claude Code conversations from ~/.claude/projects/<folder>/<session-id>.jsonl (read-only)."""
import json
import re
from collections import Counter
from pathlib import Path

from . import store

_REMINDER = re.compile(r"<system-reminder>.*?</system-reminder>", re.S)
_TAGS = re.compile(r"<(command-name|command-message|command-args|local-command-stdout|local-command-stderr)>.*?</\1>",
                   re.S)
_SKIP_PREFIXES = ("Caveat:", "[Request interrupted", "<local-command", "<command-", "This session is being continued")


def encode_cwd(cwd: str) -> str:
    """How Claude Code names a project folder: every character that isn't a letter, digit or '-' becomes '-'."""
    return re.sub(r"[^A-Za-z0-9-]", "-", cwd)


def _text_of(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
    return ""


def clean_prompt(text: str) -> str:
    text = _REMINDER.sub("", text or "")
    cmd = re.search(r"<command-name>(.*?)</command-name>", text, re.S)
    args = re.search(r"<command-args>(.*?)</command-args>", text, re.S)
    text = _TAGS.sub("", text).strip()
    if cmd and not text:
        text = f"{cmd.group(1).strip()} {args.group(1).strip() if args else ''}".strip()
    return text


def _is_human_prompt(d: dict) -> str | None:
    """The text Harry typed, or None for tool results, meta lines and Claude-made messages."""
    if d.get("type") != "user" or d.get("isMeta") or d.get("isSidechain") or d.get("isCompactSummary"):
        return None
    m = d.get("message") or {}
    c = m.get("content")
    if isinstance(c, list) and any(isinstance(b, dict) and b.get("type") == "tool_result" for b in c):
        return None
    t = clean_prompt(_text_of(c))
    if not t or t.startswith(_SKIP_PREFIXES):
        return None
    return t


def _tool_key(name: str) -> str:
    if name.startswith("mcp__"):
        parts = name.split("__")
        return f"mcp:{parts[1]}" if len(parts) > 1 else name
    return name


def parse(path: Path) -> dict:
    """One pass over a transcript: what the list and the suggestions need."""
    info = {"id": path.stem, "folder": path.parent.name, "path": str(path), "cwd": "", "branch": "",
            "title": "", "custom_title": "", "summary": "", "first_prompt": "", "last_prompt": "",
            "started": "", "updated": "", "prompts": 0, "replies": 0, "tools": {}, "skills_used": [],
            "mcp_used": [], "cost_usd": None, "model": "", "text_sample": ""}
    tools: Counter = Counter()
    skills: list[str] = []
    prompts: list[str] = []
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            try:
                d = json.loads(line)
            except ValueError:
                continue
            t = d.get("type")
            ts = d.get("timestamp")
            if ts:
                info["started"] = info["started"] or ts
                info["updated"] = max(info["updated"], ts)
            if d.get("cwd") and not info["cwd"]:
                info["cwd"] = d["cwd"]
            if d.get("gitBranch"):
                info["branch"] = d["gitBranch"]
            if t == "custom-title" and d.get("customTitle"):
                info["custom_title"] = d["customTitle"]
            elif t == "summary" and d.get("summary"):
                info["summary"] = d["summary"]
            elif t in ("ai-title", "title") and (d.get("aiTitle") or d.get("title")):
                info["summary"] = info["summary"] or d.get("aiTitle") or d.get("title")
            elif t == "last-prompt" and d.get("lastPrompt"):
                info["last_prompt"] = clean_prompt(d["lastPrompt"])[:300]
            elif t == "cost-state" and d.get("totalCostUSD") is not None:
                info["cost_usd"] = d["totalCostUSD"]
            elif t == "user":
                p = _is_human_prompt(d)
                if p:
                    info["prompts"] += 1
                    prompts.append(p)
                    if not info["first_prompt"]:
                        info["first_prompt"] = p[:500]
                    info["last_prompt"] = p[:300]
            elif t == "assistant" and not d.get("isSidechain"):
                m = d.get("message") or {}
                info["model"] = m.get("model") or info["model"]
                content = m.get("content")
                if isinstance(content, list):
                    if any(b.get("type") == "text" for b in content if isinstance(b, dict)):
                        info["replies"] += 1
                    for b in content:
                        if isinstance(b, dict) and b.get("type") == "tool_use":
                            tools[_tool_key(b.get("name", ""))] += 1
                            if b.get("name") == "Skill":
                                inp = b.get("input") or {}
                                s = inp.get("skill") or inp.get("command") or inp.get("name")
                                if s and s not in skills:
                                    skills.append(str(s).lstrip("/"))
    info["tools"] = dict(tools.most_common())
    info["skills_used"] = skills
    info["mcp_used"] = sorted(k[4:] for k in tools if k.startswith("mcp:"))
    info["title"] = info["custom_title"] or info["summary"] or (info["first_prompt"].split("\n")[0][:90]
                                                               if info["first_prompt"] else "(no prompt yet)")
    sample = "\n".join(p[:600] for p in prompts[:25])
    info["text_sample"] = sample[:8000]
    return info


def _index(path: Path, cache: dict) -> dict | None:
    try:
        st = path.stat()
    except OSError:
        return None
    hit = cache.get(str(path))
    if hit and hit[0] == st.st_mtime and hit[1] == st.st_size:
        return hit[2]
    info = parse(path)
    info["size"] = st.st_size
    with store.db() as c:
        c.execute("INSERT OR REPLACE INTO transcript_index(path, mtime, size, data) VALUES(?,?,?,?)",
                  (str(path), st.st_mtime, st.st_size, json.dumps(info)))
    return info


def files() -> list[Path]:
    root = store.claude_dir() / "projects"
    if not root.is_dir():
        return []
    return [p for p in root.glob("*/*.jsonl") if p.is_file()]


def _file_has(path: Path, words: list[str]) -> bool:
    try:
        text = path.read_text(encoding="utf-8", errors="replace").lower()
    except OSError:
        return False
    return all(w in text for w in words)


# ---- projects: which folder a chat belongs to, and which folders to hide --------------------------------------

_WORKTREE = re.compile(r"[\\/]\.claude[\\/]worktrees[\\/][^\\/]+$", re.I)
_RANDOM = re.compile(r"^([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}|[0-9a-f]{16,}|"
                     r"(?=.*\d)(?=.*[a-z])[a-z0-9]{20,})$", re.I)
_APP_DIRS = ("local-agent-mode-sessions", "appdata/roaming/claude/", "application support/claude/",
             "/.claude/projects/", "/.config/claude/")


def project_of(cwd: str, folder: str = "") -> str:
    """The project a chat belongs to. A worktree (<repo>/.claude/worktrees/<name>) belongs to its repo."""
    if not cwd:
        return folder
    return _WORKTREE.sub("", cwd.rstrip("\\/")) or cwd


def junk_reason(cwd: str) -> str:
    """Why a project folder looks machine-made rather than yours ('' = it looks like a real project)."""
    if not cwd or ("/" not in cwd and "\\" not in cwd):  # no cwd: only Claude Code's encoded folder name
        return "No folder was recorded"
    path = cwd.replace("\\", "/").rstrip("/")
    home = str(store.home()).replace("\\", "/").rstrip("/")
    if path.lower().startswith(home.lower() + "/"):  # judge only the part inside your home folder
        path = path[len(home):]
    low = path.lower() + "/"
    parts = [x for x in low.split("/") if x]
    if any(x in ("tmp", "temp") for x in parts) or "/var/folders/" in low:
        return "Temporary folder"
    if any(d in low for d in _APP_DIRS):
        return "Made by the Claude app"
    if parts and _RANDOM.match(parts[-1]):
        return "Random folder name"
    return ""


def _hidden_file() -> Path:
    return store.DATA / "projects.json"


def hidden_overrides() -> dict[str, bool]:
    """Your own choices: {project: True (hide) | False (show even if it looks machine-made)}."""
    return store.read_json(_hidden_file(), {}).get("hidden", {})


def set_hidden(project: str, hidden: bool) -> dict[str, bool]:
    data = store.read_json(_hidden_file(), {})
    ov = data.setdefault("hidden", {})
    ov[project] = bool(hidden)
    store.write_json(_hidden_file(), data)
    return ov


def is_hidden(project: str, overrides: dict[str, bool] | None = None) -> bool:
    ov = hidden_overrides() if overrides is None else overrides
    return ov[project] if project in ov else bool(junk_reason(project))


def list_sessions(query: str = "", project: str = "", full: bool = False, hidden: bool = False) -> list[dict]:
    """Chats newest first. `full` searches the whole transcript, not just the indexed sample.
    Chats in hidden projects are left out unless `hidden` is set or that project is asked for by name."""
    overrides = hidden_overrides()
    with store.db() as c:
        cache = {r["path"]: (r["mtime"], r["size"], json.loads(r["data"]))
                 for r in c.execute("SELECT * FROM transcript_index")}
    out = []
    profiles = store.all_profiles()
    for p in files():
        info = _index(p, cache)
        if not info or (info["prompts"] == 0 and info["replies"] == 0):
            continue
        prof = profiles.get(info["id"], {})
        row = {k: info[k] for k in ("id", "title", "cwd", "folder", "branch", "started", "updated", "prompts",
                                    "replies", "skills_used", "mcp_used", "first_prompt", "size", "cost_usd")}
        row["about"] = prof.get("about") or ""
        row["has_profile"] = bool(prof.get("skills") is not None or prof.get("mcp") is not None)
        row["project"] = project_of(info["cwd"], info["folder"])
        if project and project not in (row["project"], info["cwd"], info["folder"]):
            continue
        if not hidden and not project and is_hidden(row["project"], overrides):
            continue
        if query:
            hay = " ".join([row["title"], row["cwd"], row["first_prompt"], row["about"], info["text_sample"]]).lower()
            words = query.lower().split()
            if not all(w in hay for w in words) and not (full and _file_has(p, words)):
                continue
        out.append(row)
    out.sort(key=lambda r: r["updated"], reverse=True)
    return out


def find(session_id: str) -> Path | None:
    if not re.fullmatch(r"[A-Za-z0-9._-]+", session_id or ""):
        return None
    for p in files():
        if p.stem == session_id:
            return p
    return None


def get(session_id: str) -> dict | None:
    p = find(session_id)
    if not p:
        return None
    with store.db() as c:
        cache = {r["path"]: (r["mtime"], r["size"], json.loads(r["data"]))
                 for r in c.execute("SELECT * FROM transcript_index WHERE path=?", (str(p),))}
    info = _index(p, cache)
    if info:
        info = {**info, "project": project_of(info["cwd"], info["folder"])}
    return info


def messages(session_id: str, offset: int = 0, limit: int = 60) -> dict:
    """The readable conversation: what was asked, what Claude answered, which tools it used."""
    p = find(session_id)
    if not p:
        return {"total": 0, "items": []}
    items = []
    pending_tools: list[str] = []
    with open(p, encoding="utf-8", errors="replace") as f:
        for line in f:
            try:
                d = json.loads(line)
            except ValueError:
                continue
            if d.get("isSidechain"):
                continue
            if d.get("type") == "user":
                t = _is_human_prompt(d)
                if t:
                    items.append({"role": "you", "text": t[:6000], "time": d.get("timestamp")})
            elif d.get("type") == "assistant":
                content = (d.get("message") or {}).get("content")
                if not isinstance(content, list):
                    continue
                for b in content:
                    if not isinstance(b, dict):
                        continue
                    if b.get("type") == "tool_use":
                        name = b.get("name", "")
                        if name == "Skill":
                            inp = b.get("input") or {}
                            name = f"Skill: {inp.get('skill') or inp.get('command') or ''}"
                        pending_tools.append(name)
                    elif b.get("type") == "text" and b.get("text", "").strip():
                        items.append({"role": "claude", "text": b["text"][:6000], "time": d.get("timestamp"),
                                      "tools": pending_tools})
                        pending_tools = []
    if pending_tools:
        items.append({"role": "claude", "text": "", "tools": pending_tools, "time": None})
    total = len(items)
    if offset < 0:
        offset = max(0, total + offset)
    return {"total": total, "offset": offset, "items": items[offset:offset + limit]}


def projects(include_hidden: bool = False) -> list[dict]:
    """Projects newest first; `cwd` is the project's folder (worktrees folded into their repo)."""
    overrides = hidden_overrides()
    seen: dict[str, dict] = {}
    for s in list_sessions(hidden=True):
        key = s["project"]
        e = seen.setdefault(key, {"cwd": key, "folder": s["folder"], "chats": 0, "updated": "",
                                  "reason": junk_reason(key), "hidden": is_hidden(key, overrides)})
        e["chats"] += 1
        e["updated"] = max(e["updated"], s["updated"])
    out = [e for e in seen.values() if include_hidden or not e["hidden"]]
    return sorted(out, key=lambda e: e["updated"], reverse=True)
