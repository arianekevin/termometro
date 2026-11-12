#!/usr/bin/env python3
"""Termometro server — receives what the collector sends and shows usage and frustration per screen.

Standard library only, one SQLite file. Serves the dashboard, the heat map, the collector for <script> tags
and the API:

  POST /api/events     a batch from the collector; the project key picks the project
  POST /api/login      the instance password -> session cookie
  GET  /auth/google    sign in with Google (then /auth/google/callback); only allowed e-mails or domains get in
  POST /api/logout
  GET  /api/me         is this browser signed in, and which projects exist
  GET  /api/overview   the period against the one before, and what deserves a look ┐
  GET  /api/search     screens, elements, failures, actions and ids containing ?q=  │
  GET  /api/failures   every failure, grouped by kind and message       │
  GET  /api/failure    one failure in depth (?signal=&detail=): stack, browsers, trails │
  GET  /api/session    everything one session did, in order (?session=) │
  GET  /api/journeys   time on screen, screen to screen, how far things are, actions that follow │
  GET  /api/funnel     sessions through ?steps=["page:/a","action:POST /b"] in order │
  GET  /api/report     everything above for the period in one document, with definitions; ?format=md for text │
  GET  /api/summary    frustration per screen and per version      │
  GET  /api/usage      usage per screen, or per element of one      │ session cookie (or a heat-map token,
  GET  /api/people     usage per role, account and user (ids only)  │ for /api/usage)
  GET  /api/actions    effort (clicks and time) per accepted write  │
  GET  /api/compare    one version against another (default: latest) │
  GET  /api/filters    accounts, roles and versions seen             │
  GET  /api/names      what people call screens, buttons, actions and accounts │
  GET  /api/dictionary everything that can be named, with its automatic name, its given name and its use
  POST /api/names      the dictionary: {kind, key, name} names a screen, control, action or account (empty = back to auto)
  GET  /api/status     has this project received anything yet        │
  POST /api/map-token  a one-hour token to open the heat map        │
  GET  /api/features   each watched feature: uses against before, people, accounts, adoption, frustration, per day
  GET  /api/engagement per account: people and sessions a day, uses of each feature, now against before, drops first
                       (with ?account=, also that account's day by day)
  POST /api/features   {id?, name, rules: [{kind: screen|control|action|track, key}]} or {id, delete: true}
                       ?feature=<id> on any read above narrows it to what belongs to that feature
  POST /api/mark       start the project afresh from now (?project=), or ?clear=1 to undo ┘
                       every read above sees only what came after the mark, unless ?all=1
  GET  /  /map.js  /termometro.js

A screen's frustration score is the weighted signals divided by its visits, times 20, capped at 100. One rage
click on every visit scores 60; one 5xx on every visit scores 100.

Configuration (environment) — at least one way in, Google or a password, unless TERMOMETRO_NO_AUTH=1:
  TERMOMETRO_GOOGLE_CLIENT_ID, TERMOMETRO_GOOGLE_CLIENT_SECRET   an OAuth client of your own Google Cloud project
  TERMOMETRO_ALLOWED_EMAILS, TERMOMETRO_ALLOWED_DOMAINS           who may sign in with Google (comma separated)
  TERMOMETRO_PUBLIC_URL  where this server is reached, e.g. https://termometro.example.com (Google redirects back there)
  TERMOMETRO_PASSWORD   a single password for the dashboard
  TERMOMETRO_PROJECTS   JSON list: [{"name", "key", "origins": [...], "url"}]; or TERMOMETRO_CONFIG, a file with it
  TERMOMETRO_DB         SQLite file (default ./data/termometro.db)
  TERMOMETRO_HOST, TERMOMETRO_PORT          (default 0.0.0.0:8080)
  TERMOMETRO_RETENTION_DAYS                 events with user ids live this long (default 90), then become id-less totals
  TERMOMETRO_WEBHOOK_URL   Slack or Google Chat incoming webhook for every project without its own "webhook": warns when
                           the latest version made a screen worse or brought a new failure
  TERMOMETRO_LANGUAGE      language of those warnings: en (default) or pt-BR
  TERMOMETRO_API_TOKENS    comma-separated tokens that read everything with `Authorization: Bearer <token>` — for the
                           MCP server (termometro_mcp.py) or your own scripts; `python termometro.py new-token` makes one

`python termometro.py new-key` prints a fresh project key.
"""
import base64
import datetime
import hashlib
import urllib.parse
import urllib.request
import hmac
import json
import os
import re
import secrets
import sqlite3
import statistics
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

HERE = Path(__file__).resolve().parent
STATIC = HERE / "static"
VERSION = "0.2.2"

# Weight of each frustration signal in the score. "page" is a visit (the denominator); "click" and "action"
# measure usage and effort and weigh nothing; "inventory" lists what can be clicked on a screen.
WEIGHTS = {"rage": 3, "dead": 2, "js_error": 5, "http_5xx": 5, "http_4xx": 2, "abandon": 2, "bounce": 1, "slow": 1}
FAILURES = "('js_error', 'http_5xx', 'http_4xx', 'slow')"
TYPES = set(WEIGHTS) | {"page", "click", "action", "inventory", "track"}
FACTOR, CAP = 20, 100

MAX_BODY = 256 * 1024
MAX_EVENTS = 100
MAX_INVENTORY = 300
MAX_PER_MINUTE = 1200
MAX_LOGINS_PER_MINUTE = 10
SESSION_SECONDS = 7 * 86400
MAP_TOKEN_SECONDS = 3600
GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
ALERT_EVERY = 3600
ALERT_MIN_VISITS = 30   # visits to a screen in each of the two versions before its scores are compared
ALERT_RISE = 15         # score points a screen has to get worse by
ALERT_MIN_NEW = 5       # times a failure the previous version never had must happen
SIZES = {"version": 40, "session": 40, "account": 64, "user": 64, "role": 32,
         "route": 200, "target": 200, "detail": 200, "stack": 1200, "device": 10, "label": 60}
MAX_CLOCK_GAP = 86400 * 1000  # an event older than this inside a batch is put at the batch's arrival
TRAIL_BEFORE, TRAIL_AFTER, TRAIL_SAMPLES, SESSION_MAX = 15, 3, 5, 500
# Added after 0.2: old databases get them on start (empty for what was already there).
NEW_COLUMNS = {"stack": "TEXT NOT NULL DEFAULT ''", "agent": "TEXT NOT NULL DEFAULT ''", "device": "TEXT NOT NULL DEFAULT ''",
               "label": "TEXT NOT NULL DEFAULT ''"}


class Config:
    def __init__(self, env=os.environ):
        self.password = env.get("TERMOMETRO_PASSWORD", "")
        self.google_id = env.get("TERMOMETRO_GOOGLE_CLIENT_ID", "")
        self.google_secret = env.get("TERMOMETRO_GOOGLE_CLIENT_SECRET", "")
        self.allowed_emails = {e.strip().lower() for e in env.get("TERMOMETRO_ALLOWED_EMAILS", "").split(",") if e.strip()}
        self.allowed_domains = {d.strip().lower().lstrip("@") for d in env.get("TERMOMETRO_ALLOWED_DOMAINS", "").split(",") if d.strip()}
        self.public_url = env.get("TERMOMETRO_PUBLIC_URL", "").rstrip("/")
        self.no_auth = env.get("TERMOMETRO_NO_AUTH") == "1"
        self.db = Path(env.get("TERMOMETRO_DB", "data/termometro.db"))
        self.host = env.get("TERMOMETRO_HOST", "0.0.0.0")
        self.port = int(env.get("TERMOMETRO_PORT", "8080"))
        self.retention_days = int(env.get("TERMOMETRO_RETENTION_DAYS", "90"))
        self.webhook = env.get("TERMOMETRO_WEBHOOK_URL", "")
        self.api_tokens = [x.strip() for x in env.get("TERMOMETRO_API_TOKENS", "").split(",") if x.strip()]
        self.language = "pt" if env.get("TERMOMETRO_LANGUAGE", "").lower().startswith("pt") else "en"
        raw = env.get("TERMOMETRO_PROJECTS")
        if not raw and env.get("TERMOMETRO_CONFIG"):
            raw = Path(env["TERMOMETRO_CONFIG"]).read_text()
        projects = json.loads(raw) if raw else []
        if isinstance(projects, dict):
            projects = projects.get("projects", [])
        self.projects = {}
        for p in projects:
            if not p.get("name") or not p.get("key"):
                raise ValueError("every project needs a name and a key")
            self.projects[p["key"]] = {"name": str(p["name"]), "origins": list(p.get("origins", [])), "url": p.get("url", ""),
                                       "webhook": p.get("webhook", "") or self.webhook}
        self.by_name = {p["name"]: p for p in self.projects.values()}

    @property
    def google(self) -> bool:
        return bool(self.google_id and self.google_secret)

    def allowed(self, email: str) -> bool:
        email = email.lower()
        return email in self.allowed_emails or email.rpartition("@")[2] in self.allowed_domains

    def check(self):
        if not self.password and not self.google and not self.no_auth:
            raise SystemExit("Set a way in: TERMOMETRO_GOOGLE_CLIENT_ID and _SECRET, or TERMOMETRO_PASSWORD "
                             "(or TERMOMETRO_NO_AUTH=1 if the dashboard sits behind your own auth).")
        if self.google and not (self.allowed_emails or self.allowed_domains):
            raise SystemExit("Google sign-in is on but nobody is allowed: set TERMOMETRO_ALLOWED_EMAILS or _DOMAINS.")
        if self.google and not self.public_url:
            raise SystemExit("Google sign-in needs TERMOMETRO_PUBLIC_URL, where Google sends people back.")
        if not self.projects:
            print("warning: no project configured — nothing will be accepted. See TERMOMETRO_PROJECTS.", flush=True)


CONFIG: Config = None  # set in main() or by the tests
_lock = threading.Lock()
_counts: dict[str, tuple[int, int]] = {}


def connect() -> sqlite3.Connection:
    CONFIG.db.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(CONFIG.db, timeout=10)
    con.execute("PRAGMA journal_mode=WAL")
    con.executescript("""
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY, project TEXT NOT NULL, version TEXT NOT NULL, session TEXT NOT NULL,
            account TEXT NOT NULL DEFAULT '', user_id TEXT NOT NULL DEFAULT '', role TEXT NOT NULL DEFAULT '',
            type TEXT NOT NULL, route TEXT NOT NULL, target TEXT NOT NULL DEFAULT '', detail TEXT NOT NULL DEFAULT '',
            clicks INTEGER, duration_ms INTEGER, at INTEGER NOT NULL);
        CREATE INDEX IF NOT EXISTS events_project_at ON events (project, at);
        CREATE TABLE IF NOT EXISTS elements (
            project TEXT NOT NULL, route TEXT NOT NULL, target TEXT NOT NULL, last_seen INTEGER NOT NULL,
            PRIMARY KEY (project, route, target));
        CREATE TABLE IF NOT EXISTS history (
            day TEXT NOT NULL, project TEXT NOT NULL, version TEXT NOT NULL, route TEXT NOT NULL, type TEXT NOT NULL,
            n INTEGER NOT NULL, PRIMARY KEY (day, project, version, route, type));
        CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS features (
            project TEXT NOT NULL, id TEXT NOT NULL, name TEXT NOT NULL, rules TEXT NOT NULL, at INTEGER NOT NULL,
            PRIMARY KEY (project, id));
        CREATE TABLE IF NOT EXISTS dictionary (
            project TEXT NOT NULL, kind TEXT NOT NULL, key TEXT NOT NULL, name TEXT NOT NULL, at INTEGER NOT NULL,
            PRIMARY KEY (project, kind, key));
        CREATE TABLE IF NOT EXISTS alerts (
            project TEXT NOT NULL, version TEXT NOT NULL, key TEXT NOT NULL, at INTEGER NOT NULL,
            PRIMARY KEY (project, version, key));
    """)
    for table, columns in (("events", NEW_COLUMNS), ("elements", {"label": "TEXT NOT NULL DEFAULT ''"})):
        have = {row[1] for row in con.execute(f"PRAGMA table_info({table})")}
        for column, kind in columns.items():
            if column not in have:
                try:
                    con.execute(f"ALTER TABLE {table} ADD COLUMN {column} {kind}")
                except sqlite3.OperationalError:  # another thread added it first
                    pass
    con.execute("CREATE INDEX IF NOT EXISTS events_session ON events (project, session, at)")
    MARKS.clear()
    MARKS.update({k[5:]: int(v) for k, v in con.execute("SELECT k, v FROM meta WHERE k LIKE 'mark:%'")})
    FEATURES.clear()
    for project, fid, name, rules in con.execute("SELECT project, id, name, rules FROM features ORDER BY name"):
        FEATURES.setdefault(project, {})[fid] = {"id": fid, "name": name, "rules": json.loads(rules)}
    return con


