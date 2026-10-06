import json
import threading
import time

import pytest


def test_chat_flow(client):
    chats = client.get("/api/chats").json()
    sid = next(c["id"] for c in chats if "Instagram" in c["title"])
    assert client.post(f"/api/chats/{sid}/about", json={"about": "Captions"}).json()["about"] == "Captions"
    t = client.get(f"/api/chats/{sid}/tools").json()
    assert t["profile"]["skills"] is None and t["suggested"]["skills"]
    job = client.post(f"/api/chats/{sid}/ask-claude").json()["job"]
    for _ in range(50):
        j = client.get(f"/api/jobs/{job}").json()
        if j["status"] != "running":
            break
        time.sleep(0.05)
    assert j["status"] == "done"
    ids = [s["id"] for s in t["suggested"]["skills"]]
    assert client.post(f"/api/chats/{sid}/tools", json={"skills": ids, "mcp": []}).json()["skills"] == ids
    assert client.post(f"/api/chats/{sid}/tools", json={"skills": "nope"}).status_code == 400
    cmd = client.get(f"/api/chats/{sid}/command").json()
    assert "--strict-mcp-config" in cmd["args"]
    r = client.post(f"/api/chats/{sid}/open", json={}).json()
    assert "Demo" in r["message"]
    assert client.get("/api/chats/does-not-exist").status_code == 404
    assert client.get("/api/chats?q=sourdough").json()[0]["id"] == sid


def test_skill_endpoints(client):
    r = client.post("/api/skills", json={"name": "cap-writer", "description": "Writes captions. Use for captions.",
                                         "body": "Do it"})
    assert r.status_code == 200
    sid = r.json()["id"]
    txt = client.get(f"/api/skills/text?id={sid}").json()["text"]
    assert "cap-writer" in txt
    assert client.post("/api/skills/text", json={"id": sid, "text": "no frontmatter"}).status_code == 400
    j = client.post("/api/skills/draft", json={"request": "captions"}).json()["job"]
    time.sleep(0.3)
    assert client.get(f"/api/jobs/{j}").json()["result"]["name"] == "instagram-captions"
    assert client.post("/api/skills/copy", json={"id": "claude/dataviz"}).status_code == 400


def test_mcp_endpoints(client):
    lst = client.get("/api/mcp").json()
    assert any(s["id"] == "library/bakery-notes" for s in lst)
    assert "demo-token-not-real" not in json.dumps(lst)
    r = client.post("/api/mcp/test", json={"id": "library/bakery-notes"}).json()
    assert r["ok"] and len(r["tools"]) == 2
    out = client.post("/api/mcp/call", json={"id": "library/bakery-notes", "tool": "add_note",
                                             "arguments": {"client": "a", "text": "b"}}).json()
    assert "Saved note" in out["content"][0]["text"]
    assert client.post("/api/mcp/library", json={"name": "x y", "config": {}}).status_code == 400
    r = client.post("/api/mcp/create", json={"name": "t1", "description": "d",
                                             "tools": [{"name": "ping", "description": "p", "body": "return 'pong'"}]})
    assert r.status_code == 200
    assert client.get("/api/mcp/code/t1").json()["code"].count("def ping") == 1
    assert client.post("/api/mcp/install", json={"id": "library/t1", "scope": "user"}).status_code == 200
    assert any(s["id"] == "user/t1" for s in client.get("/api/mcp").json())
    s = client.get("/api/self-mcp").json()
    assert s["config"]["args"] == ["-m", "tctl.mcp_server"] and not s["connected"]
    client.post("/api/self-mcp/connect")
    assert client.get("/api/self-mcp").json()["connected"]


def test_ui_served(client):
    assert client.get("/").status_code == 200 and client.get("/static/app.js").status_code == 200


def test_sdk_against_live_server(demo):
    import uvicorn
    import importlib
    from tctl import main
    importlib.reload(main)
    server = uvicorn.Server(uvicorn.Config(main.app, host="127.0.0.1", port=8461, log_level="error"))
    th = threading.Thread(target=server.run, daemon=True)
    th.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    try:
        from tools_control import ToolsControl, ToolsControlError
        tc = ToolsControl("http://127.0.0.1:8461")
        c = tc.chats("instagram")[0]
        tc.set_about(c["id"], "Bakery captions")
        r = tc.use_suggested(c["id"])
        assert r["skills"] and r["about"] == "Bakery captions"
        res = tc.ask_claude(c["id"])
        assert res["about"]
        opts = tc.agent_options(c["id"])
        assert opts["resume"] == c["id"] and opts["strict_mcp_config"] and "settings" in opts
        assert isinstance(opts["mcp_servers"], dict)
        assert tc.test_mcp("library/bakery-notes")["ok"]
        with pytest.raises(ToolsControlError):
            tc.chat("missing")
        import toolsctl
        assert toolsctl.main(["--url", "http://127.0.0.1:8461", "chats", "bakery"]) == 0
        assert toolsctl.main(["--url", "http://127.0.0.1:8461", "set", c["id"], "--skills", "default"]) == 0
        assert tc.chat(c["id"])["profile"]["skills"] is None
    finally:
        server.should_exit = True
        th.join(timeout=5)
