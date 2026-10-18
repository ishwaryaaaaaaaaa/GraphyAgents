"""The web UI: the JSON API over the real agent, and the things a web server must refuse."""
import http.client
import itertools
import json
import re
import threading
from pathlib import Path

import pytest

import ui_server
from agent import store

_n = itertools.count()


@pytest.fixture(scope="module")
def server():
    srv = ui_server.make_server("127.0.0.1", 0)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield srv
    srv.shutdown()
    srv.server_close()


@pytest.fixture
def ui(server, monkeypatch):
    """A tiny client plus a fresh person name; the person's graph is wiped before and after."""
    monkeypatch.setenv("LLM_MODE", "off")
    user = f"ui{next(_n)}"
    store.reset(user)
    ui_server._sessions.pop(user, None)
    port = server.server_address[1]

    class Client:
        name = user

        def call(self, method, path, body=None, headers=None, raw=None, host=None):
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=60)
            h = dict(headers or {})
            data = raw
            if body is not None:
                data = json.dumps(body).encode()
                h.setdefault("Content-Type", "application/json")
            conn.putrequest(method, path, skip_host=True)
            conn.putheader("Host", host or f"127.0.0.1:{port}")
            for k, v in h.items():
                conn.putheader(k, v)
            conn.putheader("Content-Length", str(len(data or b"")))
            conn.endheaders(data)
            r = conn.getresponse()
            payload = r.read()
            conn.close()
            ctype = r.getheader("Content-Type", "")
            return r.status, (json.loads(payload) if "json" in ctype else payload), r

        def get(self, path, **kw):
            return self.call("GET", path, **kw)

        def say(self, text):
            status, body, _ = self.call("POST", "/api/say", {"user": user, "text": text})
            assert status == 200, body
            return body

    yield Client()
    store.reset(user)
    ui_server._sessions.pop(user, None)


def story(ui):
    ui.say("I eat meat again")
    ui.say("I love fried chicken")
    first = ui.say("fried chicken or chana chaat?")
    ui.say("/day 10")
    ui.say("I turned vegetarian")
    second = ui.say("fried chicken or chana chaat?")
    return first, second


# ---- the page and the happy path ---------------------------------------------------------------------

def test_page_is_served_with_a_locked_down_csp(ui):
    status, body, r = ui.get("/")
    assert status == 200 and b"<title>Decisive agent</title>" in body
    csp = r.getheader("Content-Security-Policy")
    assert "default-src 'none'" in csp and "connect-src 'self'" in csp
    assert "img-src data: https://images.unsplash.com;" in csp      # photos only from the one host the page uses
    assert r.getheader("X-Content-Type-Options") == "nosniff"


def test_page_belongs_to_whoever_opens_it():
    """No pre-loaded person: each browser tab makes its own random id, and the first screen explains the product."""
    page = (Path(ui_server.ROOT) / "ui" / "index.html").read_text(encoding="utf-8")
    assert "crypto.getRandomValues" in page and "sessionStorage" in page
    assert "localStorage" not in page                      # nothing carries over between visits or people
    assert 'value="demo"' not in page and "Meera" not in page
    assert "Start with a blank memory" in page and "My memory of you is empty" in page


def test_a_new_visitor_starts_with_an_empty_memory(ui):
    fresh = f"u_{next(_n):012x}"
    assert ui_server.USER_RE.fullmatch(fresh)              # the ids the page generates are accepted
    try:
        assert ui.get(f"/api/memory?user={fresh}&as_of=1")[1]["rows"] == []
        assert ui.get(f"/api/people?user={fresh}")[1]["contacts"] == []
        assert ui.get(f"/api/graph?user={fresh}")[1]["decisions"] == []
        assert ui.get(f"/api/state?user={fresh}")[1]["today"] == 1
    finally:
        store.reset(fresh)
        ui_server._sessions.pop(fresh, None)