# Watched features, per project: a name and the screens, controls, actions and app events that make it up. Read from
# the features table on every connect(), like the marks.
FEATURES: dict[str, dict[str, dict]] = {}
RULE_KINDS = ("screen", "control", "action", "track")


def feature_sql(rules: list[dict], uses_only: bool = False) -> tuple[str, list]:
    """The events that belong to a feature (its scope: everything on its screens, on its controls, its requests and
    their failures, its app events) or, with uses_only, the ones that count as one use of it (a visit to its screen,
    a click on its control, its accepted write, its app event)."""
    parts, args = [], []
    if uses_only:  # one use is counted once: by its write or app event if it has one, else its click, else its visit
        kinds = {r.get("kind") for r in rules}
        strongest = ({"action", "track"} & kinds) or ({"control"} & kinds) or {"screen"}
        rules = [r for r in rules if r.get("kind") in strongest]
    for r in rules:
        kind, key = r.get("kind"), str(r.get("key", ""))
        if kind == "screen":
            parts.append("(type = 'page' AND route = ?)" if uses_only else "route = ?")
            args.append(key)
        elif kind == "control":
            route, _, target = key.partition("\t")
            parts.append(("(type = 'click' AND " if uses_only else "(") + "route = ? AND target = ?)")
            args += [route, target]
        elif kind == "action":
            if uses_only:
                parts.append("(type = 'action' AND detail = ?)")
                args.append(key)
            else:
                parts.append("(detail = ? OR detail LIKE ?)")  # the write itself, and its failures ("POST /x 500")
                args += [key, key + " %"]
        elif kind == "track":
            parts.append("(type = 'track' AND detail = ?)")
            args.append(key)
    return ("(" + " OR ".join(parts) + ")", args) if parts else ("0", [])


def save_feature(con, project: str, item: dict) -> str:
    """Creates, changes ({id, name, rules}) or removes ({id, delete: true}) a watched feature. Returns its id."""
    fid = str(item.get("id") or "")[:40]
    if item.get("delete"):
        con.execute("DELETE FROM features WHERE project = ? AND id = ?", (project, fid))
        return fid
    name = " ".join(str(item.get("name", "")).split())[:MAX_NAME]
    rules = [{"kind": r["kind"], "key": str(r.get("key", ""))[:400]} for r in item.get("rules") or []
             if isinstance(r, dict) and r.get("kind") in RULE_KINDS and r.get("key")][:50]
    if not name or not rules:
        raise ValueError("a feature needs a name and at least one screen, control, action or event")
    if any(other["name"].lower() == name.lower() and other["id"] != fid for other in FEATURES.get(project, {}).values()):
        raise ValueError("there is already a feature with this name")
    fid = fid or secrets.token_hex(4)
    con.execute("INSERT OR REPLACE INTO features (project, id, name, rules, at) VALUES (?, ?, ?, ?, ?)",
                (project, fid, name, json.dumps(rules, ensure_ascii=False), int(time.time() * 1000)))
    return fid


# A project's fresh start: reads see only what came after it (unless they ask for all=1); nothing is deleted, and
# what came before still leaves with the retention. Read from the meta table on every connect().
MARKS: dict[str, int] = {}


def mark_of(q: dict) -> int:
    return 0 if q.get("all") == "1" else MARKS.get(q.get("project", ""), 0)


def set_mark(con, project: str, at: int | None) -> None:
    if at is None:
        con.execute("DELETE FROM meta WHERE k = ?", ("mark:" + project,))
        MARKS.pop(project, None)
    else:
        con.execute("INSERT OR REPLACE INTO meta (k, v) VALUES (?, ?)", ("mark:" + project, str(at)))
        MARKS[project] = at


_secret: dict[str, bytes] = {}


def secret() -> bytes:
    """Signs sessions and map tokens. Kept in the database so a restart does not sign everyone out."""
    if str(CONFIG.db) in _secret:
        return _secret[str(CONFIG.db)]
    with connect() as con:
        row = con.execute("SELECT v FROM meta WHERE k = 'secret'").fetchone()
        if not row:
            con.execute("INSERT OR IGNORE INTO meta (k, v) VALUES ('secret', ?)", (secrets.token_bytes(32).hex(),))
            row = con.execute("SELECT v FROM meta WHERE k = 'secret'").fetchone()
    _secret[str(CONFIG.db)] = bytes.fromhex(row[0])
    return _secret[str(CONFIG.db)]


def sign(payload: str) -> str:
    mac = hmac.new(secret(), payload.encode(), hashlib.sha256).digest()
    return payload + "." + base64.urlsafe_b64encode(mac).decode().rstrip("=")


def verify(token: str) -> str | None:
    payload, _, _ = token.rpartition(".")
    return payload if payload and hmac.compare_digest(sign(payload), token) else None


def text(value, field: str) -> str:
    return str(value if value is not None else "")[: SIZES[field]]


def integer(value) -> int | None:
    return int(value) if isinstance(value, (int, float)) and 0 <= value < 10**9 else None


BROWSERS = (("Edge", r"Edg(?:e|A|iOS)?/(\d+)"), ("Opera", r"OPR/(\d+)"), ("Samsung", r"SamsungBrowser/(\d+)"),
            ("Firefox", r"(?:Firefox|FxiOS)/(\d+)"), ("Chrome", r"(?:Chrome|CriOS)/(\d+)"), ("Safari", r"Version/(\d+).*Safari"))
SYSTEMS = (("iOS", r"iPhone|iPad|iPod"), ("Android", r"Android"), ("Windows", r"Windows"), ("ChromeOS", r"CrOS"),
           ("macOS", r"Mac OS X|Macintosh"), ("Linux", r"Linux"))


def agent_of(ua: str) -> str:
    """Browser and major version, and the system: "Chrome 130 · macOS". Nothing finer, so it cannot single anyone out."""
    ua = ua or ""
    browser = next((f"{name} {m.group(1)}" for name, pat in BROWSERS if (m := re.search(pat, ua))), "")
    system = next((name for name, pat in SYSTEMS if re.search(pat, ua)), "")
    return " · ".join(x for x in (browser, system) if x)


def moment(value) -> int | None:
    return int(value) if isinstance(value, (int, float)) and 0 < value < 10**14 else None


def parse_batch(batch, origin: str | None, agent: str = "") -> tuple[str, list[tuple], list[tuple]]:
    """A collector batch -> (project, event rows, inventory rows). Raises ValueError or PermissionError."""
    if not isinstance(batch, dict):
        raise ValueError("batch is not an object")
    project = CONFIG.projects.get(str(batch.get("key", "")))
    if not project:
        raise PermissionError("unknown key")
    if origin and project["origins"] and origin not in project["origins"]:
        raise PermissionError("origin not allowed for this key")
    session = text(batch.get("session"), "session")
    if not session:
        raise ValueError("missing session")
    events = batch.get("events")
    if not isinstance(events, list) or not events or len(events) > MAX_EVENTS:
        raise ValueError(f"events must be a list of 1 to {MAX_EVENTS}")
    who = [text(batch.get(f), f) for f in ("version", "account", "user", "role")]
    device = text(batch.get("device"), "device")
    now = int(time.time() * 1000)
    sent = moment(batch.get("sent"))
    rows, elements = [], []
    for e in events:
        if not isinstance(e, dict) or e.get("type") not in TYPES:
            continue  # an unknown type (a newer collector) does not sink the batch
        route = text(e.get("route"), "route") or "/"
        if e["type"] == "inventory":
            targets = e.get("targets") if isinstance(e.get("targets"), list) else []
            labels = e.get("labels") if isinstance(e.get("labels"), list) else []
            labels = (labels + [""] * len(targets))[:len(targets)]
            elements += [(project["name"], route, text(t, "target"), now, text(l, "label"))
                         for t, l in zip(targets[:MAX_INVENTORY], labels) if t]
            continue
        # The browser's clock only says how long before sending it happened; the server's says when that was.
        t = moment(e.get("t"))
        at = now - min(max(sent - t, 0), MAX_CLOCK_GAP) if sent and t else now
        rows.append((project["name"], who[0] or "?", session, who[1], who[2], who[3], e["type"], route,
                     text(e.get("target"), "target"), text(e.get("detail"), "detail"),
                     integer(e.get("clicks")), integer(e.get("duration_ms")), at,
                     text(e.get("stack"), "stack") if e["type"] == "js_error" else "", agent, device, text(e.get("label"), "label")))
    return project["name"], rows, elements


INSERT_EVENT = ("INSERT INTO events (project, version, session, account, user_id, role, type, route, target, detail, clicks, "
                "duration_ms, at, stack, agent, device, label) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)")


def within_limit(bucket: str, n: int, limit: int) -> bool:
    minute = int(time.time() // 60)
    with _lock:
        m, total = _counts.get(bucket, (minute, 0))
        if m != minute:
            total = 0
        if total + n > limit:
            return False
        _counts[bucket] = (minute, total + n)
        if len(_counts) > 10_000:
            _counts.clear()
        return True


def score(points: float, visits: int) -> int:
    return min(CAP, round(points / visits * FACTOR)) if visits else 0


def p90(values: list) -> float:
    if not values:
        return 0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(len(ordered) * 0.9))]


WEIGHT_CASE = "CASE type " + " ".join(f"WHEN '{t}' THEN {w}" for t, w in WEIGHTS.items()) + " ELSE 0 END"
SIGNALS = "(" + ",".join(f"'{t}'" for t in WEIGHTS) + ")"


class Filter:
    """The WHERE every read shares: project, period and the optional cuts."""

    def __init__(self, q: dict, before: bool = False):
        try:
            self.days = max(1, min(CONFIG.retention_days, int(q.get("days", "7"))))
        except ValueError:
            self.days = 7
        self.mark = mark_of(q)
        self.since = max(self.mark, int((time.time() - self.days * 86400) * 1000))
        self.sql, self.args = "project = ? AND at >= ?", [q.get("project", ""), self.since]
        self.until = int(time.time() * 1000)
        if before:  # the same length of time just before: what "now" is compared with, never before the mark
            end = int((time.time() - self.days * 86400) * 1000)
            self.since = max(self.mark, end - self.days * 86400 * 1000)
            self.sql += " AND at < ?"
            self.args = [q.get("project", ""), self.since, end]
            self.until = end
        for field, column in (("version", "version"), ("account", "account"), ("role", "role"),
                              ("user", "user_id"), ("route", "route")):
            if q.get(field):
                self.sql += f" AND {column} = ?"
                self.args.append(q[field])
        self.feature = FEATURES.get(q.get("project", ""), {}).get(q.get("feature", ""))
        if self.feature:  # every read sees only what belongs to the feature
            sql, args = feature_sql(self.feature["rules"])
            self.sql += " AND " + sql
            self.args += args
        self.q = q


def frustration_by(con, f: Filter, key: str) -> list[dict]:
    rows = con.execute(f"""
        SELECT {key}, type, COUNT(*), COUNT(DISTINCT session) FROM events
        WHERE {f.sql} AND (type = 'page' OR type IN {SIGNALS}) GROUP BY {key}, type""", f.args).fetchall()
    groups: dict[str, dict] = {}
    for k, kind, n, sessions in rows:
        g = groups.setdefault(k, {"key": k, "visits": 0, "sessions": 0, "points": 0, "signals": {}})
        if kind == "page":
            g["visits"], g["sessions"] = n, sessions
        else:
            g["signals"][kind] = n
            g["points"] += n * WEIGHTS[kind]
    for g in groups.values():
        g["score"] = score(g["points"], g["visits"])
    return sorted(groups.values(), key=lambda g: (-g["score"], -g["points"]))


