"""Which skills and MCP servers fit a chat: an instant local match, and a deeper one from Claude."""
import math
import re
from collections import Counter

from . import claude_run, mcp, sessions, skills, store

STOP = set("""a about above after again all also am an and any are as at be because been before being below between
both but by can could did do does doing done down during each few for from further had has have having he her here
hers him his how i if in into is it its itself just me more most my no nor not now of off on once only or other our
out over own same she should so some such than that the their them then there these they this those through to too
under until up very was we were what when where which while who whom why will with would you your yours use used using
when user users claude skill skills want wants make makes need needs like get also please thanks ok yes let lets
going go one two new work working file files code app apps thing things way something create created look
read check edit add find list show text done here change changed why run make give put take keep start see""".split())


def _stem(w: str) -> str:
    for suf in ("ings", "ing", "ers", "er", "ies", "es", "ed", "ly", "s"):
        if len(w) > len(suf) + 3 and w.endswith(suf):
            return w[: -len(suf)] + ("y" if suf == "ies" else "")
    return w


def terms(text: str) -> Counter:
    words = re.findall(r"[a-z][a-z0-9+#.]{2,}", (text or "").lower())
    return Counter(_stem(w.strip(".")) for w in words if w not in STOP and not w.isdigit())


def chat_text(info: dict, prof: dict) -> str:
    return "\n".join([prof.get("about") or "", prof.get("about_auto") or "", info.get("title") or "",
                      info.get("text_sample") or ""])


def local(session_id: str, limit: int = 8) -> dict:
    info = sessions.get(session_id)
    if not info:
        raise ValueError("Chat not found")
    prof = store.get_profile(session_id)
    text = chat_text(info, prof)
    ct = terms(text)
    low = text.lower()
    all_sk = skills.all_skills(info["cwd"])
    docs = [terms(f"{s['invoke'].replace('-', ' ').replace(':', ' ')} {s['description']}") for s in all_sk]
    df = Counter(t for d in docs for t in set(d))
    n = max(len(docs), 1)
    out_sk = []
    used = set(info.get("skills_used") or [])
    for s, d in zip(all_sk, docs):
        score, hits = 0.0, []
        for t in set(d):
            if t in ct:
                w = math.log(1 + n / (1 + df[t])) * (1 + math.log(ct[t]))
                score += w
                hits.append((w, t))
        reasons = []
        if s["invoke"] in used or s["folder"] in used:
            score += 25
            reasons.append("used in this chat")
        bare = s["folder"].replace("-", " ")
        if len(bare) > 3 and (bare in low or s["folder"] in low):
            score += 6
            reasons.append(f"“{s['folder']}” is mentioned")
        score /= math.sqrt(max(len(d), 4)) / 2
        if hits:
            reasons.append("matches: " + ", ".join(t for _, t in sorted(hits, reverse=True)[:4]))
        strong = any(r.startswith(("used", "“")) for r in reasons)
        if score > 2.6 or (strong and score > 0):
            out_sk.append({"id": s["id"], "invoke": s["invoke"], "score": round(score, 2), "why": "; ".join(reasons),
                           "source": s["source"]})
    out_sk.sort(key=lambda x: -x["score"])

    out_mcp = []
    used_mcp = set(info.get("mcp_used") or [])
    for srv in mcp.all_servers(info["cwd"]):
        score, reasons = 0.0, []
        if srv["name"] in used_mcp:
            score += 25
            reasons.append(f"its tools were used {sum(v for k, v in info['tools'].items() if k == 'mcp:' + srv['name'])}× in this chat")
        name_words = [w for w in re.split(r"[-_]", srv["name"].lower()) if len(w) > 2 and w not in ("mcp", "server")]
        hit = [w for w in name_words if _stem(w) in ct]
        if hit:
            score += 4 * len(hit)
            reasons.append("mentioned: " + ", ".join(hit))
        dt = terms(srv.get("description", ""))
        common = [t for t in dt if t in ct]
        if common:
            score += len(common) * 0.8
            reasons.append("matches: " + ", ".join(common[:4]))
        if score >= 3:
            out_mcp.append({"id": srv["id"], "name": srv["name"], "score": round(score, 2), "why": "; ".join(reasons)})
    out_mcp.sort(key=lambda x: -x["score"])
    return {"skills": out_sk[:limit], "mcp": out_mcp[:limit]}


