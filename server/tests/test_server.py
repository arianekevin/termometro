"""Server tests: python3 -m unittest discover server/tests"""
import base64
import json
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.parse
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
        failure = cart["failures"][0]
        self.assertEqual({k: failure[k] for k in ("type", "detail", "after", "n", "first_version", "last_version")},
                         {"type": "http_5xx", "detail": "POST /api/pay 500", "after": "button#pay", "n": 1,
                          "first_version": "1.0", "last_version": "1.0"})
        self.assertEqual(s["overall"]["visits"], 3)

    def test_a_failure_says_when_and_in_which_version_it_started_and_was_last_seen(self):
        error = {"type": "js_error", "route": "/cart", "detail": "TypeError: x is undefined"}
        self.send([{"type": "page", "route": "/cart"}, error], version="1.0")
        time.sleep(0.01)
        self.send([{"type": "page", "route": "/cart"}, error, error], version="1.1")
        time.sleep(0.01)
        self.send([{"type": "page", "route": "/cart"}], version="1.2")
        [failure] = self.read("/api/summary?project=shop&days=1")["routes"][0]["failures"]
        self.assertEqual((failure["n"], failure["first_version"], failure["last_version"]), (3, "1.0", "1.1"))
        self.assertLess(failure["first_at"], failure["last_at"])

    def test_a_fresh_start_hides_what_came_before_until_undone_and_deletes_nothing(self):
        error = {"type": "js_error", "route": "/cart", "detail": "TypeError: old"}
        self.send([{"type": "page", "route": "/cart"}, error])
        time.sleep(0.01)
        status, _, body = call(self.base, "/api/mark?project=shop", {}, cookie=self.cookie)
        self.assertEqual(status, 200)
        mark = json.loads(body)["mark"]
        self.assertEqual(self.read("/api/me")["projects"][0]["mark"], mark)
        self.assertIsNone(self.read("/api/me")["projects"][1]["mark"])  # only the project asked for
        time.sleep(0.01)
        self.send([{"type": "page", "route": "/home"}, {**error, "route": "/home"}])
        s = self.read("/api/summary?project=shop&days=1")
        self.assertEqual(([r["key"] for r in s["routes"]], s["overall"]["visits"]), (["/home"], 1))
        [f] = self.read("/api/failures?project=shop&days=1")["failures"]
        self.assertTrue(f["new"])  # before the mark does not count: it started again
        self.assertGreaterEqual(f["first_at"], mark)
        self.assertEqual(self.read("/api/summary?project=shop&days=1&all=1")["overall"]["visits"], 2)
        self.assertEqual(self.read("/api/summary?project=blog&days=1")["overall"]["visits"], 0)
        status, _, _ = call(self.base, "/api/mark?project=shop&clear=1", {}, cookie=self.cookie)
        self.assertEqual(status, 200)
        self.assertIsNone(self.read("/api/me")["projects"][0]["mark"])
        self.assertEqual(self.read("/api/summary?project=shop&days=1")["overall"]["visits"], 2)

    def test_marks_are_saved_by_date_and_picked_one_at_a_time(self):
        day = 86400 * 1000
        self.send([{"type": "page", "route": "/old"}])
        self.age(10)
        self.send([{"type": "page", "route": "/mid"}])
        self.age(3)
        self.send([{"type": "page", "route": "/new"}])
        now = int(time.time() * 1000)
        mark = lambda body: json.loads(call(self.base, "/api/mark?project=shop", body, cookie=self.cookie)[2])
        m = mark({"action": "create", "name": "Redesenho", "at": now - 5 * day})
        self.assertEqual([x["name"] for x in m["marks"]], ["Redesenho"])
        visits = lambda: sorted(r["key"] for r in self.read("/api/summary?project=shop&days=30")["routes"])
        self.assertEqual(visits(), ["/mid", "/new"])  # since 5 days ago
        m = mark({"action": "create", "name": "Versão 2", "at": now - day})
        self.assertEqual([x["name"] for x in m["marks"]], ["Versão 2", "Redesenho"])  # newest first, the new one in use
        self.assertEqual(visits(), ["/new"])
        first = next(x for x in m["marks"] if x["name"] == "Redesenho")
        mark({"action": "use", "id": first["id"]})
        self.assertEqual(visits(), ["/mid", "/new"])
        mark({"action": "none"})
        self.assertEqual(visits(), ["/mid", "/new", "/old"])
        m = mark({"action": "delete", "id": first["id"]})
        self.assertEqual([x["name"] for x in m["marks"]], ["Versão 2"])
        self.assertEqual(self.read("/api/me")["projects"][0]["marks"][0]["name"], "Versão 2")
        self.assertEqual(call(self.base, "/api/mark?project=shop", {"action": "create", "at": now + 10 * day}, cookie=self.cookie)[0], 400)

    def test_a_fresh_start_needs_a_signed_in_user_and_a_known_project(self):
        self.assertEqual(call(self.base, "/api/mark?project=shop", {})[0], 401)
        self.assertEqual(call(self.base, "/api/mark?project=nope", {}, cookie=self.cookie)[0], 404)

    def test_a_slow_request_weighs_one_and_shows_its_average_time(self):
        self.send([{"type": "page", "route": "/reports"},
                   {"type": "slow", "route": "/reports", "detail": "GET /api/reports/:id", "duration_ms": 4000},
                   {"type": "slow", "route": "/reports", "detail": "GET /api/reports/:id", "duration_ms": 5000}])
        r = self.read("/api/summary?project=shop&days=1")["routes"][0]
        self.assertEqual((r["score"], r["signals"]), (40, {"slow": 2}))  # 2 x 1 point / 1 visit * 20
        self.assertEqual((r["failures"][0]["type"], r["failures"][0]["seconds"]), ("slow", 4.5))

    def test_compare_puts_the_latest_version_against_the_one_before(self):
        page = lambda r: {"type": "page", "route": r}
        self.send([page("/cart"), page("/cart"), page("/home"),
                   {"type": "action", "route": "/cart", "detail": "POST /api/orders", "clicks": 3, "duration_ms": 4000},
                   {"type": "js_error", "route": "/cart", "detail": "TypeError: old"}], version="2.0")
        time.sleep(0.01)
        self.send([page("/cart"), page("/cart"), page("/home"),
                   {"type": "rage", "route": "/cart", "target": "button#pay"},
                   {"type": "action", "route": "/cart", "detail": "POST /api/orders", "clicks": 9, "duration_ms": 20000},
                   {"type": "js_error", "route": "/cart", "detail": "TypeError: old"},
                   {"type": "http_5xx", "route": "/cart", "detail": "POST /api/pay 500"}], version="10.0")
        c = self.read("/api/compare?project=shop&days=1")
        self.assertEqual((c["versions"], c["a"], c["b"]), (["2.0", "10.0"], "2.0", "10.0"))  # deploy order, not text order
        cart = c["routes"][0]
        self.assertEqual((cart["route"], cart["a"]["score"], cart["b"]["score"], cart["delta"]), ("/cart", 50, 100, 50))  # (3 + 5 + 5) / 2 * 20, capped
        self.assertEqual(c["routes"][1]["delta"], 0)
        [orders] = c["actions"]
        self.assertEqual((orders["a"]["clicks_median"], orders["b"]["clicks_median"]), (3, 9))
        self.assertEqual(c["new_failures"], [{"type": "http_5xx", "detail": "POST /api/pay 500", "route": "/cart", "n": 1}])
        self.assertEqual(c["overall"]["b"]["visits"], 3)
        back = self.read("/api/compare?project=shop&days=1&a=10.0&b=2.0")
        self.assertEqual((back["a"], back["b"]), ("10.0", "2.0"))
        self.assertEqual(self.read("/api/compare?project=blog&days=1")["routes"], [])

    def test_compare_is_per_visit_and_session_and_finds_the_version_before_out_of_the_period(self):
        page = lambda r: {"type": "page", "route": r}
        self.send([page("/cart")] * 4 + [{"type": "js_error", "route": "/cart", "detail": "TypeError: x"}], version="1.0", session="a1")
        self.age(10)
        for n in range(4):
            self.send([page("/cart")] * 5, version="1.1", session=f"b{n}")
        c = self.read("/api/compare?project=shop&days=7")
        self.assertEqual((c["versions"], c["previous"]), (["1.1"], {"version": "1.0", "days": 18}))  # 11 days ago + the 7 of the period
        wide = self.read("/api/compare?project=shop&days=18")
        self.assertEqual((wide["a"], wide["b"]), ("1.0", "1.1"))
        a, b = wide["overall"]["a"], wide["overall"]["b"]
        self.assertEqual((a["sessions"], a["failures"], a["failures_per_100"]), (1, 1, 100.0))
        self.assertEqual((b["visits"], b["sessions"], b["failures_per_100"]), (20, 4, 0))
        self.assertLess(a["first_at"], b["first_at"])
        self.assertIsNone(self.read("/api/compare?project=blog&days=7")["previous"])

    def test_insights_are_ordered_by_severity_times_reach(self):
        page = {"type": "page", "route": "/cart"}
        for n in range(30):  # a 4xx that reaches 30 people, against a 4xx that reaches one
            self.send([page, {"type": "http_4xx", "route": "/cart", "detail": "GET /api/wide 404"}], session=f"w{n}", user=f"u{n}")
        self.send([page] + [{"type": "http_4xx", "route": "/cart", "detail": "GET /api/narrow 404"}] * 40, session="n1", user="u0")
        o = self.read("/api/overview?project=shop&days=7")
        new = [i for i in o["insights"] if i["kind"] == "failure_new"]
        self.assertEqual([i["detail"] for i in new], ["GET /api/wide 404", "GET /api/narrow 404"])  # more times, fewer people: after
        self.assertEqual((new[0]["reach_sessions"], new[0]["reach_people"]), (30, 30))
        self.assertGreater(new[0]["impact"], new[1]["impact"])
        self.assertEqual([i["impact"] for i in o["insights"]], sorted((i["impact"] for i in o["insights"]), reverse=True))

    def age(self, days):
        """Moves everything sent so far `days` into the past."""
        with t.connect() as con:
            con.execute("UPDATE events SET at = at - ?", (days * 86400 * 1000,))

    def test_overview_compares_with_the_period_before_and_says_what_deserves_a_look(self):
        page = {"type": "page", "route": "/cart"}
        self.send([page] * 10 + [{"type": "js_error", "route": "/cart", "detail": "TypeError: old"}] * 5)
        self.age(8)
        self.send([page] * 10 + [{"type": "rage", "route": "/cart", "target": "button#pay"}] * 5
                  + [{"type": "js_error", "route": "/cart", "detail": "TypeError: old"}] * 5
                  + [{"type": "http_5xx", "route": "/cart", "detail": "POST /api/pay 500"}] * 2
                  + [{"type": "action", "route": "/cart", "detail": "POST /api/orders", "clicks": 20, "duration_ms": 9000}] * 3,
                  user="u1")
        o = self.read("/api/overview?project=shop&days=7")
        self.assertEqual((o["before"]["visits"], o["before"]["score"]), (10, 50))  # 5 errors x 5 / 10 * 20
        self.assertEqual((o["now"]["visits"], o["now"]["users"], o["now"]["failures"], o["now"]["score"]), (10, 1, 7, 100))
        kinds = [i["kind"] for i in o["insights"]]
        self.assertEqual(kinds[0], "screen_worse")
        self.assertIn("failure_new", kinds)          # the 5xx never happened before this week
        self.assertIn("failure_recurring", kinds)    # the TypeError did
        self.assertIn("action_laborious", kinds)
        self.assertIn("element_irritating", kinds)
        worse = o["insights"][0]
        self.assertEqual((worse["before"], worse["now"], worse["top_signal"], worse["link"]),
                         (50, 100, "js_error", {"tab": "frustration", "params": {"route": "/cart"}}))
        self.assertEqual(len(o["daily"]), 1)

    def test_overview_says_which_version_made_a_screen_worse_and_draws_the_days(self):
        page = {"type": "page", "route": "/cart"}
        self.send([page] * 10 + [{"type": "rage", "route": "/cart", "target": "button#pay"}] * 1, version="1.0", user="u1")
        time.sleep(0.01)
        self.send([page] * 10 + [{"type": "rage", "route": "/cart", "target": "button#pay"}] * 6, version="1.1", user="u2")
        o = self.read("/api/overview?project=shop&days=7")
        worse = o["insights"][0]
        self.assertEqual({k: worse[k] for k in ("kind", "severity", "route", "a", "b", "before", "now")},
                         {"kind": "version_worse", "severity": "bad", "route": "/cart", "a": "1.0", "b": "1.1", "before": 6, "now": 36})
        self.assertNotIn("screen_frustrating", [i["kind"] for i in o["insights"]])  # the same screen is said once
        self.assertEqual([d["version"] for d in o["deploys"]], ["1.0", "1.1"])
        self.assertEqual(o["daily"][0]["users"], 2)
        [cart] = o["screens"]
        self.assertEqual((cart["route"], cart["score"], list(cart["days"].values())[0]["visits"]), ("/cart", 21, 20))
        self.assertEqual(o["before_daily"], [])
        filtered = self.read("/api/overview?project=shop&days=7&version=1.1")["insights"]
        self.assertNotIn("version_worse", [i["kind"] for i in filtered])  # one version picked: nothing to compare

    def test_names_come_from_what_the_collector_saw_and_the_app_name_is_left_out(self):
        for route in ("/a", "/b", "/c"):
            self.send([{"type": "page", "route": route, "label": "ndesk"}])
        self.send([{"type": "page", "route": "/config/usuarios", "label": "Usuários"},
                   {"type": "inventory", "route": "/config/usuarios", "targets": ["button#new", "a#help"], "labels": ["Novo usuário"]},
                   {"type": "click", "route": "/config/usuarios", "target": "a#help", "label": "Ajuda"},
                   {"type": "action", "route": "/config/usuarios", "detail": "POST /api/users", "clicks": 2, "label": "Salvar"}])
        n = self.read("/api/names?project=shop")
        self.assertEqual(n["screens"], {"/config/usuarios": "Usuários"})
        self.assertEqual(n["controls"], {"/config/usuarios\tbutton#new": "Novo usuário", "/config/usuarios\ta#help": "Ajuda"})
        self.assertEqual(n["actions"], {"POST /api/users": "Salvar"})
        self.assertEqual(call(self.base, "/api/names?project=shop")[0], 401)
        found = self.read("/api/search?project=shop&days=1&q=" + urllib.parse.quote("usuár"))["results"]  # by the names people use
        self.assertEqual({(r["kind"], r["label"]) for r in found}, {("screen", "/config/usuarios")})
        self.assertIn(("action", "POST /api/users"), {(r["kind"], r["label"]) for r in self.read("/api/search?project=shop&days=1&q=salvar")["results"]})

    def test_the_dictionary_names_screens_controls_actions_and_accounts_and_wins_over_auto(self):
        self.send([{"type": "page", "route": "/opp", "label": "Opps"},
                   {"type": "click", "route": "/opp", "target": "button#s", "label": "Salvar"}], account="4821")
        def name(kind, key, value):
            return call(self.base, "/api/names?project=shop", {"kind": kind, "key": key, "name": value}, cookie=self.cookie)[0]
        self.assertEqual(name("screen", "/opp", "  Oportunidades "), 200)
        self.assertEqual(name("control", "/opp\tbutton#s", "Criar oportunidade"), 200)
        self.assertEqual(name("account", "4821", "4821 · Contrato Acme Saúde"), 200)
        n = self.read("/api/names?project=shop")
        self.assertEqual((n["screens"]["/opp"], n["auto"]["screens"]["/opp"]), ("Oportunidades", "Opps"))
        self.assertEqual(n["controls"]["/opp\tbutton#s"], "Criar oportunidade")
        self.assertEqual(n["accounts"], {"4821": "4821 · Contrato Acme Saúde"})
        self.assertEqual(name("screen", "/opp", ""), 200)  # back to what the collector saw
        self.assertEqual(self.read("/api/names?project=shop")["screens"]["/opp"], "Opps")
        self.assertEqual(name("bogus", "/opp", "x"), 400)
        self.assertEqual(call(self.base, "/api/names?project=shop", {"kind": "screen", "key": "/opp", "name": "x"})[0], 401)

    def feature(self, body):
        status, _, out = call(self.base, "/api/features?project=shop", body, cookie=self.cookie)
        self.assertEqual(status, 200, out)
        return json.loads(out)["id"]

    def test_a_watched_feature_counts_its_uses_and_narrows_every_read(self):
        create = {"type": "action", "route": "/opp", "detail": "POST /api/opps", "clicks": 2}
        self.send([{"type": "page", "route": "/opp"}, create, create,
                   {"type": "rage", "route": "/opp", "target": "button#save"},
                   {"type": "http_5xx", "route": "/opp", "detail": "POST /api/opps 500"},
                   {"type": "page", "route": "/home"}], user="u1", account="a1")
        self.send([{"type": "page", "route": "/home"}], user="u2", account="a2")
        fid = self.feature({"name": "Criar oportunidade", "rules": [{"kind": "action", "key": "POST /api/opps"},
                                                                   {"kind": "screen", "key": "/opp"}]})
        [ft] = self.read("/api/features?project=shop&days=7")["features"]
        self.assertEqual({k: ft[k] for k in ("id", "name", "uses", "users", "accounts", "adoption", "failures")},
                         {"id": fid, "name": "Criar oportunidade", "uses": 2, "users": 1, "accounts": 1, "adoption": 0.5, "failures": 1})
        # 2: with an action in it, a use is the write; the visit to its screen is not counted again
        s = self.read(f"/api/summary?project=shop&days=7&feature={fid}")
        self.assertEqual([r["key"] for r in s["routes"]], ["/opp"])  # /home is outside the feature
        self.assertEqual(call(self.base, "/api/features?project=shop", {"name": "x", "rules": []}, cookie=self.cookie)[0], 400)
        self.assertEqual(call(self.base, "/api/features?project=shop", {"name": "criar oportunidade", "rules": [{"kind": "screen", "key": "/x"}]},
                              cookie=self.cookie)[0], 400)  # the same name twice would read as one feature
        self.feature({"id": fid, "delete": True})
        self.assertEqual(self.read("/api/features?project=shop&days=7")["features"], [])

    def test_a_followed_item_keeps_its_baseline_and_says_if_it_got_better(self):
        page, rage = {"type": "page", "route": "/users"}, {"type": "rage", "route": "/users", "target": "button#save"}
        fail = {"type": "http_5xx", "route": "/users", "detail": "POST /api/users 500"}
        self.send([page, rage, rage, fail] * 5, session="s1", version="1.6")
        follow = lambda body, q="project=shop&days=7": call(self.base, "/api/follow?" + q, body, cookie=self.cookie)
        status, _, out = follow({"kind": "screen", "key": "/users", "label": "Usuários"})
        self.assertEqual(status, 200, out)
        sid = json.loads(out)["id"]
        self.assertEqual(json.loads(follow({"kind": "screen", "key": "/users"})[2])["id"], sid)  # once per thing
        fid = json.loads(follow({"kind": "failure", "key": "http_5xx\tPOST /api/users 500", "label": "Salvar"})[2])["id"]
        items = {x["id"]: x for x in self.read("/api/follow?project=shop&days=7")["items"]}
        s = items[sid]
        self.assertEqual((s["label"], s["metric"], s["before"], s["version"], s["state"], s["now"]),
                         ("Usuários", "score", 100, "1.6", "waiting", None))  # nothing since it was followed
        self.assertEqual(items[fid]["before"], 500.0)  # 5 per session, per 100 sessions
        self.assertEqual(items[fid]["link"], {"tab": "failures", "params": {"signal": "http_5xx", "detail": "POST /api/users 500"}})
        # after the fix: calm visits, and the failure gone
        for n in range(4):
            self.send([page, page, page], session=f"n{n}", version="1.7")
        items = {x["id"]: x for x in self.read("/api/follow?project=shop&days=7")["items"]}
        self.assertEqual((items[sid]["now"], items[sid]["state"]), (0, "better"))
        self.assertEqual((items[fid]["now"], items[fid]["state"]), (0, "better"))
        # people only write; an unknown project or kind says no
        self.assertEqual(call(self.base, "/api/follow?project=shop", {"kind": "screen", "key": "/x"})[0], 401)
        self.assertEqual(follow({"kind": "screen", "key": "/x"}, "project=nope")[0], 404)
        self.assertEqual(follow({"kind": "person", "key": "u1"})[0], 400)
        self.assertEqual(call(self.base, f"/api/follow?project=shop&id={sid}", method="DELETE")[0], 401)
        self.assertEqual(call(self.base, f"/api/follow?project=shop&id={sid}", method="DELETE", cookie=self.cookie)[0], 200)
        self.assertEqual([x["id"] for x in self.read("/api/follow?project=shop&days=7")["items"]], [fid])

    def test_follow_state_has_a_tolerance_per_metric(self):
        self.assertEqual(t.follow_state("score", True, 60, 64), "same")
        self.assertEqual(t.follow_state("score", True, 60, 50), "better")
        self.assertEqual(t.follow_state("failure", True, 10, 11.5), "same")  # within 20%
        self.assertEqual(t.follow_state("failure", True, 10, 13), "worse")
        self.assertEqual(t.follow_state("people", False, 4, 6), "better")  # more people a day is better
        self.assertEqual(t.follow_state("clicks", True, 3, 3.8), "same")  # within a click

    def test_engagement_shows_an_account_fading_in_people_and_in_a_feature(self):
        create = {"type": "action", "route": "/opp", "detail": "POST /api/opps", "clicks": 1}
        for u in ("u1", "u2", "u3"):  # the month before: 3 people, 12 creations
            self.send([{"type": "page", "route": "/opp"}] + [create] * 4, user=u, account="a1", session=u)
        self.age(25)
        self.send([{"type": "page", "route": "/opp"}, create], user="u1", account="a1", session="now")
        self.send([{"type": "page", "route": "/home"}], user="u9", account="a2", session="other")
        self.age(10)  # before: 35 days ago; now: 10 days ago and today; 20-day windows
        self.send([{"type": "page", "route": "/home"}], user="u9", account="a2", session="today")
        fid = self.feature({"name": "Criar oportunidade", "rules": [{"kind": "action", "key": "POST /api/opps"}]})
        e = self.read("/api/engagement?project=shop&days=20")
        self.assertTrue(e["comparable"])
        a1 = next(r for r in e["accounts"] if r["account"] == "a1")
        self.assertEqual(e["accounts"][0]["account"], "a1")  # drops first
        self.assertEqual([d["what"] for d in a1["drops"]], ["feature"])
        self.assertEqual((a1["drops"][0]["before"], a1["drops"][0]["now"]), (12, 1))
        self.assertEqual(a1["features"], [{"id": fid, "now": 1, "before": 12, "move": "down"}])
        self.assertEqual(a1["trend"], "down")
        daily = self.read("/api/engagement?project=shop&days=40&account=a1")["daily"]
        self.assertEqual(sum(d["features"].get(fid, 0) for d in daily), 13)
        kinds = [i["kind"] for i in self.read("/api/overview?project=shop&days=20")["insights"]]
        self.assertIn("account_feature_drop", kinds)

    def test_engagement_says_the_trend_of_each_account_and_puts_the_falling_first(self):
        def visit(account, users, prefix):
            for i in range(users):
                self.send([{"type": "page", "route": "/home"}], user=f"{account}-{prefix}{i}", account=account, session=f"{account}-{prefix}{i}")
        self.send([{"type": "page", "route": "/home"}], session="first")  # the project was already sending before
        self.age(1)
        visit("up", 1, "b"); visit("down", 12, "b"); visit("flat", 3, "b")
        self.age(1.5)  # inside the 24 hours before
        visit("up", 12, "n"); visit("down", 1, "n"); visit("flat", 3, "n")
        e = self.read("/api/engagement?project=shop&days=1")
        self.assertTrue(e["comparable"])
        self.assertEqual([(r["account"], r["trend"]) for r in e["accounts"]], [("down", "down"), ("flat", "flat"), ("up", "up")])
        down = e["accounts"][0]
        self.assertEqual(down["moves"], {"users_day": "down", "sessions_day": "down"})
        self.assertEqual([d["what"] for d in down["drops"]], ["users_day"])  # the alerts keep their own rule

    def test_accounts_say_how_much_they_suffer_now_and_before(self):
        page, rage = {"type": "page", "route": "/cart"}, {"type": "rage", "route": "/cart", "target": "button#pay"}
        fail = {"type": "http_5xx", "route": "/cart", "target": "button#pay", "detail": "POST /api/pay 500"}
        self.send([page], session="first")
        self.age(1)
        self.send([page] * 10 + [rage], account="a1", user="u1", session="b1")  # before: calm, no failure
        self.age(1.5)
        self.send([page, page, rage, fail, fail], account="a1", user="u1", session="n1")  # now: suffering
        [a1] = [a for a in self.read("/api/engagement?project=shop&days=1")["accounts"] if a["account"] == "a1"]
        self.assertEqual((a1["now"]["score"], a1["now"]["failures"]), (100, 2))
        self.assertEqual((a1["before"]["score"], a1["before"]["failures"]), (6, 0))

    def test_usage_people_product_and_features_carry_the_period_before(self):
        page = {"type": "page", "route": "/cart"}
        click = {"type": "click", "route": "/cart", "target": "button#pay"}
        self.send([{"type": "page", "route": "/home"}], session="first")
        self.age(1)
        for i in range(4):  # before: four sessions on the cart, one of them paying
            self.send([page] + ([click] if not i else []), session=f"b{i}", user=f"u{i}", role="agent")
        self.age(1.5)
        for i in range(2):  # now: two sessions on the cart, both paying; one more only at home
            self.send([page, click], session=f"n{i}", user=f"u{i}", role="agent")
        self.send([{"type": "page", "route": "/home"}], session="n9", user="u9", role="agent")
        u = self.read("/api/usage?project=shop&days=1")
        cart = next(x for x in u["screens"] if x["route"] == "/cart")
        self.assertTrue(u["comparable"])
        self.assertEqual((cart["visits"], cart["before"]["visits"], cart["before"]["clicks"]), (2, 4, 1))
        el = self.read("/api/usage?project=shop&days=1&route=/cart")
        self.assertEqual((el["visits_before"], el["elements"][0]["before"]), (4, 1))
        [role] = self.read("/api/people?project=shop&days=1")["roles"]
        self.assertEqual((role["visits"], role["before"]["visits"]), (3, 4))
        areas = {a["area"]: a for a in self.read("/api/product?project=shop&days=1")["areas"]}
        # everyone active used both areas would read 100% adoption; the share of the sessions tells them apart
        self.assertEqual((areas["Cart"]["session_share"], areas["Cart"]["before"]["visits"], areas["Cart"]["before"]["session_share"]),
                         (0.667, 4, 1.0))
        fid = self.feature({"name": "Pagar", "rules": [{"kind": "control", "key": "/cart\tbutton#pay"}]})
        [ft] = self.read("/api/features?project=shop&days=1")["features"]
        self.assertEqual((ft["uses"], ft["before"], ft["session_share"]), (2, 1, 0.667))
        self.assertEqual((ft["before_detail"]["users"], ft["before_detail"]["session_share"]), (1, 0.25))
        self.assertTrue(fid)

    def test_trend_rule_is_the_drop_and_its_mirror_beyond_chance(self):
        self.assertEqual(t.move(210, 60, True), "down")
        self.assertEqual(t.move(22, 11, True), "flat")  # a small count halving is chance
        self.assertEqual(t.move(210, 60, False), "flat")  # too small before for a drop to mean something
        self.assertEqual(t.move(60, 210, True), "up")
        self.assertEqual(t.move(11, 22, True), "flat")
        self.assertEqual(t.move(0, 14, False), "up")  # came from nothing

    def test_summary_compares_each_screen_and_the_whole_with_the_period_before(self):
        page = {"type": "page", "route": "/cart"}
        self.send([{"type": "page", "route": "/home"}], session="first")
        self.age(1)
        self.send([page] * 10 + [{"type": "rage", "route": "/cart", "target": "button#pay"}], session="before")
        self.age(1.5)
        self.send([page, page, {"type": "rage", "route": "/cart", "target": "button#pay"},
                   {"type": "http_5xx", "route": "/cart", "target": "button#pay", "detail": "POST /api/pay 500"}], session="now")
        s = self.read("/api/summary?project=shop&days=1")
        self.assertEqual(s["before"], {"visits": 10, "sessions": 1, "score": 6})
        [cart] = s["routes"]
        self.assertEqual((cart["score"], cart["before"]["score"], cart["before"]["visits"]), (80, 6, 10))
        self.assertIsNone(self.read("/api/summary?project=shop&days=7")["before"])  # no week before with data

    def test_product_health_groups_screens_into_areas_and_finds_little_used_and_new_buttons(self):
        inv = {"type": "inventory", "route": "/config/users", "targets": ["button#new", "button#export"]}
        for i in range(30):
            self.send([{"type": "page", "route": "/config/users"}, inv] + ([{"type": "click", "route": "/config/users", "target": "button#new"}] if i % 2 else []),
                      session=f"s{i}", user=f"u{i}")
        self.send([{"type": "page", "route": "/config/roles"}, {"type": "page", "route": "/home"}], session="x", user="u1")
        name = lambda kind, key, v: call(self.base, "/api/names?project=shop", {"kind": kind, "key": key, "name": v}, cookie=self.cookie)
        name("area", "/home", "Painel")
        p = self.read("/api/product?project=shop&days=7")
        areas = {a["area"]: a for a in p["areas"]}
        self.assertEqual(set(areas), {"Config", "Painel"})
        self.assertEqual([s["route"] for s in areas["Config"]["screens"]], ["/config/users", "/config/roles"])
        self.assertEqual((areas["Config"]["visits"], areas["Config"]["users"]), (31, 30))
        self.assertEqual([(x["target"], x["sessions"], x["clicked"]) for x in p["low_use"]], [("button#export", 30, 0)])
        self.assertEqual(p["new"], [])  # everything is new on the first day: nothing is called new
        with t.connect() as con:  # a button that showed up two days after the project started
            con.execute("UPDATE events SET at = at - 3 * 86400000")
            con.execute("UPDATE elements SET first_seen = first_seen - 3 * 86400000")
            con.execute("UPDATE elements SET first_seen = ? WHERE target = 'button#export'", (int(time.time() * 1000) - 86400000,))
        self.send([{"type": "page", "route": "/config/users"}, {"type": "click", "route": "/config/users", "target": "button#export"}], session="late")
        [x] = self.read("/api/product?project=shop&days=7")["new"]
        self.assertEqual((x["target"], x["sessions"], x["share"]), ("button#export", 1, 1.0))

    def test_a_persons_name_is_kept_apart_and_only_where_the_project_allows_it(self):
        self.send([{"type": "page", "route": "/a"}], user="u1", user_name="  Maria   Souza ")
        self.send([{"type": "page", "route": "/a"}], key="tk_blog", origin=None, user="u2", user_name="João")
        self.assertEqual(self.read("/api/names?project=shop")["people"], {"u1": "Maria Souza"})
        self.assertIn(("user", "u1"), {(r["kind"], r["label"]) for r in self.read("/api/search?project=shop&days=1&q=souza")["results"]})
        t.CONFIG.projects[KEY]["people_names"] = False  # as "people_names": false in TERMOMETRO_PROJECTS
        self.send([{"type": "page", "route": "/a"}], user="u3", user_name="Ana")
        self.assertNotIn("u3", self.read("/api/names?project=shop")["people"])
        report = json.dumps(self.read("/api/report?project=shop&days=1"))
        self.assertNotIn("Maria", report)  # names never go to the document an AI reads
        with t.connect() as con:
            con.execute("UPDATE people SET last_seen = 0")
            t.apply_retention(con)
            self.assertEqual(con.execute("SELECT COUNT(*) FROM people").fetchone()[0], 0)

    def test_frustration_splits_by_kind_and_effort_stays_apart(self):
        self.send([{"type": "page", "route": "/cart"}] * 10
                  + [{"type": "rage", "route": "/cart", "target": "b"}] * 2 + [{"type": "dead", "route": "/cart", "target": "b"}]
                  + [{"type": "http_5xx", "route": "/cart", "detail": "POST /x 500"}, {"type": "slow", "route": "/cart", "detail": "GET /y"}]
                  + [{"type": "abandon", "route": "/cart", "target": "form"}]
                  + [{"type": "action", "route": "/cart", "detail": "POST /o", "clicks": c} for c in (3, 5, 9)])
        cart = self.read("/api/summary?project=shop&days=1")["routes"][0]
        # (2x3 + 2 + 5 + 1 + 2) / 10 visits x 20 = 32; each kind is its own points over the same visits
        self.assertEqual((cart["score"], cart["categories"]),
                         (32, {"irritation": 12, "no_effect": 4, "failure": 10, "slowness": 2, "giving_up": 4}))
        self.assertEqual(cart["effort"], {"clicks": 5, "actions": 3, "here_median": None, "path_median": None})  # older collectors
        k = self.read("/api/overview?project=shop&days=1")["kinds"]
        self.assertEqual((k["now"]["irritation"], k["effort"]["now"]["clicks"], len(k["daily"])), (12, 5, 1))

    def test_rage_clicks_carry_their_likely_reason(self):
        rage = lambda why: {"type": "rage", "route": "/cart", "target": "button#pay", "detail": why}
        self.send([{"type": "page", "route": "/cart"}] * 10 + [rage("waiting")] * 3 + [rage("nothing")] + [rage("")] * 2
                  + [{"type": "rage", "route": "/cart", "target": "button#pay"}] * 2)
        [pay] = [t for t in self.read("/api/summary?project=shop&days=1")["routes"][0]["targets"] if t["type"] == "rage"]
        self.assertEqual((pay["n"], pay["reasons"]), (8, {"waiting": 3, "nothing": 1}))  # older collectors send no reason
        o = self.read("/api/overview?project=shop&days=1")
        self.assertEqual(o["kinds"]["rage_reasons"], {"waiting": 3, "nothing": 1})
        [irr] = [i for i in o["insights"] if i["kind"] == "element_irritating"]
        self.assertEqual(irr["reason"], "waiting")

    def test_click_patterns_focus_follow_enter_retry_and_near_miss(self):
        page = lambda r: {"type": "page", "route": r}
        clk = lambda r, t: {"type": "click", "route": r, "target": t}
        for i in range(20):
            evs = [page("/users"), clk("/users", "form#f > input#name"),           # always clicks the name field first
                   clk("/users", "button#new"), clk("/users", "div#dlg > input#email"),  # opens the dialog, clicks its field
                   {"type": "typed", "route": "/users", "target": "input#q"}, clk("/users", "button#search")]  # never Enter
            if i < 6:
                evs += [clk("/users", "button#save"), {"type": "retry", "route": "/users", "target": "button#save"},
                        {"type": "near_miss", "route": "/users", "target": "button#tiny"}]
            self.send(evs, session=f"s{i}")
        p = self.read("/api/patterns?project=shop&days=1")
        self.assertEqual([(x["route"], x["target"], x["share"]) for x in p["focus"]], [("/users", "form#f > input#name", 1.0)])
        follow = {(x["target"], x["next_target"]): x for x in p["follows"]}
        self.assertTrue(follow[("button#new", "div#dlg > input#email")]["to_field"])
        [ne] = p["no_enter"]
        self.assertEqual((ne["target"], ne["next_target"], ne["share"], ne["enter_share"]), ("input#q", "button#search", 1.0, 0.0))
        self.assertEqual((p["retry"][0]["target"], p["retry"][0]["n"]), ("button#save", 6))
        self.assertEqual((p["near_miss"][0]["target"], p["near_miss"][0]["n"]), ("button#tiny", 6))
        kinds = {i["kind"] for i in self.read("/api/overview?project=shop&days=1")["insights"]}
        self.assertTrue({"focus_candidate", "click_follows", "search_no_enter", "retry_needed", "near_miss"} <= kinds, kinds)

    def test_effort_splits_the_way_to_the_screen_from_the_clicks_on_it(self):
        act = lambda c, h: {"type": "action", "route": "/users", "detail": "POST /api/users", "clicks": c, "here": h}
        self.send([{"type": "page", "route": "/users"}, act(5, 2), act(7, 3), act(4, 2)])
        [a] = self.read("/api/actions?project=shop&days=1")["actions"]
        self.assertEqual((a["clicks_median"], a["here_median"], a["path_median"]), (5, 2, 3))
        users = self.read("/api/summary?project=shop&days=1")["routes"][0]
        self.assertEqual((users["effort"]["here_median"], users["effort"]["path_median"]), (2, 3))
        e = self.read("/api/overview?project=shop&days=1")["kinds"]["effort"]["now"]
        self.assertEqual((e["clicks"], e["here_median"], e["path_median"]), (5, 2, 3))

    def test_the_way_to_a_button_shows_where_people_looked_for_it_first(self):
        page = lambda r: {"type": "page", "route": r}
        clk = lambda r, t: {"type": "click", "route": r, "target": t}
        for i in range(20):  # everyone starts at home; most look in Reports before finding Export in Stats
            evs = [page("/"), clk("/", "a#menu")]
            if i < 14:
                evs += [page("/reports"), clk("/reports", "button#filter"), clk("/reports", "button#tab")]
            evs += [page("/stats"), clk("/stats", "button#export")]
            self.send(evs, session=f"e{i}")
        for i in range(20):  # the way to something else: home only
            self.send([page("/"), clk("/", "a#menu"), page("/users"), clk("/users", "button#new")], session=f"o{i}")
        ways = {(w["route"], w["key"]): w for w in self.read("/api/ways?project=shop&days=1")["ways"]}
        export = ways[("/stats", "button#export")]
        [looked] = export["looked_elsewhere"]
        self.assertEqual((looked["route"], looked["share"], looked["browsed"]), ("/reports", 0.7, 0.7))
        self.assertEqual(ways[("/users", "button#new")]["looked_elsewhere"], [])  # home is on every way: not a sign
        kinds = [i for i in self.read("/api/overview?project=shop&days=1")["insights"] if i["kind"] == "looked_elsewhere"]
        self.assertEqual((kinds[0]["key"], kinds[0]["via"]), ("button#export", "/reports"))

    def test_something_left_unfinished_to_fetch_elsewhere_and_finished_on_coming_back(self):
        page = lambda r: {"type": "page", "route": r}
        for i in range(24):
            evs = [page("/tickets/new"), {"type": "typed", "route": "/tickets/new", "target": "input#subject"}]
            if i < 12:  # leaves to look up the customer, comes back and saves
                evs += [{"type": "abandon", "route": "/tickets/new", "target": "form#ticket"}, page("/customers"),
                        {"type": "click", "route": "/customers", "target": "a#row"}, page("/tickets/new")]
            if i in (6, 7, 8):  # leaves the browser for a while
                evs += [{"type": "away", "route": "/tickets/new", "target": "form#ticket", "duration_ms": 40000}]
            evs += [{"type": "action", "route": "/tickets/new", "detail": "POST /api/tickets", "clicks": 3}]
            self.send(evs, session=f"t{i}")
        [fm] = [x for x in self.read("/api/patterns?project=shop&days=1")["forms"] if x["route"] == "/tickets/new"]
        self.assertEqual((fm["started"], fm["detours"], fm["share"], fm["form"]), (24, 12, 0.5, "form#ticket"))
        self.assertEqual(fm["via"], [{"route": "/customers", "share": 1.0}])
        self.assertEqual((fm["away"], fm["away_share"], fm["away_seconds"]), (3, 0.12, 40))
        kinds = {i["kind"] for i in self.read("/api/overview?project=shop&days=1")["insights"]}
        self.assertIn("form_detour", kinds)
        self.assertNotIn("form_away", kinds)  # 3 times is under the minimum of 10

    def test_usage_of_a_screen_carries_its_click_routes_for_the_map(self):
        clk = lambda t: {"type": "click", "route": "/users", "target": t}
        for i in range(3):
            self.send([{"type": "page", "route": "/users"}, clk("button#new"), clk("input#email"), clk("button#save")], session=f"r{i}")
        self.send([{"type": "page", "route": "/users"}, clk("button#new"), clk("button#new")], session="x")  # a repeat is no route
        u = self.read("/api/usage?project=shop&days=1&route=/users")
        self.assertEqual([(p["from"], p["to"], p["n"]) for p in u["paths"]],
                         [("button#new", "input#email", 3), ("input#email", "button#save", 3)])

    def test_usage_of_a_screen_carries_its_latest_layout_per_kind_of_window(self):
        def inv(vw, boxes, targets=("button#new", "a#help", "span.x"), **extra):
            return {"type": "inventory", "route": "/users", "targets": list(targets), "labels": ["Novo", "Ajuda", ""],
                    "layout": {"vw": vw, "vh": 800, "dw": vw, "dh": 1600, "boxes": boxes, **extra}}
        self.assertEqual(self.read("/api/usage?project=shop&route=/users")["layout"], None)  # an older collector: no preview
        self.send([{"type": "page", "route": "/users"}, inv(1280, [[10.4, 20, 80, 32], None, [1, 1, 0, 5]],
                   landmarks=[{"kind": "main", "box": [0, 60, 1280, 700]}, {"kind": "script", "box": [0, 0, 1, 1]}, {"kind": "nav"},
                                {"kind": "title", "box": [20, 70, 300, 28]}])])
        self.send([inv(390, [[5, 5, 40, 40], [5, 50, 40, 40], None])], session="m")
        self.send([inv(1280, "junk"), inv(1280, [["a", 1, 2, 3]] * 3), {"type": "inventory", "route": "/users", "targets": ["b"], "layout": {"vw": "x"}}],
                  session="bad")  # no box to draw: the earlier picture stays
        u = self.read("/api/usage?project=shop&route=/users")
        self.assertEqual(u["layouts"], ["desktop", "mobile"])
        lay = u["layout"]
        self.assertEqual((lay["viewport"], lay["vw"], lay["vh"], lay["dw"], lay["dh"]), ("desktop", 1280, 800, 1280, 1600))
        self.assertEqual(lay["boxes"], {"button#new": [10, 20, 80, 32]})  # hidden and empty boxes left out, whole pixels
        self.assertEqual(lay["landmarks"], [{"kind": "main", "box": [0, 60, 1280, 700]}, {"kind": "title", "box": [20, 70, 300, 28]}])  # only known kinds
        self.assertEqual(lay["labels"], {"button#new": "Novo"})
        m = self.read("/api/usage?project=shop&route=/users&viewport=mobile")["layout"]
        self.assertEqual((m["viewport"], m["boxes"]), ("mobile", {"button#new": [5, 5, 40, 40], "a#help": [5, 50, 40, 40]}))
        # the most recent picture replaces the one before, whole: never a mix of two layouts
        self.send([inv(1440, [None, [100, 10, 60, 20], None])], session="later")
        lay = self.read("/api/usage?project=shop&route=/users")["layout"]
        self.assertEqual((lay["vw"], lay["boxes"]), (1440, {"a#help": [100, 10, 60, 20]}))
        # the inventory still lists every target, with or without a box
        self.assertEqual(self.read("/api/usage?project=shop&route=/users")["never_clicked"], ["a#help", "b", "button#new", "span.x"])
        # what a click opened (a dialog) is an addition: it joins the drawing and outlives the next whole picture
        self.send([{"type": "inventory", "route": "/users", "targets": ["input#email"], "labels": ["E-mail"],
                    "layout": {"vw": 1440, "vh": 800, "dw": 1440, "dh": 1600, "boxes": [[500, 300, 200, 30]], "partial": True,
                               "landmarks": [{"kind": "dialog", "box": [450, 250, 400, 200]}]}}], session="dlg")
        self.send([inv(1440, [[10, 20, 80, 32], [100, 10, 60, 20], None])], session="closed")
        lay = self.read("/api/usage?project=shop&route=/users")["layout"]
        self.assertEqual(lay["boxes"], {"input#email": [500, 300, 200, 30], "button#new": [10, 20, 80, 32], "a#help": [100, 10, 60, 20]})
        self.assertEqual(lay["landmarks"], [{"kind": "dialog", "box": [450, 250, 400, 200]}])
        with t.connect() as con:
            t.apply_retention(con, now=time.time() + 400 * 86400)
            self.assertEqual(con.execute("SELECT COUNT(*) FROM layouts").fetchone()[0], 0)

    def test_usage_of_a_screen_says_why_each_element_irritated(self):
        self.send([{"type": "page", "route": "/u"}, {"type": "click", "route": "/u", "target": "button#s"},
                   {"type": "rage", "route": "/u", "target": "button#s", "detail": "waiting"},
                   {"type": "rage", "route": "/u", "target": "button#s", "detail": "waiting"},
                   {"type": "rage", "route": "/u", "target": "button#s", "detail": "error"}])
        e = self.read("/api/usage?project=shop&route=/u")["elements"][0]
        self.assertEqual((e["rage"], e["reasons"]), (3, {"waiting": 2, "error": 1}))

    def test_search_finds_screens_elements_failures_actions_and_ids(self):
        self.send([{"type": "page", "route": "/orders"}, {"type": "click", "route": "/orders", "target": "button#export-orders"},
                   {"type": "js_error", "route": "/orders", "detail": "TypeError: orders is undefined"},
                   {"type": "action", "route": "/orders", "detail": "POST /api/orders", "clicks": 2, "duration_ms": 10}],
                  user="u-orders-1", account="acc-9")
        r = self.read("/api/search?project=shop&days=1&q=ORDERS")["results"]
        self.assertEqual(sorted({x["kind"] for x in r}), ["action", "element", "failure", "screen", "user"])
        self.assertEqual(next(x for x in r if x["kind"] == "element")["link"], {"tab": "usage", "params": {"route": "/orders"}})
        self.assertEqual(self.read("/api/search?project=shop&days=1&q=acc-9")["results"][0]["kind"], "account")
        self.assertEqual(self.read("/api/search?project=shop&days=1&q=o")["results"], [])  # too short to mean anything

    def test_events_take_the_browser_time_lined_up_with_the_server_and_keep_browser_and_stack(self):
        sent = 1_000_000_000_000
        call(self.base, "/api/events", {"key": KEY, "version": "1.0", "session": "s9", "device": "phone", "sent": sent, "events": [
            {"type": "page", "route": "/a", "t": sent - 60_000},
            {"type": "js_error", "route": "/a", "detail": "TypeError: x", "stack": "f @ /app.js:1:2", "t": sent - 1000},
            {"type": "click", "route": "/a", "target": "button#b", "stack": "ignored", "t": sent - 30 * 86400_000}]}, origin=ORIGIN)
        with t.connect() as con:
            rows = con.execute("SELECT type, at, stack, device FROM events WHERE session = 's9' ORDER BY id").fetchall()
        (_, page_at, _, device), (_, error_at, stack, _), (_, click_at, click_stack, _) = rows
        self.assertEqual(error_at - page_at, 59_000)           # the gap the browser saw, on the server's clock
        self.assertLessEqual(abs(int(time.time() * 1000) - 86400_000 - click_at), 5000)  # a wild clock is capped at a day
        self.assertEqual((stack, click_stack, device), ("f @ /app.js:1:2", "", "phone"))
        self.assertEqual(t.agent_of("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
                                    "Chrome/130.0.0.0 Safari/537.36"), "Chrome 130 · macOS")
        self.assertEqual(t.agent_of("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) "
                                    "Version/17.0 Mobile/15E148 Safari/604.1"), "Safari 17 · iOS")

    def test_an_old_database_gets_the_new_columns(self):
        import sqlite3
        db = Path(tempfile.mkdtemp()) / "old.db"
        con = sqlite3.connect(db)
        con.execute("""CREATE TABLE events (id INTEGER PRIMARY KEY, project TEXT NOT NULL, version TEXT NOT NULL, session TEXT NOT NULL,
            account TEXT NOT NULL DEFAULT '', user_id TEXT NOT NULL DEFAULT '', role TEXT NOT NULL DEFAULT '', type TEXT NOT NULL,
            route TEXT NOT NULL, target TEXT NOT NULL DEFAULT '', detail TEXT NOT NULL DEFAULT '', clicks INTEGER, duration_ms INTEGER,
            at INTEGER NOT NULL)""")
        con.execute("INSERT INTO events (project, version, session, type, route, at) VALUES ('shop', '1', 's', 'page', '/', 1)")
        con.commit(); con.close()
        t.CONFIG.db = db
        with t.connect() as con:
            self.assertEqual(con.execute("SELECT stack, agent, device FROM events").fetchone(), ("", "", ""))

    def test_failures_are_grouped_and_one_shows_its_trail_stack_and_browsers(self):
        sent = int(time.time() * 1000)
        steps = [{"type": "page", "route": "/orders", "t": sent - 5000},
                 {"type": "click", "route": "/orders", "target": "button#export", "t": sent - 3000},
                 {"type": "js_error", "route": "/orders", "target": "button#export", "detail": "TypeError: rows", "stack": "load @ /a.js:1:2",
                  "t": sent - 2000},
                 {"type": "click", "route": "/orders", "target": "button#retry", "t": sent - 1000}]
        for session in ("s1", "s2"):
            call(self.base, "/api/events", {"key": KEY, "version": "2.0", "session": session, "user": "u-" + session,
                                            "device": "desktop", "sent": sent, "events": steps}, origin=ORIGIN)
        self.send([{"type": "http_4xx", "route": "/x", "detail": "GET /api/x 404"}], session="s3")
        [first, second] = self.read("/api/failures?project=shop&days=1")["failures"]
        self.assertEqual((first["type"], first["sessions"], first["users"], first["new"], first["first_version"]),
                         ("js_error", 2, 2, True, "2.0"))
        self.assertEqual(second["type"], "http_4xx")
        d = self.read("/api/failure?project=shop&days=1&signal=js_error&detail=TypeError%3A%20rows")
        self.assertEqual((d["n"], d["sessions"], d["stacks"], d["after_clicking"]),
                         (2, 2, [{"key": "load @ /a.js:1:2", "n": 2}], [{"key": "button#export", "n": 2}]))
        self.assertEqual(d["devices"], [{"key": "desktop", "n": 2}])
        trail = d["trails"][0]
        self.assertEqual([s["type"] for s in trail["before"]], ["page", "click"])
        self.assertEqual((trail["failure"]["type"], [s["target"] for s in trail["after"]]), ("js_error", ["button#retry"]))
        self.assertEqual(trail["before"][1]["at"] - trail["before"][0]["at"], 2000)
        whole = self.read("/api/session?project=shop&days=1&session=s1")
        self.assertEqual(([s["type"] for s in whole["steps"]], whole["user"]), (["page", "click", "js_error", "click"], "u-s1"))
        self.assertEqual(self.read("/api/failure?project=shop&days=1&signal=js_error&detail=nope")["n"], 0)

    def test_failures_have_a_count_per_day_and_the_detail_names_its_accounts_people_and_last_version(self):
        self.send([{"type": "js_error", "route": "/a", "detail": "E1"}] * 3, session="s1", user="u1", account="acme")
        self.age(2)
        self.send([{"type": "js_error", "route": "/a", "detail": "E1"}], session="s2", user="u2", account="beta", version="0.9")
        self.send([{"type": "page", "route": "/a"}], session="s3")
        self.age(1)
        self.send([{"type": "js_error", "route": "/a", "detail": "E1"}] * 3, session="s1", user="u1", account="acme", version="1.1")
        r = self.read("/api/failures?project=shop&days=7")
        self.assertEqual(len(r["days"]), 4)  # from the first event of the window to today, the quiet days too
        [f] = r["failures"]
        self.assertEqual(f["daily"], [3, 0, 1, 3])
        self.assertEqual(r["days"][-1], time.strftime("%Y-%m-%d", time.gmtime()))
        d = self.read("/api/failure?project=shop&days=7&signal=js_error&detail=E1")
        self.assertEqual((d["first_version"], d["last_version"]), ("1.0", "1.1"))
        self.assertEqual(d["account_list"], [{"key": "acme", "n": 6}, {"key": "beta", "n": 1}])
        self.assertEqual(d["people"], [{"key": "u1", "n": 6}, {"key": "u2", "n": 1}])
        self.assertEqual(len(d["days"]), 4)

    def test_journeys_show_how_far_things_are_what_follows_what_and_where_people_go(self):
        sent = int(time.time() * 1000)
        path = [{"type": "page", "route": "/home"}, {"type": "click", "route": "/home", "target": "a.menu"},
                {"type": "page", "route": "/tickets"}, {"type": "click", "route": "/tickets", "target": "a.row"},
                {"type": "page", "route": "/tickets/:id"}, {"type": "click", "route": "/tickets/:id", "target": "button.more"},
                {"type": "click", "route": "/tickets/:id", "target": "button.bulk"},
                {"type": "action", "route": "/tickets/:id", "detail": "POST /api/bulk", "clicks": 4, "duration_ms": 9000},
                {"type": "click", "route": "/tickets/:id", "target": "button#export"},
                {"type": "action", "route": "/tickets/:id", "detail": "POST /api/export", "clicks": 1, "duration_ms": 1000},
                {"type": "page", "route": "/home"}]
        for i in range(10):
            events = [{**e, "t": sent - (len(path) - n) * 1000} for n, e in enumerate(path)]
            call(self.base, "/api/events", {"key": KEY, "version": "1", "session": f"j{i}", "user": f"u{i}", "sent": sent,
                                            "events": events}, origin=ORIGIN)
        self.send([{"type": "page", "route": "/home"}], session="lonely")
        j = self.read("/api/journeys?project=shop&days=1")
        bulk = next(r for r in j["reach"] if r["key"] == "button.bulk")
        self.assertEqual((bulk["uses"], bulk["users"], bulk["clicks_median"], bulk["screens_median"], bulk["far"]), (10, 10, 3, 2, True))
        action = next(r for r in j["reach"] if r["key"] == "POST /api/bulk")
        self.assertEqual((action["clicks_median"], action["screens_median"], action["far"]), (4, 2, True))
        export = next(r for r in j["reach"] if r["key"] == "button#export")
        self.assertEqual((export["clicks_median"], export["screens_median"], export["far"]), (0, 0, False))  # right after the bulk save
        [pair] = j["pairs"]
        self.assertEqual((pair["a"], pair["b"], pair["n"], pair["share"], pair["linked"]), ("POST /api/bulk", "POST /api/export", 10, 1.0, True))
        home = next(x for x in j["screens"] if x["route"] == "/home")
        self.assertEqual({x["route"]: x["n"] for x in home["to"]}, {"/tickets": 10, "(exit)": 11})
        self.assertEqual(home["seconds_median"], 2.0)
        tickets = next(x for x in j["screens"] if x["route"] == "/tickets")
        self.assertEqual(tickets["from"], [{"route": "/home", "n": 10, "share": 1.0}])
        steps = urllib.parse.quote(json.dumps(["page:/home", "action:POST /api/bulk", "action:POST /api/export", "page:/nowhere"]))
        f = self.read(f"/api/funnel?project=shop&days=1&steps={steps}")["steps"]
        self.assertEqual([x["sessions"] for x in f], [11, 10, 10, 0])
        o = self.read("/api/overview?project=shop&days=1")
        self.assertTrue({"reach_far", "pair_linked"} <= {i["kind"] for i in o["insights"]})

    def test_report_has_everything_with_definitions_in_json_and_markdown(self):
        self.send([{"type": "page", "route": "/cart"}, {"type": "rage", "route": "/cart", "target": "button#pay"},
                   {"type": "js_error", "route": "/cart", "detail": "TypeError: x", "stack": "f @ /a.js:1:2"},
                   {"type": "action", "route": "/cart", "detail": "POST /api/orders", "clicks": 3, "duration_ms": 1000}])
        r = self.read("/api/report?project=shop&days=1")
        self.assertIn("rage", r["glossary"]["signals"])
        self.assertEqual(r["failures_in_depth"][0]["stacks"], [{"key": "f @ /a.js:1:2", "n": 1}])
        self.assertEqual(r["screens_by_frustration"][0]["key"], "/cart")
        status, headers, body = call(self.base, "/api/report?project=shop&days=1&format=md", cookie=self.cookie)
        md = body.decode()
        self.assertEqual((status, headers["Content-Type"]), (200, "text/markdown; charset=utf-8"))
        for part in ("# Termometro report — shop", "## How to read this", "TypeError: x", "f @ /a.js:1:2", "POST /api/orders"):
            self.assertIn(part, md)

    def test_an_api_token_reads_and_a_wrong_one_does_not(self):
        t.CONFIG.api_tokens = ["tt_good"]
        self.send([{"type": "page", "route": "/cart"}])
        status, _, body = call(self.base, "/api/overview?project=shop&days=1", token="tt_good")
        self.assertEqual((status, json.loads(body)["now"]["visits"]), (200, 1))
        self.assertEqual(call(self.base, "/api/overview?project=shop&days=1", token="tt_bad")[0], 401)
        self.assertEqual(json.loads(call(self.base, "/api/me", token="tt_good")[2])["projects"][0]["name"], "shop")

    def test_mcp_server_lists_tools_and_answers_through_the_api(self):
        import subprocess
        t.CONFIG.api_tokens = ["tt_mcp"]
        self.send([{"type": "page", "route": "/cart"}, {"type": "js_error", "route": "/cart", "detail": "TypeError: x"}])
        script = Path(t.STATIC) / "termometro_mcp.py"
        msgs = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
                {"jsonrpc": "2.0", "method": "notifications/initialized"},
                {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
                {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "failures", "arguments": {"days": 1}}},
                {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "report", "arguments": {"days": 1}}},
                {"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {"name": "list_projects", "arguments": {}}}]
        run = subprocess.run([sys.executable, str(script)], input="\n".join(json.dumps(m) for m in msgs) + "\n",
                             capture_output=True, text=True, timeout=30,
                             env={"TERMOMETRO_URL": self.base, "TERMOMETRO_TOKEN": "tt_mcp", "TERMOMETRO_PROJECT": "shop"})
        out = {m["id"]: m for m in map(json.loads, run.stdout.splitlines())}
        self.assertEqual(sorted(out), [1, 2, 3, 4, 5], run.stderr)
        self.assertIn("report", [x["name"] for x in out[2]["result"]["tools"]])
        failures = json.loads(out[3]["result"]["content"][0]["text"])["failures"]
        self.assertEqual(failures[0]["detail"], "TypeError: x")
        self.assertIn("# Termometro report — shop", out[4]["result"]["content"][0]["text"])
        self.assertEqual(json.loads(out[5]["result"]["content"][0]["text"])[0]["name"], "shop")

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
        self.assertEqual(screen["elements"][0], {"target": "button#save", "clicks": 2, "users": 1, "rage": 0, "dead": 1, "errors": 0, "retry": 0, "near_miss": 0, "label": "", "before": None,
                                                 "causes": [{"kind": "dead", "n": 1}]})
        self.assertEqual(screen["never_clicked"], ["button#delete"])

    def test_usage_says_why_an_element_irritates(self):
        self.send([{"type": "page", "route": "/u"}, {"type": "click", "route": "/u", "target": "button#save"},
                   *[{"type": "rage", "route": "/u", "target": "button#save", "detail": "waiting"}] * 3,
                   {"type": "rage", "route": "/u", "target": "button#save", "detail": "nothing"},
                   *[{"type": "slow", "route": "/u", "target": "button#save", "detail": "POST /api/users", "duration_ms": ms} for ms in (4000, 6000, 5000)],
                   *[{"type": "http_5xx", "route": "/u", "target": "button#save", "detail": "POST /api/users 500"}] * 2])
        causes = self.read("/api/usage?project=shop&route=/u")["elements"][0]["causes"]
        self.assertEqual(causes, [
            {"kind": "rage_waiting", "n": 3, "slow": "POST /api/users", "slow_n": 3, "slow_ms": 5000},
            {"kind": "failed", "n": 2, "detail": "POST /api/users 500"},
            {"kind": "rage_nothing", "n": 1}])

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
                         {"key": "77", "users": 2, "sessions": 2, "visits": 3, "clicks": 1, "score": 20, "screens": None, "before": None})
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
        self.assertEqual(self.read("/api/me")["projects"], [{"name": "shop", "url": ORIGIN, "key": KEY, "origins": [ORIGIN], "mark": None, "marks": []},
                                                            {"name": "blog", "url": "", "key": "tk_blog", "origins": [], "mark": None, "marks": []}])
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
        # The map inside the app still gets CORS for its reads (without it the browser drops the answer).
        token = json.loads(call(self.base, "/api/map-token?project=shop", {}, method="POST")[2])["token"]
        status, headers, _ = call(self.base, "/api/usage?project=shop&route=/t", origin=ORIGIN, token=token)
        self.assertEqual((status, headers.get("Access-Control-Allow-Origin")), (200, ORIGIN))
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

    def test_status_tells_why_a_view_is_empty(self):
        self.assertNotIn("in_view", self.read("/api/status?project=shop&days=7"))  # nothing ever: the setup screen
        self.send([{"type": "page", "route": "/old"}], version="1.0")
        self.age(10)
        s = self.read("/api/status?project=shop&days=7")
        self.assertFalse(s["in_view"])  # the period is empty...
        self.assertEqual(s["last_match"], s["last_at"])  # ...and says when the last event came
        self.assertTrue(self.read("/api/status?project=shop&days=30")["in_view"])
        self.assertIsNone(self.read("/api/status?project=shop&days=30&version=9.9")["last_match"])  # no such cut at all
        self.send([{"type": "page", "route": "/new"}], version="2.0")
        self.assertTrue(self.read("/api/status?project=shop&days=7")["in_view"])
        self.assertFalse(self.read("/api/status?project=shop&days=7&version=1.0")["in_view"])
        now = int(time.time() * 1000)
        call(self.base, "/api/mark?project=shop", {"action": "create", "name": "Depois", "at": now}, cookie=self.cookie)
        s = self.read("/api/status?project=shop&days=30&version=1.0")
        self.assertFalse(s["in_view"])  # hidden by the mark, not by the period...
        self.assertLess(s["last_match"], now)  # ...which the last match before it shows
        self.assertTrue(self.read("/api/status?project=shop&days=30&version=1.0&all=1")["in_view"])

    def test_google_is_off_without_a_client(self):
        self.assertEqual(call(self.base, "/auth/google")[0], 404)

    def test_static_files(self):
        status, headers, body = call(self.base, "/")
        self.assertEqual(status, 200)
        self.assertIn("default-src 'self'", headers["Content-Security-Policy"])
        status, headers, _ = call(self.base, "/map.js")
        self.assertEqual((status, headers["Access-Control-Allow-Origin"]), (200, "*"))