def summary(con, f: Filter) -> dict:
    routes = frustration_by(con, f, "route")
    targets = con.execute(f"""
        SELECT route, target, type, COUNT(*) n FROM events WHERE {f.sql} AND type IN {SIGNALS} AND target != ''
        GROUP BY route, target, type ORDER BY n DESC""", f.args).fetchall()
    # SQLite hands back the bare `version` from the row that holds the MIN or the MAX: where it started and ended.
    first = {k[:4]: k[4:] for k in con.execute(f"""
        SELECT route, type, detail, target, MIN(at), version FROM events
        WHERE {f.sql} AND type IN {FAILURES} GROUP BY route, type, detail, target""", f.args)}
    failures = con.execute(f"""
        SELECT route, type, detail, target, COUNT(*) n, MAX(at), version, AVG(duration_ms) FROM events
        WHERE {f.sql} AND type IN {FAILURES}
        GROUP BY route, type, detail, target ORDER BY n DESC""", f.args).fetchall()
    per_route: dict[str, dict] = {}
    for route, target, kind, n in targets:
        lst = per_route.setdefault(route, {"targets": [], "failures": []})["targets"]
        if len(lst) < 5:
            lst.append({"target": target, "type": kind, "n": n})
    for route, kind, detail, target, n, last_at, last_version, ms in failures:
        lst = per_route.setdefault(route, {"targets": [], "failures": []})["failures"]
        if len(lst) < 5:
            first_at, first_version = first[(route, kind, detail, target)]
            lst.append({"type": kind, "detail": detail, "after": target, "n": n,
                        "first_at": first_at, "first_version": first_version, "last_at": last_at,
                        "last_version": last_version, "seconds": round(ms / 1000, 1) if kind == "slow" and ms else None})
    for r in routes:
        r.update(per_route.get(r["key"], {"targets": [], "failures": []}))
    visits, points = con.execute(f"""
        SELECT COALESCE(SUM(type = 'page'), 0), COALESCE(SUM({WEIGHT_CASE}), 0) FROM events WHERE {f.sql}""", f.args).fetchone()
    sessions = con.execute(f"SELECT COUNT(DISTINCT session) FROM events WHERE {f.sql}", f.args).fetchone()[0]
    return {"days": f.days, "weights": WEIGHTS, "factor": FACTOR,
            "overall": {"visits": visits, "sessions": sessions, "points": points, "score": score(points, visits)},
            "routes": routes,
            "versions": sorted(frustration_by(con, f, "version") if not f.q.get("version") else [], key=lambda g: g["key"])}


def usage(con, f: Filter) -> dict:
    """No route: how much each screen is used. With a route: how much each element is clicked, and what never was."""
    route = f.q.get("route")
    if not route:
        rows = con.execute(f"""
            SELECT route, SUM(type = 'page'), SUM(type = 'click'), COUNT(DISTINCT session),
                   COUNT(DISTINCT NULLIF(user_id, '')), COALESCE(SUM({WEIGHT_CASE}), 0)
            FROM events WHERE {f.sql} GROUP BY route""", f.args).fetchall()
        screens = [{"route": r, "visits": v, "clicks": c, "sessions": s, "users": u, "score": score(p, v)}
                   for r, v, c, s, u, p in rows if v]
        return {"screens": sorted(screens, key=lambda s: -s["visits"])}
    rows = con.execute(f"""
        SELECT target, SUM(type = 'click'), COUNT(DISTINCT NULLIF(user_id, '')), SUM(type = 'rage'), SUM(type = 'dead'),
               SUM(type IN ('js_error', 'http_5xx', 'http_4xx'))
        FROM events WHERE {f.sql} AND target != '' AND type IN ('click', 'rage', 'dead', 'js_error', 'http_5xx', 'http_4xx')
        GROUP BY target""", f.args).fetchall()
    elements = {t: {"target": t, "clicks": c, "users": u, "rage": r, "dead": d, "errors": e} for t, c, u, r, d, e in rows}
    visits = con.execute(f"SELECT COUNT(*) FROM events WHERE {f.sql} AND type = 'page'", f.args).fetchone()[0]
    seen = [t for (t,) in con.execute("SELECT target FROM elements WHERE project = ? AND route = ?", (f.q.get("project"), route))]
    return {"route": route, "visits": visits,
            "elements": sorted(elements.values(), key=lambda e: -e["clicks"]),
            "never_clicked": sorted(t for t in seen if not elements.get(t, {}).get("clicks"))}


def people(con, f: Filter) -> dict:
    def by(column: str) -> list[dict]:
        rows = con.execute(f"""
            SELECT {column}, COUNT(DISTINCT NULLIF(user_id, '')), COUNT(DISTINCT session), SUM(type = 'page'),
                   SUM(type = 'click'), COALESCE(SUM({WEIGHT_CASE}), 0)
            FROM events WHERE {f.sql} AND {column} != '' GROUP BY {column}""", f.args).fetchall()
        screens = con.execute(f"""
            SELECT {column}, route, COUNT(*) n FROM events WHERE {f.sql} AND {column} != '' AND type = 'page'
            GROUP BY {column}, route ORDER BY n DESC""", f.args).fetchall()
        top: dict[str, list] = {}
        for k, route, n in screens:
            if len(top.setdefault(k, [])) < 3:
                top[k].append({"route": route, "visits": n})
        groups = [{"key": k, "users": u, "sessions": s, "visits": v, "clicks": c, "score": score(p, v),
                   "screens": top.get(k, [])} for k, u, s, v, c, p in rows]
        return sorted(groups, key=lambda g: -g["visits"])

    users = by("user_id")
    who = {u: (r, a) for u, r, a in con.execute(
        f"SELECT user_id, MAX(role), MAX(account) FROM events WHERE {f.sql} AND user_id != '' GROUP BY user_id", f.args)}
    for g in users:
        g["role"], g["account"] = who.get(g["key"], ("", ""))
    return {"roles": by("role"), "accounts": by("account"), "users": users[:200]}


def actions(con, f: Filter) -> dict:
    rows = con.execute(f"""
        SELECT detail, clicks, duration_ms, user_id FROM events
        WHERE {f.sql} AND type = 'action' AND clicks IS NOT NULL""", f.args).fetchall()
    groups: dict[str, dict] = {}
    for detail, clicks, ms, user in rows:
        g = groups.setdefault(detail, {"clicks": [], "ms": [], "users": set()})
        g["clicks"].append(clicks)
        g["ms"].append(ms or 0)
        if user:
            g["users"].add(user)
    out = [{"action": a, "times": len(g["clicks"]), "users": len(g["users"]),
            "clicks_median": statistics.median(g["clicks"]), "clicks_p90": p90(g["clicks"]),
            "seconds_median": round(statistics.median(g["ms"]) / 1000, 1), "seconds_p90": round(p90(g["ms"]) / 1000, 1)}
           for a, g in groups.items()]
    return {"actions": sorted(out, key=lambda a: (-a["clicks_median"], -a["times"]))}


def versions_in_order(con, f: Filter) -> list[str]:
    """The versions seen in the period, oldest deploy first (by when each one first sent something)."""
    return [v for (v,) in con.execute(f"""
        SELECT version FROM events WHERE {f.sql} AND version != '?' GROUP BY version ORDER BY MIN(id)""", f.args)]


def compare(con, f: Filter) -> dict:
    """One version against another (default: the latest against the one before): per screen, per action, and the
    failures only the newer one has."""
    base = {k: v for k, v in f.q.items() if k != "version"}
    versions = versions_in_order(con, Filter(base))
    b = f.q.get("b") if f.q.get("b") in versions else (versions[-1] if versions else "")
    older = versions[:versions.index(b)] if b else []
    a = f.q.get("a") if f.q.get("a") in versions and f.q.get("a") != b else (older[-1] if older else "")
    if not a or not b:
        return {"versions": versions, "a": a, "b": b, "overall": {}, "routes": [], "actions": [], "new_failures": []}
    fa, fb = Filter({**base, "version": a}), Filter({**base, "version": b})

    def overall(fv):
        rows = frustration_by(con, fv, "version")
        return {k: rows[0][k] for k in ("visits", "score", "signals")} if rows else {"visits": 0, "score": 0, "signals": {}}

    def side(g):
        return {"visits": g["visits"], "score": g["score"], "signals": g["signals"]} if g else None

    ra = {g["key"]: g for g in frustration_by(con, fa, "route")}
    rb = {g["key"]: g for g in frustration_by(con, fb, "route")}
    routes = [{"route": r, "a": side(ra.get(r)), "b": side(rb.get(r)),
               "delta": rb[r]["score"] - ra[r]["score"] if ra.get(r, {}).get("visits") and rb.get(r, {}).get("visits") else None}
              for r in set(ra) | set(rb)]
    routes.sort(key=lambda x: (x["delta"] is None, -(x["delta"] or 0), -((x["b"] or {}).get("visits", 0))))
    aa = {x["action"]: x for x in actions(con, fa)["actions"]}
    ab = {x["action"]: x for x in actions(con, fb)["actions"]}
    acts = [{"action": k, "a": aa.get(k), "b": ab.get(k)} for k in set(aa) | set(ab)]
    acts.sort(key=lambda x: -((x["b"] or {}).get("clicks_median", 0) - (x["a"] or {}).get("clicks_median", 0)))
    seen = {(k, d) for k, d in con.execute(
        f"SELECT DISTINCT type, detail FROM events WHERE {fa.sql} AND type IN {FAILURES}", fa.args)}
    new = [{"type": k, "detail": d, "route": r, "n": n} for k, d, r, n in con.execute(f"""
        SELECT type, detail, MIN(route), COUNT(*) n FROM events WHERE {fb.sql} AND type IN {FAILURES}
        GROUP BY type, detail ORDER BY n DESC""", fb.args) if (k, d) not in seen]
    return {"versions": versions, "a": a, "b": b, "overall": {"a": overall(fa), "b": overall(fb)},
            "routes": routes, "actions": acts, "new_failures": new[:20]}


INSIGHT_MIN_VISITS = 10  # a screen needs this many visits before its score says anything
INSIGHT_RISE = 10        # score points against the previous period that count as worse (or better)
INSIGHT_EFFORT = 15      # median clicks of a laborious action
INSIGHT_IRRITATION = 5   # rage + dead clicks on one element


def totals(con, f: Filter) -> dict:
    visits, points, failures, sessions, users = con.execute(f"""
        SELECT COALESCE(SUM(type = 'page'), 0), COALESCE(SUM({WEIGHT_CASE}), 0), COALESCE(SUM(type IN {FAILURES}), 0),
               COUNT(DISTINCT session), COUNT(DISTINCT NULLIF(user_id, '')) FROM events WHERE {f.sql}""", f.args).fetchone()
    return {"visits": visits, "sessions": sessions, "users": users, "failures": failures, "score": score(points, visits)}


def daily(con, f: Filter) -> list[dict]:
    """Score, visits, people and failures per day of the period, oldest first; a day without visits is left out."""
    rows = con.execute(f"""
        SELECT date(at / 1000, 'unixepoch') d, SUM(type = 'page'), COALESCE(SUM({WEIGHT_CASE}), 0), SUM(type IN {FAILURES}),
               COUNT(DISTINCT NULLIF(user_id, ''))
        FROM events WHERE {f.sql} GROUP BY d ORDER BY d""", f.args).fetchall()
    return [{"day": d, "visits": v, "score": score(p, v), "failures": n, "users": u} for d, v, p, n, u in rows if v]


HEAT_SCREENS = 8  # screens in the screen-by-day map: the ones with the most frustration points


def screens_daily(con, f: Filter) -> list[dict]:
    """The screens that hurt the most in the period, each with its score per day: where the heat is and since when."""
    rows = con.execute(f"""
        SELECT route, date(at / 1000, 'unixepoch') d, SUM(type = 'page'), COALESCE(SUM({WEIGHT_CASE}), 0)
        FROM events WHERE {f.sql} AND (type = 'page' OR type IN {SIGNALS}) GROUP BY route, d""", f.args).fetchall()
    by: dict[str, dict] = {}
    for route, d, v, p in rows:
        g = by.setdefault(route, {"route": route, "points": 0, "visits": 0, "days": {}})
        g["points"] += p
        g["visits"] += v
        if v:
            g["days"][d] = {"score": score(p, v), "visits": v}
    top = sorted((g for g in by.values() if g["visits"] >= INSIGHT_MIN_VISITS), key=lambda g: -g["points"])[:HEAT_SCREENS]
    return [{"route": g["route"], "score": score(g["points"], g["visits"]), "visits": g["visits"], "days": g["days"]} for g in top]


def deploys(con, f: Filter) -> list[dict]:
    """When each version first sent something inside the period: the marks on the charts."""
    return [{"version": v, "at": at, "day": d} for v, at, d in con.execute(f"""
        SELECT version, MIN(at), date(MIN(at) / 1000, 'unixepoch') FROM events WHERE {f.sql} AND version != '?'
        GROUP BY version ORDER BY MIN(id)""", f.args)]