def test_page_never_builds_html_from_strings():
    page = (Path(ui_server.ROOT) / "ui" / "index.html").read_text(encoding="utf-8")
    for banned in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval("):
        assert banned not in page, banned
    assert not re.search(r"<script[^>]+src=", page), "the page must load no outside scripts"
    outside = set(re.findall(r"https?://[^/\s\"')]+", page))
    assert outside <= {"https://images.unsplash.com", "http://www.w3.org"}, outside   # photos and the SVG namespace only


def test_health(ui):
    assert ui.get("/api/health")[:2] == (200, {"ok": True})


def test_chat_story_flips_the_answer_and_names_the_decision(ui):
    first, second = story(ui)
    assert first["reply"].startswith("fried chicken.") and first["focus"]
    assert second["reply"].startswith("chana chaat.") and second["focus"] != first["focus"]
    assert second["today"] == 10
    assert ui.say("what?")["focus"] is None            # not a decision, nothing to highlight


def test_memory_panel_supports_time_travel(ui):
    story(ui)
    status, m, _ = ui.get(f"/api/memory?user={ui.name}&as_of=5")
    assert status == 200 and m["today"] == 10
    diet = next(r for r in m["rows"] if r["key"] == "diet_style")
    assert diet["as_of"] == "non_veg" and diet["now"] == "vegetarian"
    assert [h["status"] for h in diet["history"]] == ["superseded", "active"]
    later = ui.get(f"/api/memory?user={ui.name}&as_of=10")[1]
    assert next(r for r in later["rows"] if r["key"] == "diet_style")["as_of"] == "vegetarian"


def test_retracted_facts_leave_the_now_column_but_stay_in_history(ui):
    ui.say("I hate paneer wrap")
    ui.say("that was wrong about paneer wrap")
    rows = ui.get(f"/api/memory?user={ui.name}&as_of=1")[1]["rows"]
    liked = [r for r in rows if "paneer_wrap" in r["key"]]
    assert liked and all(r["now"] is None for r in liked)      # the retracted claim is no longer true now
    assert any(h["status"] != "active" for r in liked for h in r["history"])  # but history is kept


def test_graph_has_the_supersede_edge_and_the_facts_a_decision_used(ui):
    first, second = story(ui)
    g = ui.get(f"/api/graph?user={ui.name}")[1]
    by_id = {f["id"]: f for f in g["facts"]}
    assert any(by_id[a]["key"] == "diet_style" and by_id[b]["key"] == "diet_style"
               and by_id[a]["value"] == "non_veg" and by_id[b]["value"] == "vegetarian"
               for a, b in g["superseded"])
    dec = {d["id"]: d for d in g["decisions"]}
    used = [by_id[i] for i in dec[second["focus"]]["used"]]
    assert any(f["key"] == "diet_style" and f["value"] == "vegetarian" and f["status"] == "active" for f in used)
    old = [by_id[i] for i in dec[first["focus"]]["used"]]
    assert any(f["value"] == "non_veg" for f in old)          # the older answer rested on the older fact


def test_why_returns_the_audit_trail(ui):
    _, second = story(ui)
    status, a, _ = ui.get(f"/api/why?user={ui.name}&decision={second['focus']}")
    assert status == 200 and a["pick"] == "chana_chaat" and a["path_length"] == 1
    diet = next(u for u in a["used"] if u["key"] == "diet_style")
    assert [h["value"] for h in diet["history"]] == ["non_veg", "vegetarian"]
    assert isinstance(a["options"], list)


def test_why_unknown_decision_is_404(ui):
    assert ui.get(f"/api/why?user={ui.name}&decision=d999")[0] == 404


def test_people_tab(ui):
    ui.say("my friend Priya cancelled again, should I say something?")
    ui.say("I want to be someone who shows up")
    p = ui.get(f"/api/people?user={ui.name}")[1]
    priya = next(c for c in p["contacts"] if c["name"].lower() == "priya")
    assert priya["relation"] and priya["recent"] and "centrality" in priya
    assert p["values"], "the stated value should appear"


def test_state_and_next_day(ui):
    assert ui.get(f"/api/state?user={ui.name}")[1]["today"] == 1
    assert ui.say("/next")["today"] == 2
    assert ui.get(f"/api/state?user={ui.name}")[1]["today"] == 2


def test_session_resumes_the_day_after_a_server_restart(ui):
    story(ui)
    ui_server._sessions.pop(ui.name)                  # as if the server had restarted
    assert ui.get(f"/api/state?user={ui.name}")[1]["today"] == 10


def test_people_are_kept_apart(ui):
    other = ui.name + "b"
    store.reset(other)
    try:
        ui.say("I eat meat again")
        ui.call("POST", "/api/say", {"user": other, "text": "I turned vegetarian"})
        mine = ui.get(f"/api/memory?user={ui.name}&as_of=10")[1]["rows"]
        theirs = ui.get(f"/api/memory?user={other}&as_of=10")[1]["rows"]
        assert next(r for r in mine if r["key"] == "diet_style")["now"] == "non_veg"
        assert next(r for r in theirs if r["key"] == "diet_style")["now"] == "vegetarian"
    finally:
        store.reset(other)
        ui_server._sessions.pop(other, None)


def test_reset_needs_confirmation_then_wipes(ui):
    ui.say("I eat meat again")
    assert ui.call("POST", "/api/reset", {"user": ui.name})[0] == 400
    assert ui.call("POST", "/api/reset", {"user": ui.name, "confirm": "yes"})[0] == 400
    assert ui.get(f"/api/memory?user={ui.name}&as_of=1")[1]["rows"]            # still there
    assert ui.call("POST", "/api/reset", {"user": ui.name, "confirm": True})[0] == 200
    assert ui.get(f"/api/memory?user={ui.name}&as_of=1")[1]["rows"] == []
    assert ui.say("I turned vegetarian")["today"] == 1                          # a fresh session


# ---- what a web server must refuse ----------------------------------------------------------------------

@pytest.mark.parametrize("name", ["", "a b", "../x", "x;y", "a" * 31, "naïve", "%00", "a'b"])
def test_bad_person_names_are_rejected(ui, name):
    from urllib.parse import quote
    assert ui.get("/api/state?user=" + quote(name))[0] == 400
    assert ui.call("POST", "/api/say", {"user": name, "text": "hi"})[0] == 400


def test_bad_requests(ui):
    assert ui.call("POST", "/api/say", raw=b"{not json", headers={"Content-Type": "application/json"})[0] == 400
    assert ui.call("POST", "/api/say", raw=b"[1]", headers={"Content-Type": "application/json"})[0] == 400
    assert ui.call("POST", "/api/say", raw=b'{"user":"x","text":"hi"}',
                   headers={"Content-Type": "text/plain"})[0] == 400                    # no cross-site form posts
    assert ui.call("POST", "/api/say", {"user": ui.name, "text": 5})[0] == 400
    assert ui.call("POST", "/api/say", {"user": ui.name, "text": "x" * (ui_server.MAX_TEXT + 1)})[0] == 400
    assert ui.call("POST", "/api/say", {"user": ui.name, "text": "   "})[0] == 400
    assert ui.get(f"/api/why?user={ui.name}&decision=../etc")[0] == 400
    assert ui.get(f"/api/memory?user={ui.name}&as_of=abc")[0] == 400


def test_oversized_body_is_refused_without_reading_it(ui):
    big = b'{"user":"x","text":"' + b"a" * (ui_server.MAX_BODY + 10) + b'"}'
    assert ui.call("POST", "/api/say", raw=big, headers={"Content-Type": "application/json"})[0] == 413


@pytest.mark.parametrize("path", ["/etc/passwd", "/../ui_server.py", "/ui/index.html", "/..%2fui_server.py",
                                  "/api", "/api/nope", "/%2e%2e/%2e%2e/windows/win.ini"])
def test_only_the_fixed_routes_exist(ui, path):
    status, body, _ = ui.get(path)
    assert status == 404
    assert b"import " not in (body if isinstance(body, bytes) else json.dumps(body).encode())


def test_wrong_methods(ui):
    for m in ("PUT", "DELETE", "PATCH"):
        assert ui.call(m, "/api/say")[0] == 405
    assert ui.call("POST", "/")[0] == 404


@pytest.mark.parametrize("host", ["evil.example", "evil.example:8765", "127.0.0.1.evil.example"])
def test_foreign_host_header_is_refused(ui, host):
    """DNS rebinding: a hostile page resolving its own name to 127.0.0.1 must not reach the agent."""
    assert ui.get("/", host=host)[0] == 403
    assert ui.get("/api/health", host=host)[0] == 403
    assert ui.call("POST", "/api/say", {"user": ui.name, "text": "hi"}, host=host)[0] == 403


def test_localhost_name_is_fine(ui):
    assert ui.get("/api/health", host="localhost:1234")[0] == 200


def test_a_full_server_refuses_new_people_but_keeps_serving_existing_ones(ui, monkeypatch):
    ui.say("I eat meat again")                                  # this person now has a session
    monkeypatch.setattr(ui_server, "MAX_SESSIONS", len(ui_server._sessions))
    newcomer = ui.name + "z"
    assert ui.get(f"/api/state?user={newcomer}")[0] == 503
    assert ui.get(f"/api/state?user={ui.name}")[0] == 200
    store.reset(newcomer)


def test_server_errors_do_not_leak_tracebacks(ui, monkeypatch):
    def boom(user):
        raise RuntimeError("secret internals /home/x")
    monkeypatch.setattr(ui_server, "people", boom)
    status, body, _ = ui.get(f"/api/people?user={ui.name}")
    assert status == 500 and "secret" not in json.dumps(body) and "Traceback" not in json.dumps(body)


def test_binds_to_loopback_by_default():
    import inspect
    assert inspect.signature(ui_server.make_server).parameters["host"].default == "127.0.0.1"


def test_ui_code_does_not_read_facts_around_the_guard():
    """The UI may only use the guarded reads and the labelled inspection helpers."""
    src = (Path(ui_server.ROOT) / "ui_server.py").read_text(encoding="utf-8")
    assert ":Fact" not in src and "query(" not in src
