"""Demo mode (TC_DEMO=1): a pretend ~/.claude with chats, skills, a plugin and MCP servers, and a pretend Claude,
so the whole app can be tried (and tested) without touching your real Claude Code setup."""
import json
import re
import uuid
from pathlib import Path

from . import store

CHATS = [
    ("Build the CRM page for the agency app", "Desktop/marketing-agency", [
        ("Add a CRM page to the agency app: leads table, CSV import, win rate by source.", ["Read", "Edit", "Bash"]),
        ("Also push it to GitHub and open a pull request.", ["mcp__github__create_pull_request", "Bash"]),
    ]),
    ("Instagram captions for Demo Bakery", "Desktop/marketing-agency", [
        ("Write 10 Instagram captions for Demo Bakery's sourdough launch in the brand voice, with hashtags.",
         ["Skill:brand-voice", "Read"]),
        ("Check them for SEO keywords for 'sourdough near me' and make them sound less like AI.", ["Skill:seo-audit"]),
    ]),
    ("Research competitors of the bakery", "Desktop/marketing-agency", [
        ("Research the 5 closest competitor bakeries: websites, prices, Instagram and Google reviews.",
         ["WebFetch", "mcp__playwright__browser_navigate", "mcp__playwright__browser_snapshot"]),
        ("Put the comparison in a spreadsheet.", ["Skill:document-skills:xlsx"]),
    ]),
    ("Fix the video render that freezes", "Desktop/video-creation-app", [
        ("The ffmpeg render freezes at 80% on the 9:16 export. Find out why and fix it.", ["Bash", "Read", "Edit"]),
        ("Add captions burned in with the brand font.", ["Skill:video-editing", "Bash"]),
    ]),
    ("Monthly report for Demo Bakery", "Desktop/marketing-agency", [
        ("Make the September report for Demo Bakery as a PDF: reach, leads by source, best posts, next steps.",
         ["Skill:client-report", "Skill:document-skills:pdf"]),
    ]),
]

SKILLS = {
    "brand-voice": "Write in a client's brand voice from their voice guide. Use when writing captions, ads or posts for a client.",
    "seo-audit": "Audit a page or text for SEO: keywords, titles, meta, local search. Use for SEO checks and keyword research.",
    "video-editing": "Edit videos with ffmpeg: cut, captions, music, aspect ratios. Use for any video editing or render problem.",
    "tracking-links": "Build UTM tracking links from the agency ID scheme. Use when making links for posts, ads or emails.",
    "client-report": "Build a client's monthly marketing report from the CRM and analytics. Use for monthly or campaign reports.",
}
PLUGIN_SKILLS = {
    "pdf": "Create, read and edit PDF files. Use whenever a PDF is involved.",
    "xlsx": "Create and edit spreadsheets (.xlsx, .csv). Use when a spreadsheet is the input or output.",
    "pptx": "Create and edit PowerPoint decks. Use for slides and presentations.",
}
BUILTIN = [("code-review", "Review a diff for bugs."), ("simplify", "Clean up changed code."),
           ("dataviz", "Make charts and dashboards that look right."), ("loop", "Run a prompt on an interval.")]


def _skill(dirpath: Path, name: str, desc: str):
    (dirpath / name).mkdir(parents=True, exist_ok=True)
    (dirpath / name / "SKILL.md").write_text(f"---\nname: {name}\ndescription: {desc}\n---\n\n# {name}\n\n1. Read the brief.\n"
                                             f"2. Do the work.\n3. Check it against the rules.\n", encoding="utf-8")