def overview(con, f: Filter) -> dict:
    """The period against the one just before, and what deserves a look, most serious first. Every insight carries
    the facts behind it and where in the dashboard to see more (`tab` and `params`)."""
    prev = Filter(f.q, before=True)
    now_routes = {g["key"]: g for g in frustration_by(con, f, "route")}
    old_routes = {g["key"]: g for g in frustration_by(con, prev, "route")}
    insights = []

    def add(kind, severity, weight, link, **facts):
        insights.append({"kind": kind, "severity": severity, "weight": weight, "link": link, **facts})

    # What the newest version made worse than the one before, screen by screen: usually the first thing to look at.
    by_version = set()
    if not f.q.get("version"):
        c = compare(con, f)
        for r in c["routes"]:
            a, b = r["a"] or {}, r["b"] or {}
            if (r["delta"] or 0) >= INSIGHT_RISE and a.get("visits", 0) >= INSIGHT_MIN_VISITS and b.get("visits", 0) >= INSIGHT_MIN_VISITS:
                by_version.add(r["route"])
                add("version_worse", "bad", 290 + r["delta"], {"tab": "versions", "params": {"a": c["a"], "b": c["b"]}},
                    route=r["route"], a=c["a"], b=c["b"], before=a["score"], now=b["score"], visits=b["visits"])
    for route, g in now_routes.items():
        if g["visits"] < INSIGHT_MIN_VISITS or route in by_version:
            continue
        old = old_routes.get(route)
        top = max(g["signals"].items(), key=lambda kv: kv[1] * WEIGHTS[kv[0]])[0] if g["signals"] else ""
        link = {"tab": "frustration", "params": {"route": route}}
        if old and old["visits"] >= INSIGHT_MIN_VISITS and g["score"] - old["score"] >= INSIGHT_RISE:
            add("screen_worse", "bad", 300 + g["score"] - old["score"], link, route=route, before=old["score"],
                now=g["score"], visits=g["visits"], top_signal=top)
        elif g["score"] >= 50:
            add("screen_frustrating", "bad", 200 + g["score"], link, route=route, now=g["score"], visits=g["visits"], top_signal=top)
        elif old and old["visits"] >= INSIGHT_MIN_VISITS and old["score"] - g["score"] >= INSIGHT_RISE:
            add("screen_better", "ok", old["score"] - g["score"], link, route=route, before=old["score"], now=g["score"],
                visits=g["visits"])
    # A failure is new when the retained history (since the mark) has nothing of it before this period.
    first = {(k, d): at for k, d, at in con.execute(
        f"SELECT type, detail, MIN(at) FROM events WHERE project = ? AND at >= ? AND type IN {FAILURES} GROUP BY type, detail",
        (f.q.get("project", ""), f.mark))}
    failures = con.execute(f"""
        SELECT type, detail, MIN(route), COUNT(*) n, COUNT(DISTINCT session), MAX(at) FROM events
        WHERE {f.sql} AND type IN {FAILURES} GROUP BY type, detail ORDER BY n DESC""", f.args).fetchall()
    for kind, detail, route, n, sessions, last_at in failures:
        facts = dict(type=kind, detail=detail, route=route, n=n, sessions=sessions, last_at=last_at)
        link = {"tab": "failures", "params": {"signal": kind, "detail": detail}}
        serious = kind in ("js_error", "http_5xx")
        if first.get((kind, detail), 0) >= f.since:
            add("failure_new", "bad" if serious else "warn", (250 if serious else 120) + min(n, 49), link, **facts)
        elif serious and n >= 5:
            add("failure_recurring", "warn", 100 + min(n, 99), link, **facts)
    for a in actions(con, f)["actions"]:
        if a["clicks_median"] >= INSIGHT_EFFORT and a["times"] >= 3:
            add("action_laborious", "warn", 90 + a["clicks_median"], {"tab": "actions", "params": {"action": a["action"]}},
                action=a["action"], clicks=a["clicks_median"], seconds=a["seconds_median"], times=a["times"])
    for route, target, rage, dead in con.execute(f"""
            SELECT route, target, SUM(type = 'rage'), SUM(type = 'dead') FROM events
            WHERE {f.sql} AND type IN ('rage', 'dead') AND target != '' GROUP BY route, target
            HAVING COUNT(*) >= {INSIGHT_IRRITATION} ORDER BY COUNT(*) DESC LIMIT 5""", f.args):
        add("element_irritating", "warn", 80 + min(rage + dead, 99), {"tab": "usage", "params": {"route": route}},
            route=route, target=target, rage=rage, dead=dead)
    j = journeys(con, f)
    far = {}
    for r in j["reach"]:  # one line per button or action, from the screen where it is used the most
        if r["far"] and r["key"] not in far:
            far[r["key"]] = r
    for r in list(far.values())[:3]:
        add("reach_far", "idea", 70 + min(r["uses"], 99) / 10, {"tab": "journeys", "params": {}}, kind_of=r["kind"],
            key=r["key"], route=r["route"], uses=r["uses"], clicks=r["clicks_median"], screens=r["screens_median"])
    for p in [p for p in j["pairs"] if p["linked"]][:2]:
        add("pair_linked", "idea", 60 + p["share"] * 10, {"tab": "journeys", "params": {}}, a=p["a"], b=p["b"],
            share=p["share"], n=p["n"], clicks=p["clicks_median"], screens=p["screens_median"])
    if not f.q.get("account"):  # one account picked: its own drops are on the Accounts tab
        for r in engagement(con, f)["accounts"][:20]:
            for d in r["drops"]:
                link = {"tab": "accounts", "params": {"account": r["account"]}}
                if d["what"] == "users_day":
                    add("account_fading", "warn", 150 + (d["before"] - d["now"]) * 10, link, account=r["account"],
                        before=d["before"], now=d["now"])
                else:
                    add("account_feature_drop", "warn", 140 + min(d["before"] - d["now"], 99), link, account=r["account"],
                        feature=d["name"], before=d["before"], now=d["now"])
    insights.sort(key=lambda i: -i["weight"])
    return {"days": f.days, "now": totals(con, f), "before": totals(con, prev), "daily": daily(con, f),
            "before_daily": daily(con, prev), "deploys": deploys(con, f), "screens": screens_daily(con, f),
            "insights": insights[:15]}


def covered_days(con, f: Filter) -> float:
    """How many days of the window the project was sending (since its first event and the mark): the divisor of a
    per-day average, so a project that started last week is not averaged over a month."""
    first = con.execute("SELECT MIN(at) FROM events WHERE project = ? AND at >= ?", (f.q.get("project", ""), f.mark)).fetchone()[0]
    if first is None:
        return 0
    return max(0, f.until - max(f.since, first)) / 86400000


DROP = 0.6           # now at or below 60% of before is a drop...


def dropped(before: float, now: float) -> bool:
    """...and only when the fall is bigger than the usual ups and downs of counts that size (three Poisson deviations: many accounts times many features would otherwise cry wolf):
    22 → 11 uses in a small account is chance; 210 → 60 people-days is not."""
    return now <= before * DROP and before - now >= 3 * (before + now) ** 0.5
DROP_MIN_USERS = 2   # an account needs this many people a day before, for a drop of people to mean something
DROP_MIN_USES = 10   # and a feature this many uses in the period before


def engagement(con, f: Filter) -> dict:
    """Per account: people a day and sessions a day (averages over the days covered), and the uses of each watched
    feature, now against the period before; drops first. What tells a customer is fading before they say so."""
    prev = Filter(f.q, before=True)
    feats = list(FEATURES.get(f.q.get("project", ""), {}).values())
    days_now, days_before = covered_days(con, f), covered_days(con, prev)
    comparable = days_before >= max(1, days_now / 2)

    def per_account(fl, days):
        out = {}
        for account, users_days, sessions, visits in con.execute(f"""
                SELECT account, SUM(u), SUM(s), SUM(v)
                FROM (SELECT account, date(at / 1000, 'unixepoch') d, COUNT(DISTINCT NULLIF(user_id, '')) u,
                             COUNT(DISTINCT session) s, SUM(type = 'page') v
                      FROM events WHERE {fl.sql} AND account != '' GROUP BY account, d) GROUP BY account""", fl.args):
            out[account] = {"users_day": round(users_days / days, 1) if days else 0,
                            "sessions_day": round(sessions / days, 1) if days else 0, "users": 0, "visits": visits}
        for account, users in con.execute(f"""SELECT account, COUNT(DISTINCT NULLIF(user_id, '')) FROM events
                WHERE {fl.sql} AND account != '' GROUP BY account""", fl.args):
            out[account]["users"] = users
        for ft in feats:
            sql, args = feature_sql(ft["rules"], uses_only=True)
            for account, n in con.execute(f"SELECT account, COUNT(*) FROM events WHERE {fl.sql} AND account != '' AND {sql} GROUP BY account",
                                          fl.args + args):
                out.setdefault(account, {"users_day": 0, "sessions_day": 0, "users": 0, "visits": 0}).setdefault("features", {})[ft["id"]] = n
        return out

    now, before = per_account(f, days_now), per_account(prev, days_before)
    rows = []
    for account in set(now) | set(before):
        a, b = now.get(account, {}), before.get(account, {})
        drops = []
        if comparable and b.get("users_day", 0) >= DROP_MIN_USERS and dropped(b["users_day"] * days_now, a.get("users_day", 0) * days_now):
            drops.append({"what": "users_day", "before": b["users_day"], "now": a.get("users_day", 0)})
        feats_row = []
        for ft in feats:
            n, m = (a.get("features") or {}).get(ft["id"], 0), (b.get("features") or {}).get(ft["id"], 0)
            feats_row.append({"id": ft["id"], "now": n, "before": m if comparable else None})
            if comparable and m >= DROP_MIN_USES and dropped(m * days_now / days_before, n):
                drops.append({"what": "feature", "feature": ft["id"], "name": ft["name"], "before": m, "now": n})
        rows.append({"account": account, "now": {k: a.get(k, 0) for k in ("users_day", "sessions_day", "users", "visits")},
                     "before": {k: b.get(k, 0) for k in ("users_day", "sessions_day", "users", "visits")} if comparable else None,
                     "features": feats_row, "drops": drops})
    rows.sort(key=lambda r: (-len(r["drops"]), -r["now"]["visits"]))
    return {"days": f.days, "covered": round(days_now, 1), "comparable": comparable,
            "features": [{"id": x["id"], "name": x["name"]} for x in feats], "accounts": rows}


def account_daily(con, f: Filter) -> list[dict]:
    """People and sessions per day, and the uses of each watched feature per day: one account's pulse."""
    feats = list(FEATURES.get(f.q.get("project", ""), {}).values())
    # Every day of the window, the quiet ones too: a day nobody came is the news.
    first = con.execute(f"SELECT MIN(at) FROM events WHERE project = ? AND at >= ?", (f.q.get("project", ""), f.since)).fetchone()[0]
    start = datetime.datetime.fromtimestamp(max(f.since, first or f.until) / 1000, datetime.timezone.utc).date()  # SQLite days are UTC
    end = datetime.datetime.fromtimestamp(f.until / 1000, datetime.timezone.utc).date()
    days = {(start + datetime.timedelta(n)).isoformat(): {"day": (start + datetime.timedelta(n)).isoformat(), "users": 0, "sessions": 0,
                                                         "features": {}} for n in range((end - start).days + 1)}
    days.update({d: {"day": d, "users": u, "sessions": s, "features": {}} for d, u, s in con.execute(f"""
        SELECT date(at / 1000, 'unixepoch') d, COUNT(DISTINCT NULLIF(user_id, '')), COUNT(DISTINCT session) FROM events
        WHERE {f.sql} GROUP BY d ORDER BY d""", f.args)})
    for ft in feats:
        sql, args = feature_sql(ft["rules"], uses_only=True)
        for d, n in con.execute(f"SELECT date(at / 1000, 'unixepoch') d, COUNT(*) FROM events WHERE {f.sql} AND {sql} GROUP BY d",
                                f.args + args):
            if d in days:
                days[d]["features"][ft["id"]] = n
    return sorted(days.values(), key=lambda d: d["day"])


