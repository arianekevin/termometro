#!/usr/bin/env python3
"""Termometro MCP server — lets an AI assistant read a Termometro instance: what frustrates people, what fails,
how far things are and what goes together.

Standard library only; it talks MCP over stdio and reads the server's API with a token.

  TERMOMETRO_URL       your server, e.g. https://termometro.example.com
  TERMOMETRO_TOKEN     one of the server's TERMOMETRO_API_TOKENS (`python termometro.py new-token` makes one)
  TERMOMETRO_PROJECT   optional: the project to use when a tool call names none

Claude Code:  claude mcp add termometro -e TERMOMETRO_URL=https://… -e TERMOMETRO_TOKEN=tt_… -- python3 termometro_mcp.py
Get the file from your own server:  curl -O https://termometro.example.com/termometro_mcp.py
"""
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

PROTOCOL = "2025-06-18"
URL = os.environ.get("TERMOMETRO_URL", "").rstrip("/")
TOKEN = os.environ.get("TERMOMETRO_TOKEN", "")
DEFAULT_PROJECT = os.environ.get("TERMOMETRO_PROJECT", "")

PERIOD = {"days": {"type": "integer", "description": "How many days back (1, 7, 30, 90…). Default 7.", "default": 7}}
CUTS = {"version": {"type": "string", "description": "Only this app version"},
        "account": {"type": "string", "description": "Only this account id"},
        "role": {"type": "string", "description": "Only this role"},
        "user": {"type": "string", "description": "Only this user id"}}
PROJECT = {"project": {"type": "string", "description": "Project name (see list_projects); optional when TERMOMETRO_PROJECT is set"}}


def tool(name, description, path, extra=None, required=(), fixed=None):
    return {"name": name, "description": description, "path": path, "fixed": fixed or {},
            "inputSchema": {"type": "object", "properties": {**PROJECT, **PERIOD, **CUTS, **(extra or {})},
                            "required": list(required)}}


TOOLS = [
    {"name": "list_projects", "description": "The projects this Termometro instance measures.", "path": "/api/me", "fixed": {},
     "inputSchema": {"type": "object", "properties": {}}},
    tool("report", "START HERE. The whole period in one Markdown document with the definitions needed to read it: "
         "overview against the period before, what deserves a look, screens by frustration, failures (with stack and the "
         "steps up to them), effort per action, buttons used a lot and far away, actions that follow one another, screen "
         "to screen flow, usage, never-clicked elements, roles and the latest version against the previous.",
         "/api/report", fixed={"format": "md"}),
    tool("overview", "The period against the one just before (score, visits, people, failures), score per day and the "
         "list of what deserves a look, most serious first, each with its facts.", "/api/overview"),
    tool("search", "Find screens, elements, failures, actions, users and accounts whose name contains a text.",
         "/api/search", {"q": {"type": "string", "description": "Text to look for (2+ characters)"}}, ["q"]),
    tool("frustration", "Frustration score per screen with its signals, the elements that irritate and what failed; and "
         "per version.", "/api/summary"),
    tool("failures", "Every failure (JS errors, 5xx, 4xx, slow requests) grouped by kind and message, the ones hitting "
         "most sessions first, with when and in which version each started.", "/api/failures"),
    tool("failure", "One failure in depth: screens, versions, browsers, kinds of screen, what was clicked right before, "
         "the code stack and the last sessions' steps up to it.", "/api/failure",
         {"signal": {"type": "string", "description": "Failure kind: js_error, http_5xx, http_4xx or slow"},
          "detail": {"type": "string", "description": "The failure's message exactly as `failures` lists it"}}, ["signal", "detail"]),
    tool("session", "Everything one session did, in order (ids only, never content).", "/api/session",
         {"session": {"type": "string", "description": "Session id, from a failure's trails"}}, ["session"]),
    tool("journeys", "How people move: clicks and screens needed to reach each button and action against how much it is "
         "used ('far' ones are candidates for a better place), actions that tend to follow one another, and where people "
         "come from and go to on each screen with the time spent there.", "/api/journeys"),
    tool("funnel", "How many sessions go through a sequence of steps, in order.", "/api/funnel",
         {"steps": {"type": "array", "items": {"type": "string"},
                    "description": "Steps like 'page:/orders', 'action:POST /api/orders' or 'click:button#save'"}}, ["steps"]),
    tool("usage", "Without a route: visits, clicks and users per screen. With a route: clicks per element on that screen "
         "and the elements nobody clicked.", "/api/usage", {"route": {"type": "string", "description": "Screen route pattern"}}),
    tool("effort", "Clicks and time each accepted write (action) takes: median and p90.", "/api/actions"),
    tool("people", "Usage and score per role, per account and per user id.", "/api/people"),
    tool("compare_versions", "One version against another (default: the latest against the one before): per screen, per "
         "action and the failures only the newer one has.", "/api/compare",
         {"a": {"type": "string", "description": "Older version"}, "b": {"type": "string", "description": "Newer version"}}),
]
BY_NAME = {t["name"]: t for t in TOOLS}