AI_SCHEMA = {
    "type": "object",
    "properties": {
        "about": {"type": "string", "description": "2-4 plain sentences: what this chat is about and where it stands"},
        "skills": {"type": "array", "items": {"type": "object", "properties": {
            "name": {"type": "string"}, "why": {"type": "string"}}, "required": ["name", "why"]}},
        "mcp": {"type": "array", "items": {"type": "object", "properties": {
            "name": {"type": "string"}, "why": {"type": "string"}}, "required": ["name", "why"]}},
        "missing": {"type": "array", "items": {"type": "string"},
                    "description": "Tools this chat would need that are not in the lists (short phrases)"},
    },
    "required": ["about", "skills", "mcp", "missing"],
}


def ask_claude(session_id: str) -> dict:
    info = sessions.get(session_id)
    if not info:
        raise ValueError("Chat not found")
    prof = store.get_profile(session_id)
    sk = skills.all_skills(info["cwd"])
    servers = mcp.all_servers(info["cwd"])
    msgs = sessions.messages(session_id, offset=-14, limit=14)["items"]
    recent = "\n".join(f"{m['role'].upper()}: {m['text'][:700]}" for m in msgs if m["text"])
    prompt = f"""You help choose which Claude Code skills and MCP servers to switch on for ONE conversation.

Conversation title: {info['title']}
Project folder: {info['cwd']}
What the owner says it is about: {prof.get('about') or '(not written)'}
Tools it already used: {', '.join(f'{k} ×{v}' for k, v in list(info['tools'].items())[:20]) or 'none'}

First requests in the chat:
{info['text_sample'][:5000]}

Most recent exchanges:
{recent[:5000]}

AVAILABLE SKILLS (name: description):
{chr(10).join(f"- {s['invoke']}: {s['description'][:220]}" for s in sk) or '(none)'}

AVAILABLE MCP SERVERS (name: type, description):
{chr(10).join(f"- {s['name']}: {s['type']} {s.get('description', '')[:160]}" for s in servers) or '(none)'}

Return:
- about: what the chat is about and where it stands, in plain words for a non-technical owner.
- skills: the skills from the list worth having ON for this chat (exact names), most useful first, each with a short why.
  Leave out skills that don't fit — fewer, relevant skills keep Claude focused.
- mcp: the MCP servers from the list worth having ON (exact names), each with a short why.
- missing: kinds of tools this chat would benefit from that are not available (may be empty)."""
    res = claude_run.ask(prompt, AI_SCHEMA, cwd=None)
    known_sk = {s["invoke"]: s["id"] for s in sk}
    known_mcp = {s["name"]: s["id"] for s in servers}
    res["skills"] = [dict(x, id=known_sk[x["name"]]) for x in res.get("skills", []) if x.get("name") in known_sk]
    res["mcp"] = [dict(x, id=known_mcp[x["name"]]) for x in res.get("mcp", []) if x.get("name") in known_mcp]
    store.save_profile(session_id, about_auto=res.get("about", ""), ai_suggestions=res)
    return res


SKILLS_SCHEMA = {"type": "object", "properties": {"skills": {"type": "array", "items": {
    "type": "object", "properties": {"name": {"type": "string"}, "description": {"type": "string"}},
    "required": ["name", "description"]}}}, "required": ["skills"]}


def detect_claude_skills(cwd: str = "") -> dict:
    """Ask Claude which skills it can see (includes built-in and plugin skills that aren't files on this PC)."""
    res = claude_run.ask("List every skill in your available-skills list: the exact name you would pass to the "
                         "Skill tool, and its description (shortened to one sentence). Include all of them.",
                         SKILLS_SCHEMA, cwd=cwd or None, tools="Skill")
    import time
    data = {"checked": time.strftime("%Y-%m-%d %H:%M"), "cwd": cwd, "skills": res.get("skills", [])}
    store.write_json(skills.claude_seen_path(), data)
    return data