class Alerts(unittest.TestCase):
    def setUp(self):
        setup_config(TERMOMETRO_WEBHOOK_URL="https://hooks.example/x", TERMOMETRO_PUBLIC_URL="https://t.example")
        self.messages = []

    def store(self, version, events):
        _, rows, _ = t.parse_batch({"key": KEY, "version": version, "session": "s", "events": events}, ORIGIN)
        with t.connect() as con:
            con.executemany(t.INSERT_EVENT, rows)

    def deploy(self, version, rage, errors=0, visits=40):
        self.store(version, [{"type": "page", "route": "/cart"}] * visits +
                   [{"type": "rage", "route": "/cart", "target": "button#pay"}] * rage +
                   [{"type": "js_error", "route": "/cart", "detail": f"TypeError: new in {version}"}] * errors)

    def check(self, ok=True):
        def send(url, message):
            self.messages.append((url, message))
            return ok
        with t.connect() as con:
            return t.check_alerts(con, send)

    def test_warns_once_when_the_latest_version_makes_a_screen_worse_or_brings_a_new_failure(self):
        self.deploy("1.0", rage=4)
        self.assertEqual(self.check(), 0)  # nothing to compare with yet
        self.deploy("1.1", rage=20, errors=6)
        self.assertEqual(self.check(), 2)
        [(url, message)] = self.messages
        self.assertEqual(url, "https://hooks.example/x")
        self.assertEqual(message.splitlines(), [
            "Termometro · shop 1.1 got worse than 1.0",
            "• /cart: frustration 6 → 45 (40 visits)",  # 4 x 3 / 40 * 20 = 6; (20 x 3 + 6 x 5) / 40 * 20 = 45
            "• New failure on /cart: TypeError: new in 1.1 (6×)",
            "https://t.example/#versions"])
        self.assertEqual(self.check(), 0)  # already warned

    def test_small_samples_small_rises_and_rare_failures_do_not_warn(self):
        self.deploy("1.0", rage=4)
        self.deploy("1.1", rage=10, errors=4)  # 6 -> 15: a rise of 9; the new error happened 4 times
        self.deploy("1.2", rage=40, visits=10)  # worse, but 10 visits are too few
        self.assertEqual(self.check(), 0)

    def test_a_warning_that_did_not_go_out_is_tried_again(self):
        self.deploy("1.0", rage=4)
        self.deploy("1.1", rage=20)
        self.assertEqual(self.check(ok=False), 0)
        self.assertEqual(self.check(), 1)
        self.assertEqual(len(self.messages), 2)

    def test_portuguese_and_projects_without_a_webhook(self):
        setup_config(TERMOMETRO_LANGUAGE="pt-BR", TERMOMETRO_PROJECTS=json.dumps([
            {"name": "shop", "key": KEY, "origins": [ORIGIN], "webhook": "https://chat.example/y"},
            {"name": "blog", "key": "tk_blog"}]))
        self.deploy("1.0", rage=4)
        self.deploy("1.1", rage=20)
        self.assertEqual(self.check(), 1)
        self.assertEqual(self.messages[0][0], "https://chat.example/y")
        self.assertEqual(self.messages[0][1].splitlines()[:2], ["Termometro · shop 1.1 piorou em relação à 1.0", "• /cart: frustração 6 → 30 (40 visitas)"])


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