def call_api(path: str, params: dict) -> str:
    query = urllib.parse.urlencode({k: json.dumps(v) if isinstance(v, list) else v for k, v in params.items()
                                    if v not in (None, "")})
    req = urllib.request.Request(f"{URL}{path}?{query}", headers={"Authorization": f"Bearer {TOKEN}"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read().decode()


def run_tool(name: str, args: dict) -> str:
    t = BY_NAME.get(name)
    if not t:
        raise ValueError(f"unknown tool {name}")
    if not URL or not TOKEN:
        raise ValueError("set TERMOMETRO_URL and TERMOMETRO_TOKEN")
    if name == "list_projects":
        me = json.loads(call_api("/api/me", {}))
        return json.dumps([{"name": p["name"], "url": p["url"]} for p in me.get("projects", [])], ensure_ascii=False)
    params = {**args, **t["fixed"]}
    params["project"] = params.get("project") or DEFAULT_PROJECT
    if not params["project"]:
        raise ValueError("say which project (list_projects shows them) or set TERMOMETRO_PROJECT")
    params.setdefault("days", 7)
    return call_api(t["path"], params)


def reply(msg_id, result=None, error=None):
    out = {"jsonrpc": "2.0", "id": msg_id}
    out["error" if error else "result"] = error or result
    sys.stdout.write(json.dumps(out, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def handle(msg: dict):
    method, msg_id = msg.get("method"), msg.get("id")
    if msg_id is None:
        return  # a notification (initialized, cancelled): nothing to answer
    if method == "initialize":
        return reply(msg_id, {"protocolVersion": msg.get("params", {}).get("protocolVersion", PROTOCOL),
                              "capabilities": {"tools": {}}, "serverInfo": {"name": "termometro", "version": "0.3.0"},
                              "instructions": "Call `report` first: it has the whole picture and the definitions. Then "
                                              "drill down with failure, session, journeys, funnel, usage or search."})
    if method == "ping":
        return reply(msg_id, {})
    if method == "tools/list":
        return reply(msg_id, {"tools": [{k: t[k] for k in ("name", "description", "inputSchema")} for t in TOOLS]})
    if method == "tools/call":
        p = msg.get("params", {})
        try:
            text = run_tool(p.get("name", ""), p.get("arguments") or {})
            return reply(msg_id, {"content": [{"type": "text", "text": text}]})
        except urllib.error.HTTPError as e:
            text = f"Termometro answered {e.code}: {e.read().decode(errors='replace')[:300]}"
        except (OSError, ValueError) as e:
            text = str(e)
        return reply(msg_id, {"content": [{"type": "text", "text": text}], "isError": True})
    reply(msg_id, error={"code": -32601, "message": f"method not found: {method}"})


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            reply(None, error={"code": -32700, "message": "parse error"})
            continue
        handle(msg)


if __name__ == "__main__":
    main()
