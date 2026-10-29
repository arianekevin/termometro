"""Server tests: python3 -m unittest discover server/tests"""
import base64
import json
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import termometro as t  # noqa: E402

ORIGIN = "https://shop.example.com"
KEY = "tk_test"


def setup_config(**extra):
    env = {"TERMOMETRO_PASSWORD": "s3cret", "TERMOMETRO_DB": str(Path(tempfile.mkdtemp()) / "t.db"),
           "TERMOMETRO_PROJECTS": json.dumps([
               {"name": "shop", "key": KEY, "origins": [ORIGIN], "url": ORIGIN},
               {"name": "blog", "key": "tk_blog", "origins": []}])}
    env.update(extra)
    t.CONFIG = t.Config(env)
    t._counts.clear()


def call(base, path, body=None, origin=None, method=None, cookie=None, token=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base + path, data=data, method=method)
    if data:
        req.add_header("Content-Type", "text/plain")
    if origin:
        req.add_header("Origin", origin)
    if cookie:
        req.add_header("Cookie", cookie)
    if token:
        req.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        with e:
            return e.code, dict(e.headers), e.read()


class Server(unittest.TestCase):
    def setUp(self):
        setup_config()
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), t.Handler)
        self.base = f"http://127.0.0.1:{self.srv.server_port}"
        threading.Thread(target=self.srv.serve_forever, kwargs={'poll_interval': 0.05}, daemon=True).start()
        self.cookie = self.sign_in()

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()

    def sign_in(self, password="s3cret"):
        status, headers, _ = call(self.base, "/api/login", {"password": password})
        return headers.get("Set-Cookie", "").split(";")[0] if status == 200 else None

    def send(self, events, key=KEY, origin=ORIGIN, session="s1", **who):
        return call(self.base, "/api/events", {"key": key, "version": who.pop("version", "1.0"), "session": session,
                                               "events": events, **who}, origin=origin)

    def read(self, path, **kw):
        status, _, body = call(self.base, path, cookie=kw.pop("cookie", self.cookie), token=kw.pop("token", None))
        self.assertEqual(status, 200, body)
        return json.loads(body)

    # Ingest ------------------------------------------------------------------------------------------------

    def test_scores_screens_and_lists_what_irritates(self):
        status, headers, _ = self.send([
            {"type": "page", "route": "/cart"}, {"type": "page", "route": "/cart"},
            {"type": "rage", "route": "/cart", "target": "button#pay"},
            {"type": "http_5xx", "route": "/cart", "target": "button#pay", "detail": "POST /api/pay 500"},
            {"type": "page", "route": "/home"}])
        self.assertEqual(status, 204)
        self.assertEqual(headers["Access-Control-Allow-Origin"], ORIGIN)
        s = self.read("/api/summary?project=shop&days=1")
        cart = s["routes"][0]
        self.assertEqual((cart["key"], cart["score"]), ("/cart", 80))  # (3 + 5) / 2 visits * 20
        self.assertEqual(sorted(x["type"] for x in cart["targets"]), ["http_5xx", "rage"])
        self.assertEqual(cart["failures"], [{"type": "http_5xx", "detail": "POST /api/pay 500", "after": "button#pay", "n": 1}])
        self.assertEqual(s["overall"]["visits"], 3)

    def test_unknown_key_and_foreign_origin_are_refused(self):
        self.assertEqual(self.send([{"type": "page"}], key="tk_nope")[0], 403)
        self.assertEqual(self.send([{"type": "page"}], origin="https://evil.example")[0], 403)
        # A project with no origins listed takes any origin; a server-side sender has none.
        self.assertEqual(self.send([{"type": "page"}], key="tk_blog", origin="https://anything.example")[0], 204)
        self.assertEqual(self.send([{"type": "page"}], origin=None)[0], 204)

    def test_projects_do_not_see_each_other(self):
        self.send([{"type": "page", "route": "/a"}])
        self.send([{"type": "page", "route": "/b"}], key="tk_blog")
        self.assertEqual([r["key"] for r in self.read("/api/summary?project=blog")["routes"]], ["/b"])

    def test_bad_batches(self):
        self.assertEqual(call(self.base, "/api/events", {"key": KEY, "events": [{"type": "page"}]})[0], 400)
        self.assertEqual(self.send([])[0], 400)
        self.assertEqual(self.send([{"type": "page"}] * 101)[0], 400)

    def test_unknown_types_are_skipped_and_text_is_cut(self):
        self.send([{"type": "newer"}, {"type": "page", "route": "/" + "a" * 500}])
        routes = self.read("/api/summary?project=shop")["routes"]
        self.assertEqual([len(r["key"]) for r in routes], [200])

    def test_rate_limit(self):
        for _ in range(t.MAX_PER_MINUTE // 100):
            self.assertEqual(self.send([{"type": "page"}] * 100)[0], 204)
        self.assertEqual(self.send([{"type": "page"}])[0], 429)

    # Reads -------------------------------------------------------------------------------------------------

    def test_usage_per_screen_and_element_with_never_clicked(self):
        self.send([
            {"type": "page", "route": "/t"}, {"type": "page", "route": "/t"}, {"type": "page", "route": "/c"},
            {"type": "inventory", "route": "/t", "targets": ["button#save", "button#delete", "a#help"]},
            {"type": "click", "route": "/t", "target": "button#save"}, {"type": "click", "route": "/t", "target": "button#save"},
            {"type": "dead", "route": "/t", "target": "button#save"}, {"type": "click", "route": "/t", "target": "a#help"}],
            user="u1")
        screens = self.read("/api/usage?project=shop")["screens"]
        self.assertEqual([(s["route"], s["visits"], s["clicks"], s["users"]) for s in screens], [("/t", 2, 3, 1), ("/c", 1, 0, 1)])
        screen = self.read("/api/usage?project=shop&route=/t")
        self.assertEqual(screen["elements"][0], {"target": "button#save", "clicks": 2, "users": 1, "rage": 0, "dead": 1, "errors": 0})
        self.assertEqual(screen["never_clicked"], ["button#delete"])

    def test_clicks_and_actions_do_not_weigh(self):
        self.send([{"type": "page", "route": "/x"}, {"type": "click", "route": "/x", "target": "b"},
                   {"type": "action", "route": "/x", "detail": "POST /api/x", "clicks": 3, "duration_ms": 4000}])
        s = self.read("/api/summary?project=shop")
        self.assertEqual((s["overall"]["score"], s["routes"][0]["signals"]), (0, {}))

    def test_people_by_role_account_and_user(self):
        self.send([{"type": "page", "route": "/queue"}, {"type": "page", "route": "/queue"},
                   {"type": "click", "route": "/queue", "target": "b"}], user="u1", role="agent", account="77")
        self.send([{"type": "page", "route": "/reports"}, {"type": "rage", "route": "/reports"}],
                  session="s2", user="u2", role="manager", account="77")
        p = self.read("/api/people?project=shop")
        self.assertEqual({g["key"]: g["visits"] for g in p["roles"]}, {"agent": 2, "manager": 1})
        self.assertEqual(p["accounts"][0] | {"screens": None},
                         {"key": "77", "users": 2, "sessions": 2, "visits": 3, "clicks": 1, "score": 20, "screens": None})
        u1 = next(g for g in p["users"] if g["key"] == "u1")
        self.assertEqual((u1["role"], u1["account"], u1["screens"]), ("agent", "77", [{"route": "/queue", "visits": 2}]))
        self.assertEqual(self.read("/api/summary?project=shop&role=agent")["overall"]["visits"], 2)
        self.assertEqual(self.read("/api/filters?project=shop"), {"accounts": ["77"], "roles": ["agent", "manager"], "versions": ["1.0"]})

    def test_actions_median_and_p90(self):
        self.send([{"type": "action", "route": "/t", "detail": "POST /api/orders", "clicks": c, "duration_ms": c * 1000}
                   for c in (4, 6, 20)] + [{"type": "action", "route": "/t", "detail": "PUT /api/tags", "clicks": 2}])
        a = self.read("/api/actions?project=shop")["actions"]
        self.assertEqual([(x["action"], x["times"], x["clicks_median"], x["clicks_p90"], x["seconds_median"]) for x in a],
                         [("POST /api/orders", 3, 6, 20, 6.0), ("PUT /api/tags", 1, 2, 2, 0.0)])

    def test_retention_turns_events_into_idless_totals(self):
        self.send([{"type": "page", "route": "/x"}, {"type": "rage", "route": "/x"}], user="u9")
        with t.connect() as con:
            removed = t.apply_retention(con, now=time.time() + (t.CONFIG.retention_days + 1) * 86400)
            left = con.execute("SELECT COUNT(*) FROM events").fetchone()[0]
            history = con.execute("SELECT route, type, n FROM history ORDER BY type").fetchall()
        self.assertEqual((removed, left), (2, 0))
        self.assertEqual(history, [("/x", "page", 1), ("/x", "rage", 1)])

    # Auth --------------------------------------------------------------------------------------------------

    def test_reads_need_the_password(self):
        self.assertIsNone(self.sign_in("wrong"))
        status, _, _ = call(self.base, "/api/summary?project=shop")
        self.assertEqual(status, 401)
        self.assertEqual(self.read("/api/me", cookie=None), {"signed_in": False, "email": "", "no_auth": False,
                                                             "methods": {"google": False, "password": True}, "projects": []})
        self.assertEqual(self.read("/api/me")["projects"], [{"name": "shop", "url": ORIGIN, "key": KEY, "origins": [ORIGIN]},
                                                            {"name": "blog", "url": "", "key": "tk_blog", "origins": []}])
        forged = "termometro_session=s.9999999999.AAAA"
        self.assertEqual(call(self.base, "/api/summary?project=shop", cookie=forged)[0], 401)

    def test_login_attempts_are_limited(self):
        for _ in range(t.MAX_LOGINS_PER_MINUTE - 1):
            self.sign_in("wrong")
        self.assertEqual(call(self.base, "/api/login", {"password": "s3cret"})[0], 429)

    def test_map_token_reads_usage_of_its_project_only(self):
        self.assertEqual(call(self.base, "/api/map-token?project=shop", {}, method="POST")[0], 401)
        status, _, body = call(self.base, "/api/map-token?project=shop", {}, method="POST", cookie=self.cookie)
        token = json.loads(body)["token"]
        self.assertEqual(json.loads(body)["url"], ORIGIN)
        status, headers, _ = call(self.base, "/api/usage?project=shop&route=/t", origin=ORIGIN, token=token)
        self.assertEqual((status, headers["Access-Control-Allow-Origin"]), (200, ORIGIN))
        self.assertEqual(call(self.base, "/api/usage?project=blog&route=/t", token=token)[0], 401)
        self.assertEqual(call(self.base, "/api/people?project=shop", token=token)[0], 401)
        expired = t.sign(f"m.shop.{int(time.time()) - 1}")
        self.assertEqual(call(self.base, "/api/usage?project=shop&route=/t", token=expired)[0], 401)

    def test_no_auth_mode_and_missing_password(self):
        setup_config(TERMOMETRO_PASSWORD="", TERMOMETRO_NO_AUTH="1")
        self.assertEqual(call(self.base, "/api/summary?project=shop")[0], 200)
        setup_config(TERMOMETRO_PASSWORD="")
        with self.assertRaises(SystemExit):
            t.CONFIG.check()

    def test_status_tells_whether_anything_arrived(self):
        self.assertEqual(self.read("/api/status?project=shop")["events"], 0)
        self.send([{"type": "page"}, {"type": "click", "target": "b"}])
        status = self.read("/api/status?project=shop")
        self.assertEqual(status["events"], 2)
        self.assertGreater(status["last_at"], 0)
        self.assertEqual(call(self.base, "/api/status?project=shop")[0], 401)

    def test_google_is_off_without_a_client(self):
        self.assertEqual(call(self.base, "/auth/google")[0], 404)

    def test_static_files(self):
        status, headers, body = call(self.base, "/")
        self.assertEqual(status, 200)
        self.assertIn("default-src 'self'", headers["Content-Security-Policy"])
        status, headers, _ = call(self.base, "/map.js")
        self.assertEqual((status, headers["Access-Control-Allow-Origin"]), (200, "*"))


class FakeGoogle(BaseHTTPRequestHandler):
    """Google's token endpoint: answers with an ID token for whatever the test put in `claims`."""
    claims: dict = {}
    seen: dict = {}

    def log_message(self, *a):
        pass

    def do_POST(self):
        FakeGoogle.seen = {k: v[0] for k, v in parse_qs(self.rfile.read(int(self.headers["Content-Length"])).decode()).items()}
        part = base64.urlsafe_b64encode(json.dumps(FakeGoogle.claims).encode()).decode().rstrip("=")
        body = json.dumps({"id_token": f"h.{part}.sig"}).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **kw):
        return None


