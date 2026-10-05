"""A tiny MCP server over stdio with no dependencies (Python 3.10+).

    from mini_mcp import Server
    app = Server("my-tools")

    @app.tool("add", "Add two numbers", {"a": "number", "b": "number"})
    def add(a, b):
        return a + b

    app.run()

Parameters: {"name": "string" | "number" | "integer" | "boolean" | "array" | "object"} (all required), or a full
JSON Schema dict with "type": "object". Return a string, a number, a dict/list (sent as JSON text) or None.
Raise an exception to send an error back to Claude.
"""
import inspect
import json
import sys

LATEST = "2025-06-18"
SUPPORTED = {"2024-11-05", "2025-03-26", "2025-06-18"}


class Server:
    def __init__(self, name: str, version: str = "1.0.0", instructions: str = ""):
        self.name, self.version, self.instructions = name, version, instructions
        self.tools: dict[str, dict] = {}

    def tool(self, name: str, description: str, params: dict | None = None):
        params = params or {}
        if params.get("type") == "object":
            schema = params
        else:
            props = {}
            for k, v in params.items():
                props[k] = v if isinstance(v, dict) else {"type": v}
            schema = {"type": "object", "properties": props, "required": list(props)}

        def wrap(fn):
            self.tools[name] = {"fn": fn, "spec": {"name": name, "description": description, "inputSchema": schema}}
            return fn
        return wrap

    # ---- protocol --------------------------------------------------------------------------------------

    def handle(self, msg: dict) -> dict | None:
        method, mid = msg.get("method"), msg.get("id")
        if mid is None:  # a notification: nothing to answer
            return None
        try:
            if method == "initialize":
                asked = (msg.get("params") or {}).get("protocolVersion")
                result = {"protocolVersion": asked if asked in SUPPORTED else LATEST,
                          "capabilities": {"tools": {"listChanged": False}},
                          "serverInfo": {"name": self.name, "version": self.version}}
                if self.instructions:
                    result["instructions"] = self.instructions
            elif method == "ping":
                result = {}
            elif method == "tools/list":
                result = {"tools": [t["spec"] for t in self.tools.values()]}
            elif method == "tools/call":
                p = msg.get("params") or {}
                t = self.tools.get(p.get("name"))
                if not t:
                    return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32602, "message": f"Unknown tool {p.get('name')}"}}
                result = self._call(t["fn"], p.get("arguments") or {})
            elif method in ("resources/list", "prompts/list"):
                result = {method.split("/")[0]: []}
            else:
                return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"Unknown method {method}"}}
        except Exception as e:  # never crash the server
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32603, "message": str(e)}}
        return {"jsonrpc": "2.0", "id": mid, "result": result}

    def _call(self, fn, args: dict) -> dict:
        try:
            accepted = inspect.signature(fn).parameters
            if not any(p.kind == p.VAR_KEYWORD for p in accepted.values()):
                args = {k: v for k, v in args.items() if k in accepted}
            out = fn(**args)
        except Exception as e:
            return {"content": [{"type": "text", "text": f"Error: {e}"}], "isError": True}
        if out is None:
            text = "Done."
        elif isinstance(out, str):
            text = out
        else:
            text = json.dumps(out, indent=2, ensure_ascii=False, default=str)
        return {"content": [{"type": "text", "text": text}], "isError": False}

    def run(self):
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except ValueError:
                continue
            msgs = msg if isinstance(msg, list) else [msg]
            replies = [r for r in (self.handle(m) for m in msgs) if r]
            for r in replies:
                sys.stdout.write(json.dumps(r) + "\n")
            sys.stdout.flush()


def log(*a):
    """Print to stderr (stdout is reserved for the protocol)."""
    print(*a, file=sys.stderr, flush=True)

