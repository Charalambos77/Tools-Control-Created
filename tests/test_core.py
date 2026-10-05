import json

import pytest

from tctl import create, launch, mcp, mcp_client, sessions, skills, store, suggest


def chat(title):
    return next(s for s in sessions.list_sessions() if title in s["title"])


def test_reads_chats(demo):
    rows = sessions.list_sessions()
    assert len(rows) == 5 and rows[0]["updated"] >= rows[-1]["updated"]
    c = chat("Instagram")
    assert c["prompts"] == 2 and c["skills_used"] == ["brand-voice", "seo-audit"]
    assert sessions.list_sessions("sourdough")[0]["id"] == c["id"]
    m = sessions.messages(c["id"])
    assert [x["role"] for x in m["items"]] == ["you", "claude", "you", "claude"]
    assert "Skill: brand-voice" in m["items"][1]["tools"]
    r = chat("competitors")
    assert r["mcp_used"] == ["playwright"]


def test_prompt_cleaning():
    t = sessions.clean_prompt("<system-reminder>x</system-reminder>hi")
    assert t == "hi"
    assert sessions.clean_prompt("<command-name>/review</command-name><command-args>12</command-args>") == "/review 12"
    assert sessions.encode_cwd("C:\\Users\\Harry\\my.app") == "C--Users-Harry-my-app"


def test_bad_lines_are_skipped(demo, tmp_path):
    folder = store.claude_dir() / "projects" / "x"
    folder.mkdir(parents=True)
    (folder / "abc.jsonl").write_text('not json\n{"type":"user","message":{"content":"hello there"},'
                                      '"cwd":"/x","timestamp":"2026-10-01T00:00:00Z"}\n')
    assert any(s["id"] == "abc" for s in sessions.list_sessions())


def test_skill_discovery(demo):
    cwd = chat("Instagram")["cwd"]
    all_ = {s["invoke"]: s for s in skills.all_skills(cwd)}
    assert all_["brand-voice"]["source"] == "personal"
    assert all_["agency-step-runner"]["source"] == "project"
    assert all_["document-skills:pdf"]["source"] == "plugin" and all_["document-skills:pdf"]["enabled"]
    assert all_["code-review"]["source"] == "claude"
    assert "agency-step-runner" not in {s["invoke"] for s in skills.all_skills("")}


def test_frontmatter():
    meta, body = skills.parse_frontmatter("---\nname: a\ndescription: >-\n  two\n  lines\ntags:\n  - x\n  - y\n"
                                          "disable-model-invocation: true\n---\nBody")
    assert meta == {"name": "a", "description": "two lines", "tags": ["x", "y"], "disable-model-invocation": True}
    assert body == "Body"


def test_create_and_edit_skill(demo):
    s = skills.save("my-skill", "Does things. Use when testing.", "Steps")
    assert s["source"] == "library"
    with pytest.raises(ValueError):
        skills.save("my-skill", "x", "y")
    with pytest.raises(ValueError):
        skills.save("Bad Name", "x", "y")
    s2 = skills.write_text(skills.get(s["id"]), "---\nname: my-skill\ndescription: Changed\n---\nNew")
    assert s2["description"] == "Changed"
    skills.delete(skills.get(s["id"]))
    assert not skills.get(s["id"]) and (store.DATA / "trash" / "skills").exists()


def test_mcp_discovery_and_mask(demo):
    cwd = chat("Instagram")["cwd"]
    ids = {s["id"]: s for s in mcp.all_servers(cwd)}
    assert {"user/github", "user/playwright", "local/agency", "project/supabase", "library/bakery-notes"} <= set(ids)
    assert ids["project/supabase"]["approved"] is False
    masked = mcp.mask(ids["user/github"]["config"])
    assert "ghp_demo" not in json.dumps(masked) and masked["headers"]["Authorization"].endswith("1234")


def test_mcp_library_import_install(demo):
    added = mcp.import_json('{"mcpServers": {"fetch": {"command": "uvx", "args": ["mcp-server-fetch"]}}}')
    assert added == ["fetch"]
    with pytest.raises(ValueError):
        mcp.save_library("bad name!", {"command": "x"})
    with pytest.raises(ValueError):
        mcp.save_library("x", {"url": "ftp://nope"})
    path = mcp.install("fetch", mcp.library()["fetch"], "user")
    cj = store.read_json(path, {})
    assert cj["mcpServers"]["fetch"]["command"] == "uvx" and "github" in cj["mcpServers"]
    assert (store.home() / ".claude.json.tools-control.bak").exists()
    mcp.uninstall(mcp.get("user/fetch"))
    assert "fetch" not in store.read_json(path, {})["mcpServers"]


