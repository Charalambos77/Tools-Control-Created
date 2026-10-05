"""Find every MCP server Claude Code is configured with, keep a library of your own, connect them where you choose."""
import re
from pathlib import Path

from . import store

NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
SECRETISH = re.compile(r"(key|token|secret|password|auth|bearer|cookie)", re.I)


def _norm(p: str) -> str:
    return str(p).replace("\\", "/").rstrip("/").lower()


def kind(cfg: dict) -> str:
    return cfg.get("type") or ("stdio" if cfg.get("command") else "http" if cfg.get("url") else "?")


def mask(cfg: dict) -> dict:
    """Hide token-looking values when listing (full values stay in the files)."""
    out = dict(cfg)
    for field in ("env", "headers"):
        if isinstance(cfg.get(field), dict):
            out[field] = {k: (("•••• " + str(v)[-4:]) if SECRETISH.search(k) or len(str(v)) > 24 else v)
                          for k, v in cfg[field].items()}
    return out


def _entry(scope: str, name: str, cfg: dict, where: str, extra: dict | None = None) -> dict:
    meta = store.read_json(store.library() / "mcp_meta.json", {}).get(name, {}) if scope == "library" else {}
    return {"id": f"{scope}/{name}", "name": name, "scope": scope, "where": where, "type": kind(cfg),
            "config": cfg, "description": meta.get("description", ""), **(extra or {})}


def project_mcp_file(cwd: str) -> Path | None:
    if not cwd:
        return None
    for d in [Path(cwd), *Path(cwd).parents]:
        f = d / ".mcp.json"
        if f.exists():
            return f
        if (d / ".git").exists():
            break
    return Path(cwd) / ".mcp.json"


def all_servers(cwd: str = "") -> list[dict]:
    out: list[dict] = []
    cj_path = store.claude_json()
    cj = store.read_json(cj_path, {})
    for name, cfg in (cj.get("mcpServers") or {}).items():
        out.append(_entry("user", name, cfg, str(cj_path)))
    if cwd:
        for path, proj in (cj.get("projects") or {}).items():
            if _norm(path) == _norm(cwd):
                for name, cfg in (proj.get("mcpServers") or {}).items():
                    out.append(_entry("local", name, cfg, f"{cj_path} (this folder only)"))
        pf = project_mcp_file(cwd)
        if pf and pf.exists():
            proj_settings = _project_settings(cwd)
            for name, cfg in (store.read_json(pf, {}).get("mcpServers") or {}).items():
                approved = (proj_settings.get("enableAllProjectMcpServers")
                            or name in (proj_settings.get("enabledMcpjsonServers") or []))
                blocked = name in (proj_settings.get("disabledMcpjsonServers") or [])
                out.append(_entry("project", name, cfg, str(pf),
                                  {"approved": bool(approved) and not blocked, "blocked": blocked}))
    plugins = store.claude_dir() / "plugins"
    if plugins.is_dir():
        for f in plugins.glob("**/.mcp.json"):
            data = store.read_json(f, {})
            servers = data.get("mcpServers", data if all(isinstance(v, dict) for v in data.values()) else {})
            plugin = f.parent.name
            for name, cfg in servers.items():
                if isinstance(cfg, dict):
                    out.append(_entry("plugin", f"{plugin}_{name}", cfg, str(f), {"plugin": plugin}))
    for name, cfg in library().items():
        out.append(_entry("library", name, cfg, str(store.library() / "mcp.json")))
    return out


def _project_settings(cwd: str) -> dict:
    s = {}
    for f in (Path(cwd) / ".claude" / "settings.json", Path(cwd) / ".claude" / "settings.local.json"):
        s.update(store.read_json(f, {}))
    return s


def get(server_id: str, cwd: str = "") -> dict | None:
    return next((s for s in all_servers(cwd) if s["id"] == server_id), None)


# ---- the library (this app's own list) -------------------------------------------------------------------

def library() -> dict:
    return store.read_json(store.library() / "mcp.json", {}).get("mcpServers", {})