def features_report(con, f: Filter) -> dict:
    """Each watched feature in the period: its uses against the period before, who uses it (people, accounts, and
    the share of the people active in the product), its uses per day, how much it frustrates and fails."""
    project = f.q.get("project", "")
    prev = Filter(f.q, before=True)
    active = con.execute(f"SELECT COUNT(DISTINCT NULLIF(user_id, '')) FROM events WHERE {f.sql}", f.args).fetchone()[0]
    out = []
    for ft in FEATURES.get(project, {}).values():
        uses_sql, uses_args = feature_sql(ft["rules"], uses_only=True)
        scope_sql, scope_args = feature_sql(ft["rules"])
        n, users, accounts, first_at, first_version = con.execute(f"""SELECT COUNT(*), COUNT(DISTINCT NULLIF(user_id, '')),
            COUNT(DISTINCT NULLIF(account, '')), MIN(at), version FROM events WHERE {f.sql} AND {uses_sql}""", f.args + uses_args).fetchone()
        before = con.execute(f"SELECT COUNT(*) FROM events WHERE {prev.sql} AND {uses_sql}", prev.args + uses_args).fetchone()[0]
        points, fails = con.execute(f"""SELECT COALESCE(SUM({WEIGHT_CASE}), 0), COALESCE(SUM(type IN {FAILURES}), 0) FROM events
            WHERE {f.sql} AND {scope_sql}""", f.args + scope_args).fetchone()
        daily_uses = [{"day": d, "n": c} for d, c in con.execute(f"""SELECT date(at / 1000, 'unixepoch') d, COUNT(*) FROM events
            WHERE {f.sql} AND {uses_sql} GROUP BY d ORDER BY d""", f.args + uses_args)]
        out.append({**ft, "uses": n, "before": before, "users": users, "accounts": accounts,
                    "adoption": round(users / active, 2) if active else 0, "score": score(points, n), "failures": fails,
                    "daily": daily_uses})
    return {"days": f.days, "active_users": active, "features": out}


SEARCH_LIMIT = 8


def search(con, f: Filter) -> dict:
    """Screens, elements, failures, actions, users and accounts whose name contains the text, in the period."""
    text = f.q.get("q", "").strip().lower()[:100]
    if len(text) < 2:
        return {"q": text, "results": []}
    has = "instr(lower({}), ?) > 0"
    either = "(instr(lower({}), ?) > 0 OR instr(lower(label), ?) > 0)"  # the key or the name people use
    out = []
    for route, n in con.execute(f"""SELECT route, SUM(type = 'page') FROM events WHERE {f.sql} AND {either.format('route')}
            GROUP BY route ORDER BY 2 DESC LIMIT {SEARCH_LIMIT}""", f.args + [text, text]):
        out.append({"kind": "screen", "label": route, "n": n, "link": {"tab": "frustration", "params": {"route": route}}})
    for target, route, n in con.execute(f"""SELECT target, route, COUNT(*) FROM events
            WHERE {f.sql} AND type IN ('click', 'rage', 'dead') AND {either.format('target')}
            GROUP BY target, route ORDER BY 3 DESC LIMIT {SEARCH_LIMIT}""", f.args + [text, text]):
        out.append({"kind": "element", "label": target, "route": route, "n": n, "link": {"tab": "usage", "params": {"route": route}}})
    for kind, detail, route, n in con.execute(f"""SELECT type, detail, MIN(route), COUNT(*) FROM events
            WHERE {f.sql} AND type IN {FAILURES} AND {has.format('detail')}
            GROUP BY type, detail ORDER BY 4 DESC LIMIT {SEARCH_LIMIT}""", f.args + [text]):
        out.append({"kind": "failure", "type": kind, "label": detail, "route": route, "n": n,
                    "link": {"tab": "failures", "params": {"signal": kind, "detail": detail}}})
    for detail, n in con.execute(f"""SELECT detail, COUNT(*) FROM events WHERE {f.sql} AND type = 'action'
            AND {either.format('detail')} GROUP BY detail ORDER BY 2 DESC LIMIT {SEARCH_LIMIT}""", f.args + [text, text]):
        out.append({"kind": "action", "label": detail, "n": n, "link": {"tab": "actions", "params": {"action": detail}}})
    for column, kind, param in (("user_id", "user", "user"), ("account", "account", "account")):
        for value, n in con.execute(f"""SELECT {column}, SUM(type = 'page') FROM events WHERE {f.sql} AND {column} != ''
                AND {has.format(column)} GROUP BY {column} ORDER BY 2 DESC LIMIT {SEARCH_LIMIT}""", f.args + [text]):
            out.append({"kind": kind, "label": value, "n": n, "link": {"tab": "people" if kind == "user" else "overview",
                                                                      "params": {param: value}}})
    return {"q": text, "results": out}


FAILURE_WEIGHT = {"js_error": 5, "http_5xx": 5, "http_4xx": 2, "slow": 1}


def first_seen(con, f: Filter) -> dict:
    """(type, detail) -> (first time, its version), over everything still kept since the mark: when a failure started."""
    return {(k, d): (at, v) for k, d, at, v in con.execute(
        f"""SELECT type, detail, MIN(at), version FROM events WHERE project = ? AND at >= ? AND type IN {FAILURES}
            GROUP BY type, detail""", (f.q.get("project", ""), f.mark))}


def failures(con, f: Filter) -> dict:
    """Every failure of the period, grouped by kind and message, the ones that hit the most people first."""
    first = first_seen(con, f)
    rows = con.execute(f"""
        SELECT type, detail, COUNT(*), COUNT(DISTINCT session), COUNT(DISTINCT NULLIF(user_id, '')), MAX(at), version,
               COUNT(DISTINCT route), MIN(route)
        FROM events WHERE {f.sql} AND type IN {FAILURES} GROUP BY type, detail""", f.args).fetchall()
    out = []
    for kind, detail, n, sessions, users, last_at, last_version, routes, route in rows:
        first_at, first_version = first.get((kind, detail), (last_at, last_version))
        out.append({"type": kind, "detail": detail, "n": n, "sessions": sessions, "users": users, "routes": routes,
                    "route": route, "first_at": first_at, "first_version": first_version, "last_at": last_at,
                    "last_version": last_version, "new": first_at >= f.since})
    out.sort(key=lambda x: (-x["sessions"] * FAILURE_WEIGHT[x["type"]], -x["n"]))
    return {"failures": out}


STEP = "type, route, target, detail, at, version, clicks, duration_ms"


def steps(rows) -> list[dict]:
    return [{"type": k, "route": r, "target": t, "detail": d, "at": at, "version": v, "clicks": c, "duration_ms": ms}
            for k, r, t, d, at, v, c, ms in rows]


def failure(con, f: Filter) -> dict:
    """One failure in depth: where, in which versions, browsers and kinds of screen, the code stack, what was
    clicked just before, and the trail of a few sessions up to it — what a developer needs to reproduce it."""
    kind, detail = f.q.get("signal", ""), f.q.get("detail", "")
    where, args = f"{f.sql} AND type = ? AND detail = ?", f.args + [kind, detail]

    def count_by(column, limit=10):
        return [{"key": k, "n": n} for k, n in con.execute(
            f"SELECT {column}, COUNT(*) n FROM events WHERE {where} GROUP BY {column} ORDER BY n DESC LIMIT {limit}", args)]

    n, sessions, users, accounts, last_at = con.execute(f"""
        SELECT COUNT(*), COUNT(DISTINCT session), COUNT(DISTINCT NULLIF(user_id, '')), COUNT(DISTINCT NULLIF(account, '')),
               MAX(at) FROM events WHERE {where}""", args).fetchone()
    if not n:
        return {"type": kind, "detail": detail, "n": 0}
    first_at, first_version = first_seen(con, f).get((kind, detail), (None, ""))
    # The latest occurrence of each session (SQLite gives the bare columns of the MAX row), newest sessions first.
    samples = con.execute(f"""SELECT id, session, MAX(at), version, user_id, account, role, agent, device FROM events
        WHERE {where} GROUP BY session ORDER BY MAX(at) DESC LIMIT {TRAIL_SAMPLES}""", args).fetchall()
    trails = []
    for eid, session, at, version, user, account, role, agent, device in samples:
        project = f.q.get("project", "")
        before = con.execute(f"""SELECT {STEP} FROM events WHERE project = ? AND session = ? AND (at, id) < (?, ?)
            ORDER BY at DESC, id DESC LIMIT {TRAIL_BEFORE}""", (project, session, at, eid)).fetchall()[::-1]
        after = con.execute(f"""SELECT {STEP} FROM events WHERE project = ? AND session = ? AND (at, id) > (?, ?)
            ORDER BY at, id LIMIT {TRAIL_AFTER}""", (project, session, at, eid)).fetchall()
        here = con.execute(f"SELECT {STEP} FROM events WHERE id = ?", (eid,)).fetchall()
        trails.append({"session": session, "at": at, "version": version, "user": user, "account": account, "role": role,
                       "agent": agent, "device": device, "before": steps(before), "failure": steps(here)[0],
                       "after": steps(after)})
    return {"type": kind, "detail": detail, "n": n, "sessions": sessions, "users": users, "accounts": accounts,
            "first_at": first_at, "first_version": first_version, "last_at": last_at, "new": (first_at or 0) >= f.since,
            "routes": count_by("route"), "versions": count_by("version"), "agents": count_by("agent"),
            "devices": count_by("device"), "after_clicking": [x for x in count_by("target", 5) if x["key"]],
            "stacks": [x for x in count_by("stack", 3) if x["key"]],
            "per_day": [{"day": d, "n": c} for d, c in con.execute(
                f"SELECT date(at / 1000, 'unixepoch') d, COUNT(*) FROM events WHERE {where} GROUP BY d ORDER BY d", args)],
            "trails": trails}


def session_trail(con, f: Filter) -> dict:
    """Everything one session did, in order (up to SESSION_MAX steps): ids of who it was, never content."""
    project, session = f.q.get("project", ""), f.q.get("session", "")
    rows = con.execute(f"SELECT {STEP} FROM events WHERE project = ? AND session = ? ORDER BY at, id LIMIT {SESSION_MAX}",
                       (project, session)).fetchall()
    who = con.execute("""SELECT user_id, account, role, agent, device FROM events WHERE project = ? AND session = ?
        ORDER BY at DESC LIMIT 1""", (project, session)).fetchone() or ("", "", "", "", "")
    return {"session": session, "user": who[0], "account": who[1], "role": who[2], "agent": who[3], "device": who[4],
            "steps": steps(rows), "truncated": len(rows) == SESSION_MAX}


MAX_JOURNEY_ROWS = 500_000
SCREEN_CAP_MS = 30 * 60 * 1000  # longer than this on one screen is a tab left open, not reading
FAR_CLICKS, FAR_SCREENS, FAR_USES = 5, 2, 10
PAIR_MIN, PAIR_SHARE = 5, 0.3
EXIT = "(exit)"


def session_rows(con, f: Filter, types=("page", "click", "action")):
    """The period's events of these types, session by session, in the order they happened."""
    marks = ",".join("?" * len(types))
    rows = con.execute(f"""SELECT session, type, route, target, detail, at, clicks, user_id FROM events
        WHERE {f.sql} AND type IN ({marks}) ORDER BY session, at, id LIMIT {MAX_JOURNEY_ROWS}""", f.args + list(types))
    current, steps = None, []
    for row in rows:
        if row[0] != current:
            if steps:
                yield current, steps
            current, steps = row[0], []
        steps.append(row[1:])
    if steps:
        yield current, steps


def median(values):
    return statistics.median(values) if values else 0


def journeys(con, f: Filter) -> dict:
    """How people move: time on each screen and where they come from and go to; how far (clicks and screens since
    the last saved action, or the start of the session) each element and action is, against how much it is used;
    and which actions tend to follow one another."""
    screens: dict[str, dict] = {}
    reach: dict[tuple, dict] = {}
    pairs: dict[tuple, dict] = {}
    action_count: dict[str, int] = {}
    for _, steps in session_rows(con, f):
        clicks = screens_passed = 0
        last_page = None
        last_action = None  # (detail, screens passed since it)
        for kind, route, target, detail, at, n_clicks, user in steps:
            if kind == "page":
                here = screens.setdefault(route, {"ms": [], "from": {}, "to": {}})
                if last_page:
                    s = screens[last_page[0]]
                    s["ms"].append(min(at - last_page[1], SCREEN_CAP_MS))
                    s["to"][route] = s["to"].get(route, 0) + 1
                    here["from"][last_page[0]] = here["from"].get(last_page[0], 0) + 1
                last_page = (route, at)
                screens_passed += 1
                continue
            key = ("element", route, target) if kind == "click" else ("action", route, detail)
            r = reach.setdefault(key, {"clicks": [], "screens": [], "users": set()})
            # For a click, the clicks before it; for an action, the collector already counted its clicks.
            r["clicks"].append(clicks if kind == "click" else (n_clicks or 0))
            r["screens"].append(max(screens_passed - 1, 0))
            if user:
                r["users"].add(user)
            if kind == "click":
                clicks += 1
                continue
            action_count[detail] = action_count.get(detail, 0) + 1
            if last_action:
                p = pairs.setdefault((last_action[0], detail), {"clicks": [], "screens": []})
                p["clicks"].append(n_clicks or 0)
                p["screens"].append(max(screens_passed - 1, 0))
            last_action = (detail,)
            clicks, screens_passed = 0, 1
        if last_page:
            s = screens[last_page[0]]
            s["to"][EXIT] = s["to"].get(EXIT, 0) + 1

    def top(d, total):
        return [{"route": k, "n": n, "share": round(n / total, 2) if total else 0}
                for k, n in sorted(d.items(), key=lambda kv: -kv[1])[:8]]

    out_screens = []
    for route, s in screens.items():
        arrivals, leaves = sum(s["from"].values()), sum(s["to"].values())
        out_screens.append({"route": route, "visits": leaves, "seconds_median": round(median(s["ms"]) / 1000, 1),
                            "from": top(s["from"], arrivals), "to": top(s["to"], leaves)})
    out_screens.sort(key=lambda s: -s["visits"])
    out_reach = []
    for (kind, route, key), r in reach.items():
        uses = len(r["clicks"])
        c, sc = median(r["clicks"]), median(r["screens"])
        out_reach.append({"kind": kind, "key": key, "route": route, "uses": uses, "users": len(r["users"]),
                          "clicks_median": c, "screens_median": sc,
                          "far": uses >= FAR_USES and (c >= FAR_CLICKS or sc >= FAR_SCREENS)})
    out_reach.sort(key=lambda r: -r["uses"] * (r["clicks_median"] + 2 * r["screens_median"]))
    out_pairs = []
    for (a, b), p in pairs.items():
        n = len(p["clicks"])
        share = n / action_count[a] if action_count.get(a) else 0
        if n >= PAIR_MIN:
            out_pairs.append({"a": a, "b": b, "n": n, "share": round(share, 2), "clicks_median": median(p["clicks"]),
                              "screens_median": median(p["screens"]), "linked": share >= PAIR_SHARE})
    out_pairs.sort(key=lambda p: (-p["share"], -p["n"]))
    return {"screens": out_screens, "reach": out_reach[:100], "pairs": out_pairs[:50]}


