"""Seeds a fresh database for the panel test: one project, a few days of synthetic but realistic events.
Run with the same env as the server (TERMOMETRO_DB, TERMOMETRO_PROJECTS); uses the server's own code."""
import os, random, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "server"))
import termometro as t

t.CONFIG = t.Config(os.environ)
random.seed(7)
PROJECT, KEY = "demo", "tk"
NOW = time.time()
# route: (screen name, [(selector, label, action or None)])
APP = {
    "/": ("Home", [("a#menu-tickets", "Tickets", None), ("a#menu-users", "Users", None)]),
    "/tickets": ("Tickets", [("button#new", "New ticket", None), ("button#export", "Export", "POST /api/tickets/export")]),
    "/users": ("Users", [("button#invite", "Invite", "POST /api/invites"), ("span.icon", "", None)]),
}
# the drawing of /tickets: boxes follow the inventory's targets, in order
LAYOUT = {"vw": 1280, "vh": 800, "dw": 1280, "dh": 800, "boxes": [[1060, 24, 120, 36], [920, 24, 120, 36]],
          "styles": [["#ffffff", "#d9480f", "#d9480f", 6, 14], ["#ffffff", "#333333", "#cccccc", 6, 14]],
          "landmarks": [{"kind": "header", "box": [0, 0, 1280, 84]}, {"kind": "aside", "box": [0, 84, 220, 716]},
                        {"kind": "main", "box": [220, 84, 1060, 716]}],
          "look": {"page": "#f6f4f0", "blocks": [{"box": [240, 110, 1020, 300], "bg": "#ffffff", "bd": "#dddddd", "r": 8}],
                   "texts": [[260, 130, 300, 18, "#222222"], [260, 160, 500, 14, "#666666"]]}}


def session(version, n):
    ev = []
    for route in random.sample(list(APP), k=random.randint(2, 3)):
        name, controls = APP[route]
        ev += [{"type": "page", "route": route, "label": name},
               {"type": "inventory", "route": route, "targets": [c[0] for c in controls], "labels": [c[1] for c in controls],
                **({"layout": LAYOUT} if route == "/tickets" else {})}]
        for sel, label, action in controls:
            ev.append({"type": "click", "route": route, "target": sel, "label": label})
            if sel == "span.icon":
                ev.append({"type": "rage", "route": route, "target": sel, "label": label, "detail": "not_clickable"})
            elif sel == "button#invite" and version == "1.1":
                ev += [{"type": "slow", "route": route, "target": sel, "detail": action, "duration_ms": 5200},
                       {"type": "rage", "route": route, "target": sel, "label": label, "detail": "waiting"}]
                if n % 3 == 0:
                    ev.append({"type": "http_5xx", "route": route, "target": sel, "detail": action + " 500"})
            elif action:
                ev.append({"type": "action", "route": route, "detail": action, "label": label, "clicks": 3, "here": 1,
                           "duration_ms": random.randint(4000, 30000)})
    return ev


rows, elements, layouts = [], [], []
n = 0
for day in range(9, -1, -1):
    version = "1.0" if day > 4 else "1.1"
    for s in range(6):
        n += 1
        u = n % 6
        batch = {"key": KEY, "version": version, "session": f"d{day}s{s}", "user": f"u{u}", "account": ["4821", "7001"][u % 2],
                 "role": ["agent", "manager"][u % 2], "events": session(version, n)}
        _, rs, el = t.parse_batch(batch, "http://x", "", layouts)
        base = NOW - day * 86400 - 3600 * (s + 1)
        rows += [r[:12] + (int((base + i * 4) * 1000),) + r[13:] for i, r in enumerate(rs)]
        elements += el
with t.connect() as con:
    con.executemany(t.INSERT_EVENT, rows)
    con.executemany("INSERT INTO elements (project, route, target, last_seen, label, first_seen) VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT DO NOTHING",
                    [e + (int((NOW - 9 * 86400) * 1000),) for e in elements])
    t.save_layouts(con, layouts)
    t.save_feature(con, PROJECT, {"name": "Export tickets", "rules": [{"kind": "action", "key": "POST /api/tickets/export"}]})
    con.executemany("INSERT OR REPLACE INTO people (project, user_id, name, last_seen) VALUES (?, ?, ?, ?)",
                    [(PROJECT, f"u{u}", f"Person {u}", int(NOW * 1000)) for u in range(6)])
    con.commit()
print(len(rows), "events,", len(layouts), "layouts")
