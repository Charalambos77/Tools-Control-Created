"""toolsctl — Tools Control from the command line.

  python toolsctl.py chats [search words]          list chats
  python toolsctl.py show <chat-id>                what it's about + tools on
  python toolsctl.py about <chat-id> "text"        write what it's about
  python toolsctl.py suggest <chat-id> [--claude]  suggested skills / MCP servers
  python toolsctl.py use-suggested <chat-id> [--claude]
  python toolsctl.py set <chat-id> --skills id1,id2 --mcp id3     (use "default" for Claude Code's normal set)
  python toolsctl.py open <chat-id> [--new]        open it in a terminal with its tools
  python toolsctl.py command <chat-id> [--new]     print the command instead
  python toolsctl.py skills | mcp                  list skills / MCP servers
  python toolsctl.py test-mcp <server-id>          connect and list its tools
Chat ids can be shortened to their first characters.
"""
import argparse
import json
import sys

from tools_control import ToolsControl, ToolsControlError


def resolve(tc: ToolsControl, short: str) -> str:
    ids = [c["id"] for c in tc.chats()]
    if short in ids:
        return short
    hits = [i for i in ids if i.startswith(short)]
    if len(hits) != 1:
        raise ToolsControlError(f"{len(hits)} chats start with '{short}'")
    return hits[0]


def main(argv=None):
    p = argparse.ArgumentParser(prog="toolsctl", description="Tools Control from the command line")
    p.add_argument("--url", default="http://127.0.0.1:8450")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("chats"); s.add_argument("query", nargs="*")
    for name in ("show", "suggest", "use-suggested", "open", "command"):
        s = sub.add_parser(name); s.add_argument("chat")
        if name in ("suggest", "use-suggested"):
            s.add_argument("--claude", action="store_true")
        if name in ("open", "command"):
            s.add_argument("--new", action="store_true")
    s = sub.add_parser("about"); s.add_argument("chat"); s.add_argument("text")
    s = sub.add_parser("set"); s.add_argument("chat"); s.add_argument("--skills"); s.add_argument("--mcp")
    sub.add_parser("skills"); sub.add_parser("mcp")
    s = sub.add_parser("test-mcp"); s.add_argument("server")
    a = p.parse_args(argv)
    tc = ToolsControl(a.url)
    try:
        if a.cmd == "chats":
            for c in tc.chats(" ".join(a.query)):
                print(f"{c['id'][:8]}  {c['updated'][:16].replace('T', ' ')}  {c['title'][:70]}")
        elif a.cmd == "skills":
            for x in tc.skills():
                print(f"{x['id']:<45} {x['description'][:70]}")
        elif a.cmd == "mcp":
            for x in tc.mcp_servers():
                print(f"{x['id']:<35} {x['type']:<6} {x['where']}")
        elif a.cmd == "test-mcp":
            r = tc.test_mcp(a.server)
            print(("OK " + ", ".join(t["name"] for t in r["tools"])) if r["ok"] else "FAILED " + r["error"])
        else:
            cid = resolve(tc, a.chat)
            if a.cmd == "show":
                d = tc.chat(cid)
                print(json.dumps({"title": d["info"]["title"], "folder": d["info"]["cwd"], "about": d["profile"]["about"],
                                  "about_by_claude": d["profile"]["about_auto"], "skills_on": d["profile"]["skills"],
                                  "mcp_on": d["profile"]["mcp"]}, indent=2))
            elif a.cmd == "about":
                tc.set_about(cid, a.text); print("Saved.")
            elif a.cmd == "suggest":
                r = tc.ask_claude(cid) if a.claude else tc.tools(cid)["suggested"]
                for x in r["skills"]:
                    print(f"skill  {x['id']:<40} {x['why']}")
                for x in r["mcp"]:
                    print(f"mcp    {x['id']:<40} {x['why']}")
            elif a.cmd == "use-suggested":
                r = tc.use_suggested(cid, ask_claude=a.claude); print("On:", r["skills"], r["mcp"])
            elif a.cmd == "set":
                kw = {}
                if a.skills is not None:
                    kw["skills"] = None if a.skills == "default" else [x for x in a.skills.split(",") if x]
                if a.mcp is not None:
                    kw["mcp"] = None if a.mcp == "default" else [x for x in a.mcp.split(",") if x]
                tc.set_tools(cid, **kw); print("Saved.")
            elif a.cmd == "command":
                print(tc.command(cid, new=a.new)["powershell"])
            elif a.cmd == "open":
                print(tc.open(cid, new=a.new)["message"])
    except ToolsControlError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
