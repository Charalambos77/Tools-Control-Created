"""Where things are: Claude Code's own folders (read, and written only when you ask) and this app's data."""
import json
import os
import sqlite3
import threading
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
DATA = Path(os.environ.get("TC_DATA", APP / "data"))
DEMO = os.environ.get("TC_DEMO") == "1"
_lock = threading.RLock()

DEFAULT_SETTINGS = {
    "claude_dir": "",        # empty = %USERPROFILE%\.claude (or CLAUDE_CONFIG_DIR)
    "claude_exe": "",        # empty = `claude` on PATH
    "terminal": "powershell",  # how "Open chat" starts Claude on Windows: powershell | wt (Windows Terminal) | cmd
    "summary_model": "sonnet",
}


def home() -> Path:
    if DEMO:
        return DATA / "demo-home"
    return Path.home()


def claude_dir() -> Path:
    s = settings().get("claude_dir")
    if s:
        return Path(s).expanduser()
    if DEMO:
        return home() / ".claude"
    env = os.environ.get("CLAUDE_CONFIG_DIR")
    return Path(env) if env else home() / ".claude"


def claude_json() -> Path:
    """~/.claude.json: user- and local-scope MCP servers and per-project state."""
    env = os.environ.get("CLAUDE_CONFIG_DIR")
    if env and not DEMO and not settings().get("claude_dir"):
        return Path(env) / ".claude.json"
    if settings().get("claude_dir"):
        return Path(settings()["claude_dir"]).expanduser().parent / ".claude.json"
    return home() / ".claude.json"


def library() -> Path:
    """This app's own skills and MCP servers (made or added here)."""
    return DATA / "library"


# ---- small JSON files --------------------------------------------------------------------------------------

def read_json(path: Path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return json.loads(json.dumps(default))


def write_json(path: Path, value, backup: bool = False) -> None:
    """Atomic write. backup=True keeps one copy of the previous file as <name>.bak (for Claude's own files)."""
    path = Path(path)
    with _lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        if backup and path.exists():
            bak = path.with_name(path.name + ".tools-control.bak")
            bak.write_bytes(path.read_bytes())
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)


def settings() -> dict:
    s = dict(DEFAULT_SETTINGS)
    s.update(read_json(DATA / "settings.json", {}))
    return s


def update_settings(patch: dict) -> dict:
    s = settings()
    s.update({k: v for k, v in patch.items() if k in DEFAULT_SETTINGS})
    write_json(DATA / "settings.json", s)
    return s


# ---- database: per-chat profiles and the transcript index ---------------------------------------------------

SCHEMA = """
CREATE TABLE IF NOT EXISTS profiles (
  session_id TEXT PRIMARY KEY,
  about TEXT,              -- what Harry wrote the chat is about
  about_auto TEXT,         -- what Claude wrote (Summarise with Claude)
  skills TEXT,             -- JSON list of skill ids enabled for this chat; NULL = not decided (everything as usual)
  mcp TEXT,                -- JSON list of MCP server ids enabled for this chat; NULL = not decided
  ai_suggestions TEXT,     -- JSON from "Ask Claude"
  updated_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS transcript_index (
  path TEXT PRIMARY KEY,
  mtime REAL, size INTEGER,
  data TEXT
);
"""


def db() -> sqlite3.Connection:
    DATA.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DATA / "tools.db", check_same_thread=False)
    c.row_factory = sqlite3.Row
    c.executescript(SCHEMA)
    return c


def get_profile(session_id: str) -> dict:
    with db() as c:
        r = c.execute("SELECT * FROM profiles WHERE session_id=?", (session_id,)).fetchone()
    if not r:
        return {"session_id": session_id, "about": "", "about_auto": "", "skills": None, "mcp": None,
                "ai_suggestions": None}
    d = dict(r)
    for k in ("skills", "mcp", "ai_suggestions"):
        d[k] = json.loads(d[k]) if d[k] else None
    return d


def save_profile(session_id: str, **fields) -> dict:
    cur = get_profile(session_id)
    cur.update({k: v for k, v in fields.items() if k in ("about", "about_auto", "skills", "mcp", "ai_suggestions")})
    enc = lambda v: None if v is None else json.dumps(v)
    with db() as c:
        c.execute("""INSERT INTO profiles(session_id, about, about_auto, skills, mcp, ai_suggestions, updated_at)
                     VALUES(?,?,?,?,?,?,datetime('now'))
                     ON CONFLICT(session_id) DO UPDATE SET about=excluded.about, about_auto=excluded.about_auto,
                       skills=excluded.skills, mcp=excluded.mcp, ai_suggestions=excluded.ai_suggestions,
                       updated_at=excluded.updated_at""",
                  (session_id, cur["about"] or "", cur["about_auto"] or "", enc(cur["skills"]), enc(cur["mcp"]),
                   enc(cur["ai_suggestions"])))
    return get_profile(session_id)


def all_profiles() -> dict[str, dict]:
    with db() as c:
        rows = c.execute("SELECT session_id FROM profiles").fetchall()
    return {r["session_id"]: get_profile(r["session_id"]) for r in rows}