class GoogleSignIn(unittest.TestCase):
    def setUp(self):
        self.google = ThreadingHTTPServer(("127.0.0.1", 0), FakeGoogle)
        threading.Thread(target=self.google.serve_forever, kwargs={'poll_interval': 0.05}, daemon=True).start()
        t.GOOGLE_TOKEN_URL = f"http://127.0.0.1:{self.google.server_port}/token"
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), t.Handler)
        self.base = f"http://127.0.0.1:{self.srv.server_port}"
        setup_config(TERMOMETRO_PASSWORD="", TERMOMETRO_GOOGLE_CLIENT_ID="cid", TERMOMETRO_GOOGLE_CLIENT_SECRET="csecret",
                     TERMOMETRO_ALLOWED_EMAILS="ana@example.com", TERMOMETRO_ALLOWED_DOMAINS="team.example.org",
                     TERMOMETRO_PUBLIC_URL=self.base)
        threading.Thread(target=self.srv.serve_forever, kwargs={'poll_interval': 0.05}, daemon=True).start()
        self.opener = urllib.request.build_opener(NoRedirect)

    def tearDown(self):
        for s in (self.srv, self.google):
            s.shutdown()
            s.server_close()

    def get(self, path, cookie=None):
        req = urllib.request.Request(self.base + path)
        if cookie:
            req.add_header("Cookie", cookie)
        try:
            r = self.opener.open(req)
        except urllib.error.HTTPError as e:
            r = e
        with r:
            return r.status, r.headers

    def start(self):
        status, headers = self.get("/auth/google")
        self.assertEqual(status, 302)
        url = urlparse(headers["Location"])
        q = {k: v[0] for k, v in parse_qs(url.query).items()}
        self.assertEqual((url.netloc, q["client_id"], q["redirect_uri"], q["scope"]),
                         ("accounts.google.com", "cid", self.base + "/auth/google/callback", "openid email"))
        return q["state"], headers["Set-Cookie"].split(";")[0]

    def claims(self, email, **over):
        FakeGoogle.claims = {"aud": "cid", "iss": "https://accounts.google.com", "exp": int(time.time()) + 600,
                             "email": email, "email_verified": True, **over}

    def finish(self, state, cookie):
        status, headers = self.get(f"/auth/google/callback?code=abc&state={state}", cookie)
        self.assertEqual(status, 302)
        session = [c.split(";")[0] for c in headers.get_all("Set-Cookie") if c.startswith("termometro_session=")]
        return headers["Location"], session[0] if session else None

    def me(self, cookie):
        _, _, body = call(self.base, "/api/me", cookie=cookie)
        return json.loads(body)

    def test_allowed_email_signs_in(self):
        state, cookie = self.start()
        self.claims("Ana@example.com")
        location, session = self.finish(state, cookie)
        self.assertEqual(location, "/")
        self.assertEqual(FakeGoogle.seen["code"], "abc")
        self.assertEqual(FakeGoogle.seen["client_secret"], "csecret")
        me = self.me(session)
        self.assertEqual((me["signed_in"], me["email"], me["methods"]), (True, "Ana@example.com", {"google": True, "password": False}))

    def test_allowed_domain_signs_in(self):
        state, cookie = self.start()
        self.claims("bruno@team.example.org")
        self.assertEqual(self.finish(state, cookie)[0], "/")

    def test_others_are_turned_away(self):
        state, cookie = self.start()
        self.claims("eve@gmail.com")
        self.assertEqual(self.finish(state, cookie), ("/?error=not_allowed", None))

    def test_unverified_email_or_other_audience_is_refused(self):
        for over in ({"email_verified": False}, {"aud": "someone-else"}, {"exp": int(time.time()) - 1}):
            state, cookie = self.start()
            self.claims("ana@example.com", **over)
            self.assertEqual(self.finish(state, cookie), ("/?error=google", None))

    def test_state_must_match_the_cookie(self):
        _, cookie = self.start()
        self.claims("ana@example.com")
        self.assertEqual(self.finish("forged", cookie), ("/?error=state", None))
        state, _ = self.start()
        self.assertEqual(self.finish(state, None), ("/?error=state", None))

    def test_password_login_is_off_when_only_google_is_set(self):
        self.assertEqual(call(self.base, "/api/login", {"password": ""})[0], 401)

    def test_google_needs_someone_allowed_and_a_public_url(self):
        setup_config(TERMOMETRO_GOOGLE_CLIENT_ID="cid", TERMOMETRO_GOOGLE_CLIENT_SECRET="x", TERMOMETRO_PUBLIC_URL="https://t.example")
        with self.assertRaises(SystemExit):
            t.CONFIG.check()
        setup_config(TERMOMETRO_GOOGLE_CLIENT_ID="cid", TERMOMETRO_GOOGLE_CLIENT_SECRET="x", TERMOMETRO_ALLOWED_DOMAINS="x.com")
        with self.assertRaises(SystemExit):
            t.CONFIG.check()


if __name__ == "__main__":
    unittest.main()