def validate(name: str, cfg: dict) -> dict:
    if not NAME_RE.match(name or ""):
        raise ValueError("Server names use letters, digits, - and _ (max 64)")
    t = kind(cfg)
    clean: dict = {}
    if t == "stdio":
        if not str(cfg.get("command", "")).strip():
            raise ValueError("A local (stdio) server needs a command, e.g. npx or python")
        clean = {"command": str(cfg["command"]).strip(), "args": [str(a) for a in cfg.get("args") or []]}
        if cfg.get("env"):
            clean["env"] = {str(k): str(v) for k, v in cfg["env"].items()}
        if cfg.get("cwd"):
            clean["cwd"] = str(cfg["cwd"])
    elif t in ("http", "sse", "ws"):
        url = str(cfg.get("url", "")).strip()
        if not re.match(r"^(https?|wss?)://", url):
            raise ValueError("A remote server needs a full URL (https://…)")
        clean = {"type": t, "url": url}
        if cfg.get("headers"):
            clean["headers"] = {str(k): str(v) for k, v in cfg["headers"].items()}
    else:
        raise ValueError("Give either a command (local server) or a url (remote server)")
    return clean


def save_library(name: str, cfg: dict, description: str = "", old_name: str = "") -> dict:
    clean = validate(name, cfg)
    data = store.read_json(store.library() / "mcp.json", {"mcpServers": {}})
    data.setdefault("mcpServers", {})
    if old_name and old_name != name:
        data["mcpServers"].pop(old_name, None)
    data["mcpServers"][name] = clean
    store.write_json(store.library() / "mcp.json", data)
    meta = store.read_json(store.library() / "mcp_meta.json", {})
    if old_name and old_name != name:
        meta.pop(old_name, None)
    meta[name] = {"description": description}
    store.write_json(store.library() / "mcp_meta.json", meta)
    return _entry("library", name, clean, str(store.library() / "mcp.json"))


def delete_library(name: str) -> bool:
    data = store.read_json(store.library() / "mcp.json", {"mcpServers": {}})
    ok = data.get("mcpServers", {}).pop(name, None) is not None
    store.write_json(store.library() / "mcp.json", data)
    return ok


def import_json(text_or_obj) -> list[str]:
    """Paste a config from a README: {"mcpServers": {...}} or {"name": {...}} or a single server with "name"."""
    import json
    obj = json.loads(text_or_obj) if isinstance(text_or_obj, str) else text_or_obj
    if not isinstance(obj, dict):
        raise ValueError("Paste a JSON object")
    servers = obj.get("mcpServers") or obj.get("servers") or obj
    if "command" in servers or "url" in servers:
        name = servers.get("name")
        if not name:
            raise ValueError("Add a \"name\" to that server")
        servers = {name: {k: v for k, v in servers.items() if k != "name"}}
    added = []
    for name, cfg in servers.items():
        if isinstance(cfg, dict):
            save_library(name, cfg)
            added.append(name)
    if not added:
        raise ValueError("No servers found in that JSON")
    return added


# ---- connecting a server to Claude Code permanently ------------------------------------------------------

def install(name: str, cfg: dict, scope: str, cwd: str = "") -> str:
    """Write a server into Claude Code's own config: 'user' (every project) or 'project' (.mcp.json)."""
    clean = validate(name, cfg)
    if scope == "user":
        path = store.claude_json()
        data = store.read_json(path, {})
        data.setdefault("mcpServers", {})[name] = clean
        store.write_json(path, data, backup=True)
        return str(path)
    if scope == "project":
        if not cwd:
            raise ValueError("Pick the project folder")
        path = project_mcp_file(cwd)
        data = store.read_json(path, {})
        data.setdefault("mcpServers", {})[name] = clean
        store.write_json(path, data, backup=True)
        return str(path)
    raise ValueError("Connect to 'user' (all projects) or 'project' (this folder)")


def uninstall(server: dict, cwd: str = "") -> str:
    name = server["name"]
    if server["scope"] == "user":
        path = store.claude_json()
        data = store.read_json(path, {})
        (data.get("mcpServers") or {}).pop(name, None)
    elif server["scope"] == "local":
        path = store.claude_json()
        data = store.read_json(path, {})
        for p, proj in (data.get("projects") or {}).items():
            if _norm(p) == _norm(cwd):
                (proj.get("mcpServers") or {}).pop(name, None)
    elif server["scope"] == "project":
        path = Path(server["where"])
        data = store.read_json(path, {})
        (data.get("mcpServers") or {}).pop(name, None)
    else:
        raise ValueError("Only user, local and project servers can be disconnected here")
    store.write_json(path, data, backup=True)
    return str(path)
