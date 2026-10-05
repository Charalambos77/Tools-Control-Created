"""Find every skill Claude Code can see, plus this app's own library; create and edit skills."""
import json
import re
import shutil
from pathlib import Path

from . import store

NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")


def parse_frontmatter(text: str) -> tuple[dict, str]:
    """Small YAML-frontmatter reader (key: value, quoted values, >- / | blocks, simple lists)."""
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end < 0:
        return {}, text
    head, body = text[3:end].strip("\n"), text[end + 4:].lstrip("\n")
    meta: dict = {}
    lines = head.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        m = re.match(r"^([A-Za-z0-9_-]+):\s*(.*)$", line)
        i += 1
        if not m:
            continue
        key, val = m.group(1), m.group(2).strip()
        if val in (">", ">-", "|", "|-", ">+", "|+", ""):
            block = []
            while i < len(lines) and (lines[i].startswith((" ", "\t")) or not lines[i].strip()):
                block.append(lines[i].strip())
                i += 1
            if block and all(b.startswith("- ") or not b for b in block) and val == "":
                meta[key] = [b[2:].strip().strip("\"'") for b in block if b]
            else:
                meta[key] = ("\n" if val.startswith("|") else " ").join(b for b in block).strip()
            continue
        if val.startswith("[") and val.endswith("]"):
            meta[key] = [x.strip().strip("\"'") for x in val[1:-1].split(",") if x.strip()]
        elif len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
            meta[key] = val[1:-1]
        elif val.lower() in ("true", "false"):
            meta[key] = val.lower() == "true"
        else:
            meta[key] = val
    return meta, body


def _read_skill(md: Path, source: str, plugin: str = "", enabled: bool = True) -> dict | None:
    try:
        text = md.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    meta, body = parse_frontmatter(text)
    folder = md.parent.name
    name = str(meta.get("name") or folder)
    # Claude Code names a skill by its folder (checked: frontmatter name is not used for the key)
    invoke = f"{plugin}:{folder}" if plugin else folder
    return {
        "id": f"{source}{':' + plugin if plugin else ''}/{folder}",
        "name": name,
        "invoke": invoke,                       # what the Skill tool / slash command uses
        "folder": folder,
        "description": str(meta.get("description", ""))[:1200],
        "source": source,                       # personal | project | plugin | library
        "plugin": plugin,
        "enabled": enabled,                     # plugin skills: is the plugin switched on
        "path": str(md.parent),
        "user_only": bool(meta.get("disable-model-invocation")),
        "meta": {k: v for k, v in meta.items() if k not in ("name", "description")},
        "size": len(text),
    }


def _plugin_name(skill_dir: Path) -> str:
    for p in [skill_dir, *skill_dir.parents][:6]:
        pj = p / ".claude-plugin" / "plugin.json"
        if pj.exists():
            return str(store.read_json(pj, {}).get("name") or p.name)
    return skill_dir.parent.parent.name


def enabled_plugins() -> dict:
    s = store.read_json(store.claude_dir() / "settings.json", {})
    return s.get("enabledPlugins") or {}


def _scan(root: Path, source: str, out: dict, plugin_mode: bool = False) -> None:
    if not root.is_dir():
        return
    pattern = "**/skills/*/SKILL.md" if plugin_mode else "*/SKILL.md"
    flags = enabled_plugins() if plugin_mode else {}
    for md in sorted(root.glob(pattern)):
        plugin = _plugin_name(md.parent.parent.parent) if plugin_mode else ""
        enabled = True
        if plugin_mode and flags:
            enabled = any(v for k, v in flags.items() if k.split("@")[0] == plugin)
        s = _read_skill(md, source, plugin, enabled)
        if s and s["id"] not in out:
            out[s["id"]] = s


def project_skill_dirs(cwd: str) -> list[Path]:
    """.claude/skills in the chat's folder and its parents (stopping at the home folder)."""
    if not cwd:
        return []
    p = Path(cwd)
    out = []
    home = store.home().resolve() if store.home().exists() else store.home()
    for d in [p, *p.parents]:
        out.append(d / ".claude" / "skills")
        try:
            if d.resolve() == home:
                break
        except OSError:
            break
    return out


SOURCES = ["personal", "project", "plugin", "claude", "library"]


def claude_seen_path() -> Path:
    return store.DATA / "claude_skills.json"


def claude_seen() -> dict:
    """The skills Claude itself reported (built-in, plugin and synced ones that are not files on this PC)."""
    return store.read_json(claude_seen_path(), {"checked": None, "skills": []})