def funnel(con, f: Filter) -> dict:
    """Sessions that went through the steps in order (other things in between are fine). A step is
    `page:<route>`, `action:<detail>` or `click:<target>`."""
    try:
        wanted = [s for s in json.loads(f.q.get("steps", "[]")) if isinstance(s, str) and ":" in s][:8]
    except ValueError:
        wanted = []
    if not wanted:
        return {"steps": []}
    reached = [0] * len(wanted)
    for _, steps in session_rows(con, f):
        i = 0
        for kind, route, target, detail, *_ in steps:
            want_kind, _, want = wanted[i].partition(":")
            value = {"page": route, "action": detail, "click": target}[kind]
            if kind == want_kind and value == want:
                reached[i] += 1
                i += 1
                if i == len(wanted):
                    break
    return {"steps": [{"step": s, "sessions": n, "share": round(n / reached[0], 2) if reached[0] else 0}
                      for s, n in zip(wanted, reached)]}


GLOSSARY = {
    "signals": {
        "rage": "3 clicks on the same spot within 1 s",
        "dead": "a click on a button or link that changed nothing (no DOM change, request or navigation) within 1 s",
        "js_error": "an uncaught JavaScript error or rejected promise",
        "http_5xx": "a request answered with 5xx, or a network failure",
        "http_4xx": "a request refused with 4xx (401 is left out)",
        "abandon": "started filling a form or dialog and left the screen without saving",
        "bounce": "went back within 4 s of arriving",
        "slow": "a request that took 3 s or more while the page was in front of the user",
    },
    "usage": {
        "page": "a visit to a screen (route pattern, ids as :id)",
        "click": "any click, with the element's CSS selector",
        "action": "a write (POST/PUT/PATCH/DELETE) the backend accepted after at least one click, with the clicks and time "
                  "since the previous one (or since 2 idle minutes)",
    },
    "score": f"per screen: sum of signal weights / visits x {FACTOR}, capped at {CAP}. 0-19 calm, 20-49 attention, 50+ very "
             "frustrating. Weights: " + ", ".join(f"{k} {w}" for k, w in WEIGHTS.items()),
    "reach": "clicks and screens since the last saved action (or the start of the session) until a button or action is "
             f"used. 'far' = used {FAR_USES}+ times and a median of {FAR_CLICKS}+ clicks or {FAR_SCREENS}+ screens.",
    "pairs": f"action B right after action A in the same session; share = how often A is followed by B. 'linked' = {PAIR_SHARE:.0%}+.",
    "privacy": "No text the user typed or saw is collected: only signal kinds, route patterns, element selectors, request "
               "method and path with ids replaced, error messages scrubbed of numbers, e-mails and quoted text, and opaque "
               "ids for account, user and role.",
}


def report(con, f: Filter) -> dict:
    """Everything worth knowing about the period in one document, with the definitions needed to read it: what an
    AI (or a person) needs to find the problems and suggest improvements without opening the dashboard."""
    project = f.q.get("project", "")
    o = overview(con, f)
    s = summary(con, f)
    fl = failures(con, f)["failures"]
    j = journeys(con, f)
    deep = []
    for x in fl[:5]:
        d = failure(con, Filter({**f.q, "signal": x["type"], "detail": x["detail"]}))
        d["trails"] = d["trails"][:2]
        deep.append(d)
    screens = usage(con, f)["screens"]
    never = {}
    for sc in screens[:10]:
        u = usage(con, Filter({**f.q, "route": sc["route"]}))
        never[sc["route"]] = {"elements": u["elements"][:15], "never_clicked": u["never_clicked"][:30]}
    p = people(con, f)
    c = compare(con, Filter({k: v for k, v in f.q.items() if k != "version"}))
    return {
        "termometro": VERSION, "project": project, "days": f.days,
        "filters": {k: f.q[k] for k in ("version", "account", "role", "user") if f.q.get(k)},
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "glossary": GLOSSARY,
        "overview": o, "screens_by_frustration": s["routes"][:30], "versions": s["versions"],
        "failures": fl[:30], "failures_in_depth": deep,
        "usage": {"screens": screens[:40], "elements_per_screen": never},
        "effort_per_action": actions(con, f)["actions"][:40],
        "journeys": {"far": [r for r in j["reach"] if r["far"]][:20], "pairs": j["pairs"][:20], "screens": j["screens"][:25]},
        "people": {"roles": p["roles"][:20], "accounts": p["accounts"][:20], "identified_users": len(p["users"])},
        "latest_version_vs_previous": {k: c[k] for k in ("a", "b", "overall", "new_failures")} | {"routes": c["routes"][:20]},
    }


def report_markdown(r: dict) -> str:
    """The report as text a person can read and an AI can take in one paste."""
    r = json.loads(json.dumps(r).replace("|", "\\\\|"))  # a pipe in a selector or a message would break the tables
    out = [f"# Termometro report — {r['project']}, last {r['days']} days",
           f"Generated {r['generated_at']} by Termometro {r['termometro']}."
           + (f" Filters: {', '.join(f'{k}={v}' for k, v in r['filters'].items())}." if r["filters"] else ""), ""]
    g = r["glossary"]
    out += ["## How to read this", f"- Score: {g['score']}", f"- Reach: {g['reach']}", f"- Pairs: {g['pairs']}",
            "- Signals: " + "; ".join(f"**{k}** {v}" for k, v in g["signals"].items()),
            "- Usage: " + "; ".join(f"**{k}** {v}" for k, v in g["usage"].items()), f"- Privacy: {g['privacy']}", ""]
    n, b = r["overview"]["now"], r["overview"]["before"]
    out += ["## Overview (this period vs the one before)", "| | now | before |", "|---|---|---|"]
    out += [f"| {k} | {n[k]} | {b[k]} |" for k in ("score", "visits", "sessions", "users", "failures")]
    out += ["", "Score per day: " + ", ".join(f"{d['day']} {d['score']} ({d['visits']} visits)" for d in r["overview"]["daily"]), ""]
    def fact(k, v):
        return f"{k}={time.strftime('%Y-%m-%d %H:%M', time.gmtime(v / 1000))} UTC" if k.endswith("_at") and v else f"{k}={v}"
    out += ["### What deserves a look"] + [f"- [{i['severity']}] {i['kind']}: " + ", ".join(
        fact(k, v) for k, v in i.items() if k not in ("kind", "severity", "weight", "link")) for i in r["overview"]["insights"]] + [""]
    out += ["## Screens by frustration", "| screen | score | visits | signals | where | what failed |", "|---|---|---|---|---|---|"]
    for x in r["screens_by_frustration"]:
        out.append(f"| {x['key']} | {x['score']} | {x['visits']} | " + ", ".join(f"{k} {v}" for k, v in x["signals"].items())
                   + " | " + "; ".join(f"{t['type']} on `{t['target']}` {t['n']}x" for t in x["targets"])
                   + " | " + "; ".join(f"{t['type']} `{t['detail']}` {t['n']}x" for t in x["failures"]) + " |")
    out += ["", "## Failures", "| kind | message | times | sessions | users | first version | new |", "|---|---|---|---|---|---|---|"]
    out += [f"| {x['type']} | `{x['detail']}` | {x['n']} | {x['sessions']} | {x['users']} | {x['first_version']} | {x['new']} |"
            for x in r["failures"]]
    for d in r["failures_in_depth"]:
        if not d.get("n"):
            continue
        names = lambda xs: ", ".join(f"{x['key'] or '?'} ({x['n']})" for x in xs)
        out += ["", f"### {d['type']}: `{d['detail']}`", f"- screens: {names(d['routes'])}", f"- versions: {names(d['versions'])}",
                f"- browsers: {names(d['agents'])}", f"- kinds of screen: {names(d['devices'])}"]
        if d["after_clicking"]:
            out.append(f"- right after clicking: {names(d['after_clicking'])}")
        if d["stacks"]:
            out += ["```", d["stacks"][0]["key"], "```"]
        for t in d["trails"][:1]:
            out.append(f"Steps up to it (session {t['session'][:8]}, {t['agent']}, {t['device']}, {t['version']}):")
            for st in t["before"] + [t["failure"]]:
                out.append(f"  {round((st['at'] - t['at']) / 1000)}s {st['type']} {st['route']} {st['target'] or ''} {st['detail'] or ''}".rstrip())
    out += ["", "## Effort per action", "| action | times | users | clicks median | clicks p90 | seconds median | seconds p90 |",
            "|---|---|---|---|---|---|---|"]
    out += [f"| `{a['action']}` | {a['times']} | {a['users']} | {a['clicks_median']} | {a['clicks_p90']} | {a['seconds_median']} | "
            f"{a['seconds_p90']} |" for a in r["effort_per_action"]]
    jn = r["journeys"]
    out += ["", "## Journeys", "### Used a lot and far away", "| kind | item | screen | uses | users | clicks to reach | screens on the way |",
            "|---|---|---|---|---|---|---|"]
    out += [f"| {x['kind']} | `{x['key']}` | {x['route']} | {x['uses']} | {x['users']} | {x['clicks_median']} | {x['screens_median']} |"
            for x in jn["far"]]
    out += ["", "### Actions that follow one another"]
    out += [f"- after `{p['a']}` comes `{p['b']}` {round(p['share'] * 100)}% of the time ({p['n']}x), {p['clicks_median']} clicks and "
            f"{p['screens_median']} screens between them" for p in jn["pairs"]]
    out += ["", "### Screen to screen", "| screen | visits | median seconds | comes from | goes to |", "|---|---|---|---|---|"]
    flow = lambda xs: ", ".join(f"{x['route']} {round(x['share'] * 100)}%" for x in xs[:4])
    out += [f"| {x['route']} | {x['visits']} | {x['seconds_median']} | {flow(x['from'])} | {flow(x['to'])} |" for x in jn["screens"]]
    out += ["", "## Usage", "| screen | visits | clicks | users | score |", "|---|---|---|---|---|"]
    out += [f"| {x['route']} | {x['visits']} | {x['clicks']} | {x['users']} | {x['score']} |" for x in r["usage"]["screens"]]
    for route, e in r["usage"]["elements_per_screen"].items():
        out.append(f"- {route}: most clicked " + ", ".join(f"`{x['target']}` {x['clicks']}" for x in e["elements"][:8])
                   + (f"; never clicked: " + ", ".join(f"`{t}`" for t in e["never_clicked"][:15]) if e["never_clicked"] else ""))
    pp = r["people"]
    out += ["", "## People", f"Identified users: {pp['identified_users']}.", "| role | users | visits | score |", "|---|---|---|---|"]
    out += [f"| {x['key']} | {x['users']} | {x['visits']} | {x['score']} |" for x in pp["roles"]]
    v = r["latest_version_vs_previous"]
    if v["a"] and v["b"]:
        out += ["", f"## Version {v['b']} against {v['a']}", f"Overall score {v['overall']['a']['score']} → {v['overall']['b']['score']}."]
        out += [f"- {x['route']}: {x['a']['score']} → {x['b']['score']} ({'+' if x['delta'] > 0 else ''}{x['delta']})"
                for x in v["routes"] if x["delta"]]
        out += [f"- new failure: {x['type']} `{x['detail']}` on {x['route']} ({x['n']}x)" for x in v["new_failures"]]
    out += ["", "## What to do with this",
            "Find the problems that hurt the most people, tell bugs (failures with stack and steps) from design problems "
            "(frustration, effort, reach, pairs, never clicked), and suggest concrete changes, each tied to the numbers above."]
    return "\n".join(out) + "\n"


