"""Connect to an MCP server the way Claude Code does and list its tools: the "Test" button.

Speaks MCP's JSON-RPC over stdio (one JSON message per line), Streamable HTTP and the older SSE transport.
Nothing else is called: initialize → initialized → tools/list (and tools/call when you try a tool)."""
import json
import os
import queue
import shutil
import subprocess
import threading
import time

import httpx

PROTOCOL = "2025-06-18"
CLIENT = {"name": "tools-control", "version": "1.0"}


class MCPError(RuntimeError):
    pass


def _init_msg(i=1):
    return {"jsonrpc": "2.0", "id": i, "method": "initialize",
            "params": {"protocolVersion": PROTOCOL, "capabilities": {}, "clientInfo": CLIENT}}


# ---- stdio ---------------------------------------------------------------------------------------------

def _resolve_command(cmd: str, args: list[str]) -> list[str]:
    exe = shutil.which(cmd) or cmd
    if os.name == "nt" and exe.lower().endswith((".cmd", ".bat")):
        return ["cmd", "/c", exe, *args]  # npx, uvx… are .cmd files on Windows
    return [exe, *args]


class StdioSession:
    def __init__(self, cfg: dict, timeout: float = 30):
        env = dict(os.environ)
        env.update({k: str(v) for k, v in (cfg.get("env") or {}).items()})
        kw = {"creationflags": 0x08000000} if os.name == "nt" else {}
        try:
            self.p = subprocess.Popen(_resolve_command(cfg["command"], cfg.get("args") or []), stdin=subprocess.PIPE,
                                      stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, cwd=cfg.get("cwd"),
                                      text=True, encoding="utf-8", errors="replace", bufsize=1, **kw)
        except OSError as e:
            raise MCPError(f"Could not start '{cfg['command']}': {e}") from e
        self.timeout = timeout
        self.q: queue.Queue = queue.Queue()
        self.stderr: list[str] = []
        threading.Thread(target=self._read, daemon=True).start()
        threading.Thread(target=self._read_err, daemon=True).start()
        self.next_id = 1

    def _read(self):
        for line in self.p.stdout:
            line = line.strip()
            if line:
                try:
                    self.q.put(json.loads(line))
                except ValueError:
                    self.stderr.append(f"(not JSON on stdout) {line[:200]}")
        self.q.put(None)

    def _read_err(self):
        for line in self.p.stderr:
            self.stderr.append(line.rstrip())
            del self.stderr[:-40]

    def send(self, msg: dict):
        try:
            self.p.stdin.write(json.dumps(msg) + "\n")
            self.p.stdin.flush()
        except (OSError, ValueError) as e:
            raise MCPError(f"The server closed: {self._err()}") from e

    def _err(self):
        return " | ".join(self.stderr[-5:]) or f"exit code {self.p.poll()}"

    def request(self, method: str, params: dict | None = None) -> dict:
        i = self.next_id = self.next_id + 1
        self.send({"jsonrpc": "2.0", "id": i, "method": method, "params": params or {}})
        end = time.time() + self.timeout
        while time.time() < end:
            try:
                m = self.q.get(timeout=max(0.05, end - time.time()))
            except queue.Empty:
                break
            if m is None:
                raise MCPError(f"The server stopped: {self._err()}")
            if m.get("id") == i:
                if "error" in m:
                    raise MCPError(m["error"].get("message", str(m["error"])))
                return m.get("result", {})
            if "method" in m and "id" in m:  # a request from the server (e.g. roots/list): answer empty
                self.send({"jsonrpc": "2.0", "id": m["id"], "result": {}})
        raise MCPError(f"No answer to {method} within {self.timeout:.0f}s. {self._err()}")

    def notify(self, method: str):
        self.send({"jsonrpc": "2.0", "method": method})

    def close(self):
        try:
            self.p.stdin.close()
            self.p.terminate()
            self.p.wait(timeout=3)
        except Exception:
            try:
                self.p.kill()
            except Exception:
                pass


# ---- Streamable HTTP --------------------------------------------------------------------------------------

def _parse_sse(text: str) -> list[dict]:
    out = []
    data = []
    for line in text.splitlines() + [""]:
        if line.startswith("data:"):
            data.append(line[5:].strip())
        elif not line.strip() and data:
            try:
                out.append(json.loads("\n".join(data)))
            except ValueError:
                pass
            data = []
    return out