def all_skills(cwd: str = "") -> list[dict]:
    out: dict[str, dict] = {}
    _scan(store.claude_dir() / "skills", "personal", out)
    for d in project_skill_dirs(cwd):
        if d.resolve() != (store.claude_dir() / "skills").resolve():
            _scan(d, "project", out)
    _scan(store.claude_dir() / "plugins", "plugin", out, plugin_mode=True)
    _scan(store.library() / "skills", "library", out)
    by_invoke = {s["invoke"]: s for s in out.values() if s["source"] != "library"}
    for c in claude_seen().get("skills", []):
        name = str(c.get("name", "")).lstrip("/")
        if not name:
            continue
        if name in by_invoke:
            by_invoke[name]["seen_by_claude"] = True
            continue
        plugin = name.split(":")[0] if ":" in name else ""
        out[f"claude/{name}"] = {
            "id": f"claude/{name}", "name": name, "invoke": name, "folder": name.split(":")[-1],
            "description": str(c.get("description", ""))[:1200], "source": "claude", "plugin": plugin,
            "enabled": True, "path": "", "user_only": False, "meta": {}, "size": 0, "seen_by_claude": True}
    return sorted(out.values(), key=lambda s: (SOURCES.index(s["source"]), s["invoke"]))


def get(skill_id: str, cwd: str = "") -> dict | None:
    return next((s for s in all_skills(cwd) if s["id"] == skill_id), None)


def read_text(skill: dict) -> str:
    return (Path(skill["path"]) / "SKILL.md").read_text(encoding="utf-8", errors="replace")


def render(name: str, description: str, body: str, extra: dict | None = None) -> str:
    fm = [f"name: {name}", f"description: {json.dumps(description, ensure_ascii=False)}"]
    for k, v in (extra or {}).items():
        if v in (None, "", []):
            continue
        fm.append(f"{k}: {json.dumps(v) if isinstance(v, (list, bool)) else v}")
    return "---\n" + "\n".join(fm) + "\n---\n\n" + body.strip() + "\n"


def _target(scope: str, cwd: str = "") -> Path:
    if scope == "library":
        return store.library() / "skills"
    if scope == "personal":
        return store.claude_dir() / "skills"
    if scope == "project":
        if not cwd:
            raise ValueError("A project skill needs the project folder")
        return Path(cwd) / ".claude" / "skills"
    raise ValueError(f"Unknown place {scope}")


def save(name: str, description: str, body: str, scope: str = "library", cwd: str = "",
         extra: dict | None = None, overwrite: bool = False) -> dict:
    name = name.strip().lower()
    if not NAME_RE.match(name):
        raise ValueError("Skill names use lowercase letters, digits and hyphens (max 64)")
    if not description.strip():
        raise ValueError("A description is needed: it is how Claude decides when to use the skill")
    d = _target(scope, cwd) / name
    if d.exists() and not overwrite:
        raise ValueError(f"A skill called {name} already exists there")
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(render(name, description.strip(), body, extra), encoding="utf-8")
    return _read_skill(d / "SKILL.md", scope)


def write_text(skill: dict, text: str) -> dict:
    if skill["source"] in ("plugin", "claude"):
        raise ValueError("Plugin skills are managed by their plugin; copy it to your library to change it")
    meta, _ = parse_frontmatter(text)
    if not meta.get("description"):
        raise ValueError("The file needs a frontmatter block with a description")
    (Path(skill["path"]) / "SKILL.md").write_text(text, encoding="utf-8")
    return _read_skill(Path(skill["path"]) / "SKILL.md", skill["source"], skill["plugin"])


def copy(skill: dict, scope: str, cwd: str = "") -> dict:
    """Copy a skill (whole folder: scripts, references) to the library, personal or a project."""
    if not skill.get("path"):
        raise ValueError("This skill lives inside Claude Code (no file on this PC) and can't be copied")
    dest = _target(scope, cwd) / skill["folder"]
    if dest.exists():
        raise ValueError(f"{skill['folder']} already exists there")
    shutil.copytree(skill["path"], dest)
    return _read_skill(dest / "SKILL.md", scope)


def delete(skill: dict) -> None:
    if skill["source"] not in ("library", "personal", "project"):
        raise ValueError("Only your own skills can be deleted here")
    trash = store.DATA / "trash" / "skills"
    trash.mkdir(parents=True, exist_ok=True)
    dest = trash / f"{skill['folder']}-{skill['source']}"
    if dest.exists():
        shutil.rmtree(dest)
    shutil.move(skill["path"], dest)  # recoverable from data/trash
