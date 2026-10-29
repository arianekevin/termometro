#!/usr/bin/env python3
"""Termometro server — receives what the collector sends and shows usage and frustration per screen.

Standard library only, one SQLite file. Serves the dashboard, the heat map, the collector for <script> tags
and the API:

  POST /api/events     a batch from the collector; the project key picks the project
  POST /api/login      the instance password -> session cookie
  GET  /auth/google    sign in with Google (then /auth/google/callback); only allowed e-mails or domains get in
  POST /api/logout
  GET  /api/me         is this browser signed in, and which projects exist
  GET  /api/summary    frustration per screen and per version      ┐
  GET  /api/usage      usage per screen, or per element of one      │ session cookie (or a heat-map token,
  GET  /api/people     usage per role, account and user (ids only)  │ for /api/usage)
  GET  /api/actions    effort (clicks and time) per accepted write  │
  GET  /api/filters    accounts, roles and versions seen             │
  GET  /api/status     has this project received anything yet        │
  POST /api/map-token  a one-hour token to open the heat map        ┘
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

`python termometro.py new-key` prints a fresh project key.
"""
import base64
import hashlib
import urllib.parse
import urllib.request
import hmac
import json
import os
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
VERSION = "0.1.0"

# Weight of each frustration signal in the score. "page" is a visit (the denominator); "click" and "action"
# measure usage and effort and weigh nothing; "inventory" lists what can be clicked on a screen.
WEIGHTS = {"rage": 3, "dead": 2, "js_error": 5, "http_5xx": 5, "http_4xx": 2, "abandon": 2, "bounce": 1}
TYPES = set(WEIGHTS) | {"page", "click", "action", "inventory"}
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
SIZES = {"version": 40, "session": 40, "account": 64, "user": 64, "role": 32,
         "route": 200, "target": 200, "detail": 200}


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
            self.projects[p["key"]] = {"name": str(p["name"]), "origins": list(p.get("origins", [])), "url": p.get("url", "")}
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
    """)
    return con


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


def parse_batch(batch, origin: str | None) -> tuple[str, list[tuple], list[tuple]]:
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
    now = int(time.time() * 1000)
    rows, elements = [], []
    for e in events:
        if not isinstance(e, dict) or e.get("type") not in TYPES:
            continue  # an unknown type (a newer collector) does not sink the batch
        route = text(e.get("route"), "route") or "/"
        if e["type"] == "inventory":
            targets = e.get("targets") if isinstance(e.get("targets"), list) else []
            elements += [(project["name"], route, text(t, "target"), now) for t in targets[:MAX_INVENTORY] if t]
            continue
        rows.append((project["name"], who[0] or "?", session, who[1], who[2], who[3], e["type"], route,
                     text(e.get("target"), "target"), text(e.get("detail"), "detail"),
                     integer(e.get("clicks")), integer(e.get("duration_ms")), now))
    return project["name"], rows, elements


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

    def __init__(self, q: dict):
        try:
            self.days = max(1, min(CONFIG.retention_days, int(q.get("days", "7"))))
        except ValueError:
            self.days = 7
        since = int((time.time() - self.days * 86400) * 1000)
        self.sql, self.args = "project = ? AND at >= ?", [q.get("project", ""), since]
        for field, column in (("version", "version"), ("account", "account"), ("role", "role"),
                              ("user", "user_id"), ("route", "route")):
            if q.get(field):
                self.sql += f" AND {column} = ?"
                self.args.append(q[field])
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
    failures = con.execute(f"""
        SELECT route, type, detail, target, COUNT(*) n FROM events
        WHERE {f.sql} AND type IN ('js_error', 'http_5xx', 'http_4xx')
        GROUP BY route, type, detail, target ORDER BY n DESC""", f.args).fetchall()
    per_route: dict[str, dict] = {}
    for route, target, kind, n in targets:
        lst = per_route.setdefault(route, {"targets": [], "failures": []})["targets"]
        if len(lst) < 5:
            lst.append({"target": target, "type": kind, "n": n})
    for route, kind, detail, target, n in failures:
        lst = per_route.setdefault(route, {"targets": [], "failures": []})["failures"]
        if len(lst) < 5:
            lst.append({"type": kind, "detail": detail, "after": target, "n": n})
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


READS = {"/api/summary": summary, "/api/usage": usage, "/api/people": people, "/api/actions": actions}
STATIC_FILES = {"/": ("index.html", "text/html; charset=utf-8"),
                "/map.js": ("map.js", "text/javascript; charset=utf-8"),
                "/termometro.js": ("termometro.js", "text/javascript; charset=utf-8")}


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
            name, rows, elements = parse_batch(batch, origin)
        except PermissionError as error:
            return self.json(403, {"error": str(error)})
        except (ValueError, UnicodeDecodeError) as error:
            return self.json(400, {"error": str(error)})
        if not within_limit("ingest:" + self.ip(), len(rows) + (1 if elements else 0), MAX_PER_MINUTE):
            return self.json(429, {"error": "rate limit"}, headers)
        with connect() as con:
            con.executemany("INSERT INTO events (project, version, session, account, user_id, role, type, route, target, "
                            "detail, clicks, duration_ms, at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
            con.executemany("INSERT INTO elements (project, route, target, last_seen) VALUES (?, ?, ?, ?) "
                            "ON CONFLICT (project, route, target) DO UPDATE SET last_seen = excluded.last_seen", elements)
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
            return self.json(200, {"signed_in": who is not None, "email": who["email"] if who else "",
                                   "methods": {"google": CONFIG.google, "password": bool(CONFIG.password)},
                                   "no_auth": CONFIG.no_auth,
                                   # The key is public by design (it ships in the app's bundle); the dashboard shows it
                                   # to whoever signed in, for the setup snippet.
                                   "projects": [{"name": p["name"], "url": p["url"], "key": k, "origins": p["origins"]}
                                                for k, p in CONFIG.projects.items()]
                                   if who else []})
        if url.path not in READS and url.path not in ("/api/filters", "/api/status"):
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
            if url.path == "/api/status":
                first, last, total = con.execute(
                    "SELECT MIN(at), MAX(at), COUNT(*) FROM events WHERE project = ?", (q.get("project", ""),)).fetchone()
                return self.json(200, {"events": total, "first_at": first, "last_at": last}, headers)
            self.json(200, READS[url.path](con, Filter(q)), headers)

    do_HEAD = do_GET


def main(argv: list[str]) -> None:
    global CONFIG
    if argv[1:2] == ["new-key"]:
        print("tk_" + secrets.token_urlsafe(18))
        return
    CONFIG = Config()
    CONFIG.check()
    connect().close()
    threading.Thread(target=daily_retention, daemon=True).start()
    server = ThreadingHTTPServer((CONFIG.host, CONFIG.port), Handler)
    names = ", ".join(p["name"] for p in CONFIG.projects.values()) or "none"
    print(f"termometro {VERSION} on http://{CONFIG.host}:{CONFIG.port} — db {CONFIG.db} — projects: {names}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main(sys.argv)