class HttpSession:
    def __init__(self, cfg: dict, timeout: float = 30):
        self.url = cfg["url"]
        self.headers = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json",
                        **(cfg.get("headers") or {})}
        self.client = httpx.Client(timeout=timeout, follow_redirects=True)
        self.next_id = 1

    def _post(self, msg: dict) -> list[dict]:
        r = self.client.post(self.url, json=msg, headers=self.headers)
        if r.status_code == 401:
            raise MCPError("401: this server needs you to sign in (OAuth). Connect it in Claude Code with /mcp.")
        if r.status_code >= 400:
            raise MCPError(f"HTTP {r.status_code}: {r.text[:200]}")
        if r.headers.get("mcp-session-id"):
            self.headers["Mcp-Session-Id"] = r.headers["mcp-session-id"]
        if not r.content:
            return []
        if "text/event-stream" in r.headers.get("content-type", ""):
            return _parse_sse(r.text)
        body = r.json()
        return body if isinstance(body, list) else [body]

    def request(self, method: str, params: dict | None = None) -> dict:
        i = self.next_id = self.next_id + 1
        msgs = self._post({"jsonrpc": "2.0", "id": i, "method": method, "params": params or {}})
        for m in msgs:
            if m.get("id") == i:
                if "error" in m:
                    raise MCPError(m["error"].get("message", str(m["error"])))
                return m.get("result", {})
        raise MCPError(f"No answer to {method}")

    def notify(self, method: str):
        self._post({"jsonrpc": "2.0", "method": method})

    def close(self):
        self.client.close()


# ---- the older SSE transport --------------------------------------------------------------------------

class SseSession:
    def __init__(self, cfg: dict, timeout: float = 30):
        self.timeout = timeout
        self.headers = dict(cfg.get("headers") or {})
        self.client = httpx.Client(timeout=None, follow_redirects=True)
        self.q: queue.Queue = queue.Queue()
        self.endpoint = None
        self._ready = threading.Event()
        self.base = cfg["url"]
        threading.Thread(target=self._listen, daemon=True).start()
        if not self._ready.wait(timeout):
            raise MCPError("The SSE server did not send its message endpoint")
        self.next_id = 1

    def _listen(self):
        try:
            with self.client.stream("GET", self.base, headers={"Accept": "text/event-stream", **self.headers}) as r:
                event, data = "message", []
                for line in r.iter_lines():
                    if line.startswith("event:"):
                        event = line[6:].strip()
                    elif line.startswith("data:"):
                        data.append(line[5:].strip())
                    elif not line.strip():
                        payload = "\n".join(data)
                        if event == "endpoint":
                            self.endpoint = str(httpx.URL(self.base).join(payload))
                            self._ready.set()
                        elif payload:
                            try:
                                self.q.put(json.loads(payload))
                            except ValueError:
                                pass
                        event, data = "message", []
        except httpx.HTTPError as e:
            self.q.put({"_error": str(e)})
            self._ready.set()

    def request(self, method: str, params: dict | None = None) -> dict:
        if not self.endpoint:
            raise MCPError("Not connected")
        i = self.next_id = self.next_id + 1
        self.client.post(self.endpoint, json={"jsonrpc": "2.0", "id": i, "method": method, "params": params or {}},
                         headers=self.headers, timeout=self.timeout)
        end = time.time() + self.timeout
        while time.time() < end:
            try:
                m = self.q.get(timeout=max(0.05, end - time.time()))
            except queue.Empty:
                break
            if "_error" in m:
                raise MCPError(m["_error"])
            if m.get("id") == i:
                if "error" in m:
                    raise MCPError(m["error"].get("message", str(m["error"])))
                return m.get("result", {})
        raise MCPError(f"No answer to {method}")

    def notify(self, method: str):
        if self.endpoint:
            self.client.post(self.endpoint, json={"jsonrpc": "2.0", "method": method}, headers=self.headers)

    def close(self):
        self.client.close()


def open_session(cfg: dict, timeout: float = 30):
    t = cfg.get("type") or ("stdio" if cfg.get("command") else "http")
    if t == "stdio":
        return StdioSession(cfg, timeout)
    if t == "http":
        return HttpSession(cfg, timeout)
    if t == "sse":
        return SseSession(cfg, timeout)
    raise MCPError(f"Testing '{t}' servers isn't supported here; Claude Code can still use them")


def probe(cfg: dict, timeout: float = 30) -> dict:
    """Connect, list tools, disconnect. Never raises: the result says what went wrong."""
    t0 = time.time()
    s = None
    try:
        s = open_session(cfg, timeout)
        init = s.request("initialize", _init_msg()["params"])
        s.notify("notifications/initialized")
        tools, cursor = [], None
        for _ in range(20):
            r = s.request("tools/list", {"cursor": cursor} if cursor else {})
            tools += r.get("tools", [])
            cursor = r.get("nextCursor")
            if not cursor:
                break
        return {"ok": True, "server": init.get("serverInfo", {}), "protocol": init.get("protocolVersion"),
                "instructions": (init.get("instructions") or "")[:1500],
                "tools": [{"name": x.get("name"), "description": (x.get("description") or "")[:400],
                           "input": x.get("inputSchema", {})} for x in tools],
                "ms": int((time.time() - t0) * 1000)}
    except (MCPError, httpx.HTTPError, KeyError, ValueError) as e:
        return {"ok": False, "error": str(e), "ms": int((time.time() - t0) * 1000), "tools": []}
    finally:
        if s:
            s.close()


def call_tool(cfg: dict, tool: str, arguments: dict, timeout: float = 60) -> dict:
    s = open_session(cfg, timeout)
    try:
        s.request("initialize", _init_msg()["params"])
        s.notify("notifications/initialized")
        return s.request("tools/call", {"name": tool, "arguments": arguments or {}})
    finally:
        s.close()