SHARED_NAME = 3  # a screen name seen on this many routes is the app's name in the title, not the screen's


def names(con, project: str) -> dict:
    """What people call things, as the collector saw them: screens by route, controls by route and selector, actions
    by request. The most common label wins; the technical key always stays next to it in the dashboard."""
    def most_common(rows):
        best: dict = {}
        for key, label, n in rows:
            if label and n > best.get(key, ("", 0))[1]:
                best[key] = (label, n)
        return {k: v[0] for k, v in best.items()}

    screens = most_common(con.execute("""SELECT route, label, COUNT(*) FROM events WHERE project = ? AND type = 'page'
        AND label != '' GROUP BY route, label""", (project,)))
    shared = {n for n in set(screens.values()) if list(screens.values()).count(n) >= SHARED_NAME}
    screens = {r: n for r, n in screens.items() if n not in shared}
    controls = most_common(con.execute("""SELECT route || char(9) || target, label, COUNT(*) FROM events WHERE project = ?
        AND type IN ('click', 'rage', 'dead') AND label != '' GROUP BY route, target, label""", (project,)))
    for route, target, label in con.execute("SELECT route, target, label FROM elements WHERE project = ? AND label != ''", (project,)):
        controls.setdefault(route + "\t" + target, label)
    actions = most_common(con.execute("""SELECT detail, label, COUNT(*) FROM events WHERE project = ? AND type = 'action'
        AND label != '' GROUP BY detail, label""", (project,)))
    out = {"screens": screens, "controls": controls, "actions": actions, "accounts": {},
           "features": [{"id": x["id"], "name": x["name"], "rules": x["rules"]} for x in FEATURES.get(project, {}).values()],
           "auto": {"screens": dict(screens), "controls": dict(controls), "actions": dict(actions)}}
    # What the product team wrote in the dictionary wins over what the collector saw.
    for kind, key, name in con.execute("SELECT kind, key, name FROM dictionary WHERE project = ?", (project,)):
        out[DICTIONARY[kind]][key] = name
    return out


def dictionary(con, project: str) -> dict:
    """Everything that can be named, over everything kept: its key, what the collector calls it, what the dictionary
    says, and how much it is used, the most used first. Controls include the ones without a label (icons)."""
    n = names(con, project)
    custom = {(k, key): name for k, key, name in con.execute("SELECT kind, key, name FROM dictionary WHERE project = ?", (project,))}

    def item(kind, key, auto, used, **extra):
        return {"key": key, "auto": auto, "name": custom.get((kind, key), ""), "used": used, **extra}
    screens = [item("screen", r, n["auto"]["screens"].get(r, ""), v) for r, v in con.execute(
        "SELECT route, SUM(type = 'page') v FROM events WHERE project = ? GROUP BY route ORDER BY v DESC LIMIT 500", (project,))]
    used = dict(((r + "\t" + t), c) for r, t, c in con.execute("""SELECT route, target, COUNT(*) FROM events WHERE project = ?
        AND type = 'click' AND target != '' GROUP BY route, target""", (project,)))
    keys = set(used) | {r + "\t" + t for r, t in con.execute("SELECT route, target FROM elements WHERE project = ?", (project,))}
    controls = sorted((item("control", k, n["auto"]["controls"].get(k, ""), used.get(k, 0), route=k.split("\t")[0],
                            target=k.split("\t", 1)[1]) for k in keys), key=lambda x: -x["used"])[:1000]
    actions = [item("action", d, n["auto"]["actions"].get(d, ""), c) for d, c in con.execute(
        "SELECT detail, COUNT(*) c FROM events WHERE project = ? AND type = 'action' GROUP BY detail ORDER BY c DESC LIMIT 500", (project,))]
    accounts = [item("account", a, "", v, users=u) for a, v, u in con.execute("""SELECT account, SUM(type = 'page') v,
        COUNT(DISTINCT NULLIF(user_id, '')) FROM events WHERE project = ? AND account != '' GROUP BY account ORDER BY v DESC LIMIT 1000""",
        (project,))]
    return {"screens": screens, "controls": controls, "actions": actions, "accounts": accounts}


DICTIONARY = {"screen": "screens", "control": "controls", "action": "actions", "account": "accounts"}
MAX_NAME = 80


def name_thing(con, project: str, kind: str, key: str, name: str) -> None:
    """The dictionary: a screen (route), control (route TAB selector), action (request) or account (id) gets the
    name people use; an empty name gives it back to what the collector saw. An account's name stays on this server."""
    if kind not in DICTIONARY or not key or len(key) > 400:
        raise ValueError("kind or key")
    name = " ".join(str(name).split())[:MAX_NAME]
    if name:
        con.execute("INSERT OR REPLACE INTO dictionary (project, kind, key, name, at) VALUES (?, ?, ?, ?, ?)",
                    (project, kind, key, name, int(time.time() * 1000)))
    else:
        con.execute("DELETE FROM dictionary WHERE project = ? AND kind = ? AND key = ?", (project, kind, key))


def filters(con, project: str) -> dict:
    def distinct(column):
        return [v for (v,) in con.execute(
            f"SELECT DISTINCT {column} FROM events WHERE project = ? AND {column} != '' ORDER BY {column}", (project,))]
    return {"accounts": distinct("account"), "roles": distinct("role"), "versions": distinct("version")}


def apply_retention(con, now: float | None = None) -> int:
    """Events older than the retention become id-less daily totals and leave. Returns how many left."""
    cutoff = int(((now or time.time()) - CONFIG.retention_days * 86400) * 1000)
    con.execute("""
        INSERT INTO history (day, project, version, route, type, n)
        SELECT date(at / 1000, 'unixepoch'), project, version, route, type, COUNT(*)
        FROM events WHERE at < ? GROUP BY 1, 2, 3, 4, 5
        ON CONFLICT (day, project, version, route, type) DO UPDATE SET n = n + excluded.n""", (cutoff,))
    removed = con.execute("DELETE FROM events WHERE at < ?", (cutoff,)).rowcount
    con.execute("DELETE FROM elements WHERE last_seen < ?", (cutoff,))
    return removed


def daily_retention():
    while True:
        try:
            with connect() as con:
                removed = apply_retention(con)
            if removed:
                print(f"retention: {removed} events became totals", flush=True)
        except sqlite3.Error as error:
            print(f"retention failed: {error}", flush=True)
        time.sleep(86400)


ALERT_TEXT = {
    "en": {"title": "Termometro · {project} {b} got worse than {a}", "screen": "• {route}: score {sa} → {sb} ({visits} visits)",
           "failure": "• New failure on {route}: {detail} ({n}×)"},
    "pt": {"title": "Termometro · {project} {b} piorou em relação à {a}", "screen": "• {route}: nota {sa} → {sb} ({visits} visitas)",
           "failure": "• Falha nova em {route}: {detail} ({n}×)"},
}


def regressions(con, project: str) -> tuple[str, str, list[tuple[str, str]]]:
    """What the latest version made worse than the one before: (a, b, [(key, line)]). Only screens with enough
    visits in both, and only failures the previous version never had that already repeated."""
    c = compare(con, Filter({"project": project, "days": str(CONFIG.retention_days)}))
    text = ALERT_TEXT[CONFIG.language]
    found = []
    for r in c["routes"]:
        if (r["delta"] or 0) >= ALERT_RISE and r["a"]["visits"] >= ALERT_MIN_VISITS and r["b"]["visits"] >= ALERT_MIN_VISITS:
            found.append(("screen " + r["route"], text["screen"].format(
                route=r["route"], sa=r["a"]["score"], sb=r["b"]["score"], visits=r["b"]["visits"])))
    for x in c["new_failures"]:
        if x["type"] in ("js_error", "http_5xx") and x["n"] >= ALERT_MIN_NEW:
            found.append((f"failure {x['type']} {x['detail']}", text["failure"].format(**x)))
    return c["a"], c["b"], found