def ensure() -> None:
    home = store.home()
    if (home / ".demo-ready").exists():
        return
    cd = home / ".claude"
    for i, (title, rel, turns) in enumerate(CHATS):
        cwd = str(home / rel)
        Path(cwd).mkdir(parents=True, exist_ok=True)
        folder = cd / "projects" / re.sub(r"[^A-Za-z0-9-]", "-", cwd)
        folder.mkdir(parents=True, exist_ok=True)
        sid = str(uuid.UUID(int=0x5EED0000 + i))
        lines = []
        t = 0
        for prompt, tools in turns:
            t += 1
            ts = f"2026-10-0{1 + i}T0{t}:1{i}:00.000Z"
            lines.append({"type": "user", "sessionId": sid, "cwd": cwd, "gitBranch": "main", "timestamp": ts,
                          "message": {"role": "user", "content": prompt}, "uuid": str(uuid.uuid4())})
            content = []
            for tool in tools:
                if tool.startswith("Skill:"):
                    content.append({"type": "tool_use", "id": "t", "name": "Skill", "input": {"skill": tool[6:]}})
                else:
                    content.append({"type": "tool_use", "id": "t", "name": tool, "input": {}})
            content.append({"type": "text", "text": f"Done: {prompt.split('.')[0].lower()}. Here is what I changed and why."})
            lines.append({"type": "assistant", "sessionId": sid, "cwd": cwd, "timestamp": ts,
                          "message": {"role": "assistant", "model": "claude-sonnet-5-5", "content": content}})
        lines.append({"type": "summary", "summary": title, "leafUuid": "x"})
        (folder / f"{sid}.jsonl").write_text("\n".join(json.dumps(x) for x in lines) + "\n", encoding="utf-8")
    for n, d in SKILLS.items():
        _skill(cd / "skills", n, d)
    plug = cd / "plugins" / "marketplaces" / "anthropic-agent-skills" / "document-skills"
    (plug / ".claude-plugin").mkdir(parents=True, exist_ok=True)
    (plug / ".claude-plugin" / "plugin.json").write_text(json.dumps({"name": "document-skills", "version": "1.0.0"}))
    for n, d in PLUGIN_SKILLS.items():
        _skill(plug / "skills", n, d)
    store.write_json(cd / "settings.json", {"enabledPlugins": {"document-skills@anthropic-agent-skills": True}})
    proj = home / "Desktop" / "marketing-agency"
    _skill(proj / ".claude" / "skills", "agency-step-runner", "Run one of the agency's 7 process steps for a client. "
           "Use when asked to run a step for a client.")
    store.write_json(home / ".claude.json", {
        "mcpServers": {
            "github": {"type": "http", "url": "https://api.githubcopilot.com/mcp/",
                       "headers": {"Authorization": "Bearer ghp_demo_token_1234"}},
            "playwright": {"command": "npx", "args": ["@playwright/mcp@latest"]},
        },
        "projects": {str(proj).replace("\\", "/"): {"mcpServers": {
            "agency": {"command": "python", "args": ["-m", "agency_mcp"]}}}}})
    store.write_json(proj / ".mcp.json", {"mcpServers": {"supabase": {"type": "http", "url": "https://mcp.supabase.com/mcp"}}})
    store.write_json(store.DATA / "claude_skills.json", {"checked": "demo", "skills": [
        {"name": n, "description": d} for n, d in BUILTIN]})
    from . import create
    if not (create.servers_dir() / "bakery-notes").exists():
        create.create_server("bakery-notes", "Keep quick notes about clients.", [
            {"name": "add_note", "description": "Save a note about a client", "params": [
                {"name": "client", "type": "string"}, {"name": "text", "type": "string"}],
             "body": "import json, pathlib\np = pathlib.Path(__file__).with_name('notes.json')\n"
                     "notes = json.loads(p.read_text()) if p.exists() else []\nnotes.append({'client': client, 'text': text})\n"
                     "p.write_text(json.dumps(notes))\nreturn f'Saved note {len(notes)} for {client}.'"},
            {"name": "list_notes", "description": "List the notes about a client", "params": [
                {"name": "client", "type": "string"}],
             "body": "import json, pathlib\np = pathlib.Path(__file__).with_name('notes.json')\n"
                     "notes = json.loads(p.read_text()) if p.exists() else []\n"
                     "return [n['text'] for n in notes if n['client'] == client] or 'No notes yet.'"},
        ])
    (home / ".demo-ready").write_text("ok")


def fake_claude(prompt: str, schema: dict | None):
    """Plausible answers without calling Claude (demo and tests)."""
    if not schema:
        return "Demo: the tools now do what their descriptions say."
    props = schema.get("properties", {})
    if "about" in props:
        listed_sk = re.findall(r"^- ([\w:.-]+): ", prompt.split("AVAILABLE SKILLS")[1].split("AVAILABLE MCP")[0], re.M)
        listed_mcp = re.findall(r"^- ([\w.-]+): ", prompt.split("AVAILABLE MCP SERVERS")[1], re.M)
        first = prompt.split("First requests in the chat:")[1].split("Most recent")[0].lower()
        pick = [n for n in listed_sk if any(w in first for w in re.split(r"[-:]", n) if len(w) > 3)]
        pick_mcp = [n for n in listed_mcp if n.lower() in first or n in prompt.split("Tools it already used:")[1][:300]]
        title = prompt.split("Conversation title:")[1].split("\n")[0].strip()
        return {"about": f"{title}. Demo summary: Claude read the chat and this is what it is working on.",
                "skills": [{"name": n, "why": "fits what the chat asks for"} for n in pick[:5]],
                "mcp": [{"name": n, "why": "the chat works with it"} for n in pick_mcp[:3]],
                "missing": ["a tool to post to Instagram directly"] if "instagram" in first else []}
    if "body" in props:
        return {"name": "instagram-captions", "description": "Write Instagram captions in the client's voice with "
                "hashtags and a call to action. Use when asked for captions or social posts.",
                "body": "# Instagram captions\n\n1. Read the client's voice guide.\n2. Write the hook first.\n"
                        "3. Add 3-5 hashtags.\n4. End with one call to action.\n"}
    if "skills" in props:
        return {"skills": [{"name": n, "description": d} for n, d in BUILTIN]}
    return {}
