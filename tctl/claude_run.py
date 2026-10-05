"""Ask Claude (Claude Code headless, your subscription) for summaries, suggestions and drafts. Runs as background jobs."""
import json
import os
import shutil
import subprocess
import threading
import time
import uuid

from . import store

_jobs: dict[str, dict] = {}


class ClaudeError(RuntimeError):
    pass


def exe() -> str:
    s = store.settings().get("claude_exe")
    if s:
        return s
    found = shutil.which("claude")
    if found:
        return found
    if os.name == "nt":
        for p in (os.path.expandvars(r"%USERPROFILE%\.local\bin\claude.exe"),
                  os.path.expandvars(r"%APPDATA%\npm\claude.cmd")):
            if os.path.exists(p):
                return p
    raise ClaudeError("Claude Code (claude) was not found — install it or set its path in Settings")


def ask(prompt: str, schema: dict | None = None, cwd: str | None = None, model: str | None = None,
        extra: list[str] | None = None, timeout: int = 300, tools: str = "") -> dict | str:
    """One headless turn. With a schema the answer is parsed JSON. tools="" = no tools (just thinking)."""
    if store.DEMO and not os.environ.get("TC_DEMO_REAL_CLAUDE"):
        from . import demo
        return demo.fake_claude(prompt, schema)
    args = [exe(), "-p", "--output-format", "json", "--no-session-persistence", "--tools", tools,
            "--strict-mcp-config", "--model", model or store.settings().get("summary_model") or "sonnet"]
    if schema:
        args += ["--json-schema", json.dumps(schema)]
    args += extra or []
    kw = {"creationflags": 0x08000000} if os.name == "nt" else {}
    try:
        r = subprocess.run(args, input=prompt, capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=timeout, cwd=cwd if cwd and os.path.isdir(cwd) else None, **kw)
    except subprocess.TimeoutExpired as e:
        raise ClaudeError("Claude took too long") from e
    except OSError as e:
        raise ClaudeError(f"Could not start Claude Code: {e}") from e
    try:
        out = json.loads(r.stdout)
    except ValueError:
        raise ClaudeError((r.stderr or r.stdout or "No answer from Claude").strip()[:500])
    if out.get("is_error"):
        raise ClaudeError(str(out.get("result") or out.get("subtype") or "Claude returned an error")[:500])
    if schema:
        so = out.get("structured_output")
        if so is not None:
            return so
        text = str(out.get("result", "")).strip()
        start, end = text.find("{"), text.rfind("}")
        try:
            return json.loads(text[start:end + 1])
        except ValueError as e:
            raise ClaudeError("Claude's answer was not in the expected shape") from e
    return str(out.get("result", "")).strip()


# ---- background jobs -------------------------------------------------------------------------------------

def start_job(kind: str, fn, *a, **kw) -> str:
    jid = uuid.uuid4().hex[:10]
    _jobs[jid] = {"id": jid, "kind": kind, "status": "running", "started": time.time(), "result": None, "error": None}

    def run():
        try:
            _jobs[jid]["result"] = fn(*a, **kw)
            _jobs[jid]["status"] = "done"
        except Exception as e:  # report every failure to the page
            _jobs[jid]["error"] = str(e)
            _jobs[jid]["status"] = "failed"
        _jobs[jid]["finished"] = time.time()

    threading.Thread(target=run, daemon=True).start()
    return jid


def job(jid: str) -> dict | None:
    return _jobs.get(jid)