def test_created_server_works_over_stdio(demo):
    r = create.create_server("calc", "Maths", [
        {"name": "add", "description": "Add", "params": [{"name": "a", "type": "number"}, {"name": "b", "type": "number"}],
         "body": "return a + b"},
        {"name": "todo_tool", "description": "Not written yet", "params": []}])
    cfg = r["server"]["config"]
    p = mcp_client.probe(cfg)
    assert p["ok"] and [t["name"] for t in p["tools"]] == ["add", "todo_tool"]
    assert p["tools"][0]["input"]["required"] == ["a", "b"]
    out = mcp_client.call_tool(cfg, "add", {"a": 2, "b": 3})
    assert out["content"][0]["text"] == "5" and not out["isError"]
    assert "TODO" in mcp_client.call_tool(cfg, "todo_tool", {})["content"][0]["text"]
    with pytest.raises(ValueError):
        create.create_server("calc", "again", [{"name": "x", "description": "y"}])
    with pytest.raises(ValueError):
        create.create_server("c2", "bad", [{"name": "not valid", "description": "y"}])
    with pytest.raises(SyntaxError):
        create.save_server_code("calc", "def broken(:\n")


def test_probe_reports_failures(demo):
    r = mcp_client.probe({"command": "definitely-not-a-command-xyz"})
    assert not r["ok"] and "Could not start" in r["error"]
    r = mcp_client.probe({"command": "python3", "args": ["-c", "import sys; sys.exit(3)"]}, timeout=5)
    assert not r["ok"]


def test_fastmcp_template_is_valid_python(demo):
    create.create_server("fm", "FastMCP one", [{"name": "hi", "description": "Say hi",
                                                "params": [{"name": "who", "type": "string"}]}], template="fastmcp")
    code = create.server_code("fm")["code"]
    compile(code, "server.py", "exec")
    assert "FastMCP" in code and (create.servers_dir() / "fm" / "requirements.txt").exists()


def test_local_suggestions(demo):
    r = suggest.local(chat("Instagram")["id"])
    names = [x["invoke"] for x in r["skills"]]
    assert names[:2] == ["brand-voice", "seo-audit"]
    assert "document-skills:pdf" not in names
    v = suggest.local(chat("video render")["id"])
    assert v["skills"][0]["invoke"] == "video-editing"
    c = suggest.local(chat("competitors")["id"])
    assert c["mcp"][0]["name"] == "playwright"


def test_ask_claude_demo(demo):
    sid = chat("Instagram")["id"]
    r = suggest.ask_claude(sid)
    assert r["about"] and all("id" in x for x in r["skills"])
    assert store.get_profile(sid)["about_auto"] == r["about"]


def test_launch_files(demo):
    c = chat("Instagram")
    sid = c["id"]
    lib = skills.save("lib-skill", "Library only. Use in tests.", "x")
    store.save_profile(sid, skills=["personal/brand-voice", lib["id"], "claude/dataviz"],
                       mcp=["library/bakery-notes", "user/github", "gone/server"])
    cmd = launch.command(sid)
    a = cmd["args"]
    assert a[:2] == ["--resume", sid] and "--strict-mcp-config" in a
    settings = store.read_json(a[a.index("--settings") + 1], {})
    off = settings["skillOverrides"]
    assert off["seo-audit"] == "off" and off["document-skills:pdf"] == "off" and off["code-review"] == "off"
    assert "brand-voice" not in off and "dataviz" not in off and "lib-skill" not in off
    add = a[a.index("--add-dir") + 1]
    assert (store.DATA / "chats" / sid / "skills" / ".claude" / "skills" / "lib-skill" / "SKILL.md").exists()
    assert add.endswith("skills")
    m = store.read_json(a[a.index("--mcp-config") + 1], {})["mcpServers"]
    assert set(m) == {"bakery-notes", "github"}
    assert m["github"]["headers"]["Authorization"] == "Bearer ghp_demo_token_1234"  # real value, not masked
    assert any("no longer exists" in n for n in cmd["notes"])
    assert cmd["powershell"].startswith("Set-Location ") and "--resume" in cmd["shell"]


def test_launch_normal_and_new(demo):
    sid = chat("CRM")["id"]
    cmd = launch.command(sid)
    assert cmd["args"] == ["--resume", sid]  # nothing chosen = Claude Code as usual
    store.save_profile(sid, skills=["personal/tracking-links"])
    new = launch.command(sid, new=True)
    assert new["args"][0] == "--session-id" and new["session_id"] != sid
    assert store.get_profile(new["session_id"])["skills"] == ["personal/tracking-links"]


def test_apply_to_project(demo):
    c = chat("CRM")
    store.save_profile(c["id"], skills=["personal/tracking-links"])
    path = launch.apply_to_project(c["id"])
    over = store.read_json(path, {})["skillOverrides"]
    assert "tracking-links" not in over and over["brand-voice"] == "off"


def test_self_mcp_server(demo):
    import sys
    cfg = {"command": sys.executable, "args": ["-m", "tctl.mcp_server"], "cwd": str(store.APP),
           "env": {"TC_DEMO": "1", "TC_DATA": str(store.DATA)}}
    p = mcp_client.probe(cfg)
    assert p["ok"] and "set_conversation_tools" in [t["name"] for t in p["tools"]]
    sid = chat("Instagram")["id"]
    r = mcp_client.call_tool(cfg, "set_conversation_tools", {"session_id": sid, "skills": ["personal/brand-voice"]})
    assert not r["isError"]
    assert store.get_profile(sid)["skills"] == ["personal/brand-voice"]
    d = json.loads(mcp_client.call_tool(cfg, "conversation_details", {"session_id": sid})["content"][0]["text"])
    assert d["skills_on"] == ["personal/brand-voice"]