def post_webhook(url: str, message: str) -> bool:
    """Slack and Google Chat incoming webhooks both take {"text": ...}."""
    req = urllib.request.Request(url, data=json.dumps({"text": message}).encode(),
                                 headers={"Content-Type": "application/json; charset=utf-8"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return 200 <= r.status < 300
    except OSError as error:
        print(f"webhook failed: {error}", flush=True)
        return False


def check_alerts(con, send=post_webhook) -> int:
    """Warns each project's webhook once about each regression of its latest version. Returns how many went out;
    a warning that failed to go out is tried again on the next check."""
    sent = 0
    for project in CONFIG.projects.values():
        if not project["webhook"]:
            continue
        a, b, found = regressions(con, project["name"])
        fresh = [(k, line) for k, line in found if not con.execute(
            "SELECT 1 FROM alerts WHERE project = ? AND version = ? AND key = ?", (project["name"], b, k)).fetchone()]
        if not fresh:
            continue
        lines = [ALERT_TEXT[CONFIG.language]["title"].format(project=project["name"], a=a, b=b)] + [line for _, line in fresh]
        if CONFIG.public_url:
            lines.append(CONFIG.public_url + "/#versions")
        if send(project["webhook"], "\n".join(lines)):
            now = int(time.time() * 1000)
            con.executemany("INSERT OR IGNORE INTO alerts (project, version, key, at) VALUES (?, ?, ?, ?)",
                            [(project["name"], b, k, now) for k, _ in fresh])
            sent += len(fresh)
    return sent


def hourly_alerts():
    while True:
        time.sleep(ALERT_EVERY)
        try:
            with connect() as con:
                check_alerts(con)
        except sqlite3.Error as error:
            print(f"alerts failed: {error}", flush=True)


def google_email(code: str) -> str:
    """Trades the code for an ID token and returns its verified e-mail. The token comes straight from Google's
    token endpoint over TLS, so its signature does not need checking here — the claims still do."""
    body = urllib.parse.urlencode({
        "code": code, "client_id": CONFIG.google_id, "client_secret": CONFIG.google_secret,
        "redirect_uri": CONFIG.public_url + "/auth/google/callback", "grant_type": "authorization_code"}).encode()
    with urllib.request.urlopen(urllib.request.Request(GOOGLE_TOKEN_URL, data=body), timeout=10) as r:
        id_token = json.loads(r.read())["id_token"]
    claims = json.loads(base64.urlsafe_b64decode(id_token.split(".")[1] + "=="))
    if claims.get("aud") != CONFIG.google_id or claims.get("iss") not in ("https://accounts.google.com", "accounts.google.com"):
        raise ValueError("token not meant for this client")
    if int(claims.get("exp", 0)) <= time.time() or not claims.get("email_verified") or not claims.get("email"):
        raise ValueError("expired token or unverified e-mail")
    return str(claims["email"])


def engagement_read(con, f: Filter) -> dict:
    out = engagement(con, f)
    if f.q.get("account"):
        out["daily"] = account_daily(con, f)
    return out


READS = {"/api/features": features_report, "/api/engagement": engagement_read, "/api/summary": summary, "/api/usage": usage, "/api/people": people, "/api/actions": actions,
         "/api/compare": compare, "/api/overview": overview, "/api/search": search, "/api/failures": failures,
         "/api/failure": failure, "/api/session": session_trail, "/api/journeys": journeys, "/api/funnel": funnel,
         "/api/report": report}
STATIC_FILES = {"/": ("index.html", "text/html; charset=utf-8"),
                "/map.js": ("map.js", "text/javascript; charset=utf-8"),
                "/termometro.js": ("termometro.js", "text/javascript; charset=utf-8"),
                "/termometro_mcp.py": ("termometro_mcp.py", "text/x-python; charset=utf-8")}


class Handler(BaseHTTPRequestHandler):
    server_version = f"termometro/{VERSION}"

    def log_message(self, fmt, *args):  # a line per batch would be noise; errors are printed where they happen
        pass

    def ip(self) -> str:
        return self.client_address[0]

    def send(self, status: int, body: bytes = b"", content_type="application/json; charset=utf-8", headers=None):
        self.send_response(status)
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        if body:
            self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        if body and self.command != "HEAD":
            self.wfile.write(body)

    def json(self, status: int, data, headers=None):
        self.send(status, json.dumps(data, ensure_ascii=False).encode(), headers=headers)

    def body(self) -> bytes:
        size = int(self.headers.get("Content-Length") or 0)
        if size <= 0 or size > MAX_BODY:
            raise ValueError("size")
        return self.rfile.read(size)

    def cookie(self, name: str) -> str:
        for part in (self.headers.get("Cookie") or "").split(";"):
            k, _, v = part.strip().partition("=")
            if k == name:
                return v
        return ""

    def session(self) -> dict | None:
        """The signed-in person, from the session cookie: s.<expiry>.<e-mail, base64; empty for the password>."""
        if CONFIG.no_auth:
            return {"email": ""}
        auth = self.headers.get("Authorization", "")
        if auth.startswith("Bearer ") and any(hmac.compare_digest(auth[7:].encode(), t.encode()) for t in CONFIG.api_tokens):
            return {"email": "api"}
        payload = verify(self.cookie("termometro_session"))
        parts = payload.split(".") if payload else []
        if len(parts) != 3 or parts[0] != "s" or not parts[1].isdigit() or int(parts[1]) <= time.time():
            return None
        return {"email": base64.urlsafe_b64decode(parts[2] + "==").decode() if parts[2] else ""}

    def signed_in(self) -> bool:
        return self.session() is not None

    def session_cookie(self, email: str) -> str:
        mark = base64.urlsafe_b64encode(email.encode()).decode().rstrip("=")
        token = sign(f"s.{int(time.time()) + SESSION_SECONDS}.{mark}")
        return f"termometro_session={token}; Path=/; Max-Age={SESSION_SECONDS}; HttpOnly; SameSite=Strict{self.secure()}"

    def secure(self) -> str:
        https = self.headers.get("X-Forwarded-Proto") == "https" or CONFIG.public_url.startswith("https://")
        return "; Secure" if https else ""

    def redirect(self, location: str, cookies: list[str] = ()):
        self.send_response(302)
        self.send_header("Location", location)
        for c in cookies:
            self.send_header("Set-Cookie", c)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def google_start(self):
        state = secrets.token_urlsafe(16)
        params = urllib.parse.urlencode({
            "client_id": CONFIG.google_id, "redirect_uri": CONFIG.public_url + "/auth/google/callback",
            "response_type": "code", "scope": "openid email", "state": state, "prompt": "select_account"})
        # SameSite=Lax: this cookie has to come back on Google's redirect, a cross-site navigation.
        cookie = f"termometro_oauth={sign('o.' + state)}; Path=/auth/google; Max-Age=600; HttpOnly; SameSite=Lax{self.secure()}"
        self.redirect(f"{GOOGLE_AUTH_URL}?{params}", [cookie])

    def google_callback(self, q: dict):
        clear = f"termometro_oauth=; Path=/auth/google; Max-Age=0; HttpOnly; SameSite=Lax{self.secure()}"
        expected = verify(self.cookie("termometro_oauth"))
        if not expected or not q.get("state") or not hmac.compare_digest(expected, "o." + q["state"]) or not q.get("code"):
            return self.redirect("/?error=state", [clear])
        try:
            email = google_email(q["code"])
        except (OSError, ValueError, KeyError) as error:
            print(f"google sign-in failed: {error}", flush=True)
            return self.redirect("/?error=google", [clear])
        if not CONFIG.allowed(email):
            return self.redirect("/?error=not_allowed", [clear])
        self.redirect("/", [clear, self.session_cookie(email)])

    def map_token_project(self) -> str | None:
        auth = self.headers.get("Authorization", "")
        payload = verify(auth[7:]) if auth.startswith("Bearer ") else None
        if not payload or not payload.startswith("m."):
            return None
        project, _, exp = payload[2:].rpartition(".")
        return project if exp.isdigit() and int(exp) > time.time() else None

    def cors_for(self, project: dict | None) -> dict:
        origin = self.headers.get("Origin", "")
        if project and origin and (not project["origins"] or origin in project["origins"]):
            return {"Access-Control-Allow-Origin": origin, "Vary": "Origin"}
        return {}

    def do_OPTIONS(self):
        # Preflight for the heat map's reads (Authorization header). The collector's posts are text/plain: no preflight.
        origin = self.headers.get("Origin", "")
        known = any(origin in p["origins"] for p in CONFIG.projects.values())
        headers = {"Access-Control-Allow-Origin": origin, "Vary": "Origin", "Access-Control-Allow-Methods": "GET, POST",
                   "Access-Control-Allow-Headers": "Authorization, Content-Type", "Access-Control-Max-Age": "86400"} if known else {}
        self.send(204, headers=headers)

    def do_POST(self):
        path = urlparse(self.path).path
        if path == "/api/events":
            return self.ingest()
        if path == "/api/login":
            return self.login()
        if path == "/api/logout":
            return self.json(200, {"ok": True}, {"Set-Cookie": "termometro_session=; Path=/; Max-Age=0; HttpOnly; SameSite=Strict"})
        if path == "/api/names":
            who = self.session()
            if not who or who["email"] == "api":  # API tokens read; only people write
                return self.json(401, {"error": "sign in"})
            project = parse_qs(urlparse(self.path).query).get("project", [""])[0]
            if project not in CONFIG.by_name:
                return self.json(404, {"error": "project"})
            try:
                item = json.loads(self.body())
                with connect() as con:
                    name_thing(con, project, str(item.get("kind", "")), str(item.get("key", "")), str(item.get("name", "")))
            except (ValueError, AttributeError, UnicodeDecodeError) as error:
                return self.json(400, {"error": str(error)})
            return self.json(200, {"ok": True})
        if path == "/api/features":
            who = self.session()
            if not who or who["email"] == "api":
                return self.json(401, {"error": "sign in"})
            project = parse_qs(urlparse(self.path).query).get("project", [""])[0]
            if project not in CONFIG.by_name:
                return self.json(404, {"error": "project"})
            try:
                item = json.loads(self.body())
                if not isinstance(item, dict):
                    raise ValueError("not an object")
                with connect() as con:
                    fid = save_feature(con, project, item)
            except (ValueError, UnicodeDecodeError) as error:
                return self.json(400, {"error": str(error)})
            return self.json(200, {"id": fid})
        if path == "/api/mark":
            if not self.signed_in():
                return self.json(401, {"error": "sign in"})
            q = {k: v[0] for k, v in parse_qs(urlparse(self.path).query).items()}
            if q.get("project") not in CONFIG.by_name:
                return self.json(404, {"error": "project"})
            at = None if q.get("clear") == "1" else int(time.time() * 1000)
            with connect() as con:
                set_mark(con, q["project"], at)
            return self.json(200, {"mark": at})
        if path == "/api/map-token":
            if not self.signed_in():
                return self.json(401, {"error": "sign in"})
            project = parse_qs(urlparse(self.path).query).get("project", [""])[0]
            if project not in CONFIG.by_name:
                return self.json(404, {"error": "project"})
            token = sign(f"m.{project}.{int(time.time()) + MAP_TOKEN_SECONDS}")
            return self.json(200, {"token": token, "url": CONFIG.by_name[project]["url"]})
        self.json(404, {"error": "not found"})

    def ingest(self):
        origin = self.headers.get("Origin")
        try:
            batch = json.loads(self.body())
            project = CONFIG.projects.get(str(batch.get("key", ""))) if isinstance(batch, dict) else None
            headers = self.cors_for(project)
            name, rows, elements = parse_batch(batch, origin, agent_of(self.headers.get("User-Agent", "")))
        except PermissionError as error:
            return self.json(403, {"error": str(error)})
        except (ValueError, UnicodeDecodeError) as error:
            return self.json(400, {"error": str(error)})
        if not within_limit("ingest:" + self.ip(), len(rows) + (1 if elements else 0), MAX_PER_MINUTE):
            return self.json(429, {"error": "rate limit"}, headers)
        with connect() as con:
            con.executemany(INSERT_EVENT, rows)
            con.executemany("INSERT INTO elements (project, route, target, last_seen, label) VALUES (?, ?, ?, ?, ?) "
                            "ON CONFLICT (project, route, target) DO UPDATE SET last_seen = excluded.last_seen, "
                            "label = CASE WHEN excluded.label != '' THEN excluded.label ELSE elements.label END", elements)
        self.send(204, headers=headers)

    def login(self):
        if not within_limit("login:" + self.ip(), 1, MAX_LOGINS_PER_MINUTE):
            return self.json(429, {"error": "too many attempts, wait a minute"})
        try:
            password = str(json.loads(self.body()).get("password", ""))
        except (ValueError, AttributeError, UnicodeDecodeError):
            return self.json(400, {"error": "bad request"})
        if CONFIG.no_auth or not CONFIG.password or not hmac.compare_digest(password.encode(), CONFIG.password.encode()):
            return self.json(401, {"error": "wrong password"})
        self.json(200, {"ok": True}, {"Set-Cookie": self.session_cookie("")})

    def do_GET(self):
        url = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(url.query).items()}
        if url.path in STATIC_FILES:
            name, kind = STATIC_FILES[url.path]
            file = STATIC / name
            if not file.exists():
                return self.json(404, {"error": f"{name} missing — build the collector (see README)"})
            # The collector and the map run inside other sites: any origin may load them.
            extra = {"Access-Control-Allow-Origin": "*", "Cache-Control": "no-cache"} if name != "index.html" else {
                "Content-Security-Policy": "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'",
                "X-Frame-Options": "DENY"}
            return self.send(200, file.read_bytes(), kind, extra)
        if url.path == "/auth/google" and CONFIG.google:
            return self.google_start()
        if url.path == "/auth/google/callback" and CONFIG.google:
            return self.google_callback(q)
        if url.path == "/api/me":
            who = self.session()
            with connect():
                marks = dict(MARKS)
            return self.json(200, {"signed_in": who is not None, "email": who["email"] if who else "",
                                   "methods": {"google": CONFIG.google, "password": bool(CONFIG.password)},
                                   "no_auth": CONFIG.no_auth,
                                   # The key is public by design (it ships in the app's bundle); the dashboard shows it
                                   # to whoever signed in, for the setup snippet.
                                   "projects": [{"name": p["name"], "url": p["url"], "key": k, "origins": p["origins"],
                                                 "mark": marks.get(p["name"])}
                                                for k, p in CONFIG.projects.items()]
                                   if who else []})
        if url.path not in READS and url.path not in ("/api/filters", "/api/status", "/api/names", "/api/dictionary"):
            return self.json(404, {"error": "not found"})
        headers = {}
        if not self.signed_in():
            # The heat map, inside the app, reads usage for its own project with a short-lived token.
            project = self.map_token_project()
            if url.path != "/api/usage" or not project or q.get("project") != project:
                return self.json(401, {"error": "sign in"})
            headers = self.cors_for(CONFIG.by_name.get(project))
        with connect() as con:
            if url.path == "/api/filters":
                return self.json(200, filters(con, q.get("project", "")), headers)
            if url.path == "/api/names":
                return self.json(200, names(con, q.get("project", "")), headers)
            if url.path == "/api/dictionary":
                return self.json(200, dictionary(con, q.get("project", "")), headers)
            if url.path == "/api/status":
                first, last, total = con.execute(
                    "SELECT MIN(at), MAX(at), COUNT(*) FROM events WHERE project = ?", (q.get("project", ""),)).fetchone()
                return self.json(200, {"events": total, "first_at": first, "last_at": last}, headers)
            if url.path == "/api/report" and q.get("format") == "md":
                return self.send(200, report_markdown(report(con, Filter(q))).encode(), "text/markdown; charset=utf-8", headers)
            self.json(200, READS[url.path](con, Filter(q)), headers)

    do_HEAD = do_GET


def main(argv: list[str]) -> None:
    global CONFIG
    if argv[1:2] == ["new-token"]:
        print("tt_" + secrets.token_urlsafe(32))
        return
    if argv[1:2] == ["new-key"]:
        print("tk_" + secrets.token_urlsafe(18))
        return
    CONFIG = Config()
    CONFIG.check()
    connect().close()
    threading.Thread(target=daily_retention, daemon=True).start()
    if any(p["webhook"] for p in CONFIG.projects.values()):
        threading.Thread(target=hourly_alerts, daemon=True).start()
    server = ThreadingHTTPServer((CONFIG.host, CONFIG.port), Handler)
    names = ", ".join(p["name"] for p in CONFIG.projects.values()) or "none"
    print(f"termometro {VERSION} on http://{CONFIG.host}:{CONFIG.port} — db {CONFIG.db} — projects: {names}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main(sys.argv)
