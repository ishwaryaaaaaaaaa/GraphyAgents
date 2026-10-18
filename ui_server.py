"""A small local web UI for the agent: chat, live memory with a day slider, a graph view that
highlights the path behind an answer, and a people tab.

    python ui_server.py                 # then open http://127.0.0.1:8765

Standard library only, one page (ui/index.html). It is a thin skin over the code that already exists:
the chat is `cli.Session`, the memory panel is the guarded reads in agent/tools.py, and the graph view
uses two read-only inspection helpers. It never writes to the graph except through the agent itself.

Safety, since it is a web server: it binds to 127.0.0.1 by default; it serves exactly one HTML file and
a fixed set of JSON routes (no file paths from the request); person names are validated; request bodies
are capped; POSTs must be JSON; and with a loopback bind the Host header must be the loopback address
(which blocks DNS-rebinding). The page renders every string with textContent, never as HTML.
"""
import argparse
import json
import os
import re
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import cli
from agent import store, tools

ROOT = Path(__file__).resolve().parent
PAGE = ROOT / "ui" / "index.html"
USER_RE = re.compile(r"[A-Za-z0-9_]{1,30}")
MAX_BODY = 10_000
MAX_TEXT = 500
MAX_SESSIONS = int(os.environ.get("UI_MAX_SESSIONS", "2000"))   # distinct people one server will hold
LOOPBACK = ("127.0.0.1", "localhost", "::1")

_sessions, _locks, _guard = {}, {}, threading.Lock()


class BadRequest(Exception):
    """The caller sent something we will not act on (HTTP 400)."""


class Busy(Exception):
    """This server already holds as many people as it is allowed to (HTTP 503)."""


# ---- sessions ---------------------------------------------------------------------------------

def _user_lock(user):
    with _guard:
        return _locks.setdefault(user, threading.RLock())


def _infer_day(user):
    """Resume a person's simulated day from what is already in their graph."""
    days = [r["valid_from"] for r in store.raw_facts(user)]
    days += [d["day"] for d in tools.recent_decisions(user, 200)]
    return max(days + [1])


def _session(user):
    with _user_lock(user):
        if user not in _sessions:
            if len(_sessions) >= MAX_SESSIONS:
                raise Busy("this server is full, try again later")
            _sessions[user] = cli.Session(user, day=_infer_day(user), auto=True)
        return _sessions[user]


def _today(user):
    return _session(user).day


# ---- what the page asks for ---------------------------------------------------------------------

def state(user):
    s = _session(user)
    ranks = tools.rank_goals(user)
    return {
        "user": user, "today": s.day, "pending_answer": bool(s.pending),
        "goals": [{"tag": g["tag"], "since": g["since"], "rank": round(ranks.get(g["tag"], 0), 3)}
                  for g in tools.get_active_goals(user)],
        "weights": tools.get_weights(user),
        "unrated": len(tools.pending_outcomes(user, s.day + 1)),
    }


def memory(user, as_of):
    """One row per memory slot: its value on `as_of` (time travel), its value now, and its history."""
    today = _today(user)
    now = tools.get_facts(user, today)                     # the guard: only what is true now
    raw = store.raw_facts(user)
    derived_ids = {child for child, _ in store.raw_edges(user)["derived"]}
    by_key = {}
    for r in raw:
        by_key.setdefault(r["key"], []).append(r)
    rows = []
    for key, hist in by_key.items():
        rows.append({
            "key": key,
            "as_of": tools.get_fact_at(user, key, as_of),
            "now": now[key][0] if key in now else None,
            "derived": any(h["id"] in derived_ids for h in hist),
            "order": hist[0]["seq"],
            "history": [{k: h[k] for k in ("id", "value", "status", "valid_from", "valid_to")}
                        for h in hist],
        })
    rows.sort(key=lambda r: r["order"])
    return {"today": today, "as_of": as_of, "rows": rows}


def graph(user):
    raw = store.raw_facts(user)
    edges = store.raw_edges(user)
    return {
        "facts": [{k: r[k] for k in ("id", "key", "value", "status", "valid_from", "valid_to", "seq")}
                  for r in raw],
        "superseded": edges["superseded"], "derived": edges["derived"],
        "decisions": tools.recent_decisions(user, 40), "today": _today(user),
    }


def people(user):
    today = _today(user)
    ranks = tools.rank_contacts(user)
    out = []
    for c in tools.list_contacts(user):
        status = tools.get_fact_meta(user, f"contact:{c['id']}:status", today)
        city = tools.get_fact_meta(user, f"contact:{c['id']}:city", today)
        out.append({
            **c, "status": status["value"] if status else None,
            "source": status["source"] if status else None,
            "city": city["value"] if city else None,
            "recent": tools.contact_timeline(user, c["id"], 5, today),
            "promises": tools.open_promises_to(user, c["id"], today),
            "centrality": round(ranks.get(c["id"], 0), 3),
        })
    return {"today": today, "contacts": out, "values": tools.values(user)}


def why(user, decision_id):
    audit = tools.explain_decision(user, decision_id)
    if audit is None:
        raise LookupError(decision_id)
    if isinstance(audit.get("options"), str):
        audit["options"] = json.loads(audit["options"] or "[]")
    return audit


def say(user, text):
    """Give the agent one line, exactly as the command-line chat would."""
    if not text.strip():
        raise BadRequest("say something first")
    if text.strip().lower().startswith("/user"):
        return {"reply": "Switch person with the name box at the top of the page.",
                "today": _today(user), "focus": None, "pending_answer": False}
    with _user_lock(user):
        s = _session(user)
        before = (s.last_decision or {}).get("decision_id")
        reply = s.handle(text)
        after = (s.last_decision or {}).get("decision_id")
        return {"reply": reply, "today": s.day, "focus": after if after != before else None,
                "pending_answer": bool(s.pending)}


def reset(user):
    with _user_lock(user):
        store.reset(user)
        _sessions.pop(user, None)
    return {"ok": True}


# ---- HTTP ----------------------------------------------------------------------------------------

def _int(params, name, default, low=0, high=10_000):
    raw = params.get(name, [str(default)])[0]
    if not re.fullmatch(r"-?\d{1,6}", raw):
        raise BadRequest(f"{name} must be a whole number")
    return max(low, min(high, int(raw)))


def _user(value):
    if not value or not USER_RE.fullmatch(value):
        raise BadRequest("person must be 1-30 letters, digits or underscores")
    return value


class Handler(BaseHTTPRequestHandler):
    server_version = "DecisiveUI"
    sys_version = ""
    quiet = True

    def log_message(self, format, *args):  # noqa: A002 - name fixed by the base class
        if not self.quiet:
            sys.stderr.write("ui: " + format % args + "\n")

    # -- plumbing --
    def _send(self, code, body, ctype="application/json; charset=utf-8", extra=None):
        data = body if isinstance(body, bytes) else json.dumps(body, default=str).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def _host_ok(self):
        """With a loopback bind, only accept the loopback Host header (blocks DNS rebinding)."""
        if getattr(self.server, "bind_host", "127.0.0.1") not in LOOPBACK:
            return True
        host = (self.headers.get("Host") or "").rsplit(":", 1)[0].strip("[]")
        return host in LOOPBACK

    def _read_raw(self):
        """Take the request body off the socket before answering, so an early refusal does not reset the
        client's connection. Reads at most MAX_BODY+1 bytes and discards a little more; anything larger is
        simply cut off."""
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = -1
        self._length = length
        self._raw = b""
        if length > 0:
            self._raw = self.rfile.read(min(length, MAX_BODY + 1))
            extra = min(length - len(self._raw), 65536)
            if extra > 0:
                self.rfile.read(extra)

    def _body(self):
        if "application/json" not in (self.headers.get("Content-Type") or ""):
            raise BadRequest("send JSON (Content-Type: application/json)")
        if self._length < 0:
            raise BadRequest("bad Content-Length")
        if self._length > MAX_BODY:
            raise OverflowError("request too large")
        try:
            data = json.loads(self._raw or b"{}")
        except ValueError:
            raise BadRequest("body is not valid JSON") from None
        if not isinstance(data, dict):
            raise BadRequest("body must be a JSON object")
        return data

    def _run(self, fn):
        try:
            self._send(200, fn())
        except BadRequest as e:
            self._send(400, {"error": str(e)})
        except OverflowError as e:
            self._send(413, {"error": str(e)})
        except Busy as e:
            self._send(503, {"error": str(e)})
        except LookupError as e:
            self._send(404, {"error": f"not found: {e}"})
        except Exception as e:  # noqa: BLE001 - never leak a traceback to the page
            sys.stderr.write(f"ui: {self.command} {self.path} failed: {type(e).__name__}: {e}\n")
            self._send(500, {"error": f"server error ({type(e).__name__})"})

    # -- routes --
    def do_GET(self):
        if not self._host_ok():
            return self._send(403, {"error": "bad Host header"})
        url = urlparse(self.path)
        q = parse_qs(url.query)
        if url.path in ("/", "/index.html"):
            csp = ("default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
                   "connect-src 'self'; img-src data: https://images.unsplash.com; base-uri 'none'; form-action 'none'")
            return self._send(200, PAGE.read_bytes(), "text/html; charset=utf-8",
                              {"Content-Security-Policy": csp})
        routes = {
            "/api/health": lambda: {"ok": True},
            "/api/state": lambda: state(_user(q.get("user", [""])[0])),
            "/api/memory": lambda: memory(_user(q.get("user", [""])[0]), _int(q, "as_of", 10_000)),
            "/api/graph": lambda: graph(_user(q.get("user", [""])[0])),
            "/api/people": lambda: people(_user(q.get("user", [""])[0])),
            "/api/why": lambda: why(_user(q.get("user", [""])[0]),
                                    _decision(q.get("decision", [""])[0])),
        }
        if url.path in routes:
            return self._run(routes[url.path])
        self._send(404, {"error": "not found"})

    do_HEAD = do_GET

    def do_POST(self):
        self._read_raw()
        if not self._host_ok():
            return self._send(403, {"error": "bad Host header"})
        path = urlparse(self.path).path
        if path == "/api/say":
            return self._run(self._post_say)
        if path == "/api/reset":
            return self._run(self._post_reset)
        self._send(404, {"error": "not found"})

    def _post_say(self):
        body = self._body()
        text = body.get("text")
        if not isinstance(text, str) or len(text) > MAX_TEXT:
            raise BadRequest(f"text must be a string of at most {MAX_TEXT} characters")
        return say(_user(body.get("user")), text)

    def _post_reset(self):
        body = self._body()
        if body.get("confirm") is not True:
            raise BadRequest("send {\"confirm\": true} to wipe this person's memory")
        return reset(_user(body.get("user")))

    def _method_not_allowed(self):
        self._send(405, {"error": "method not allowed"}, extra={"Allow": "GET, POST"})

    do_PUT = do_DELETE = do_PATCH = _method_not_allowed


def _decision(value):
    if not re.fullmatch(r"d\d{1,8}", value or ""):
        raise BadRequest("decision must look like d12")
    return value


def make_server(host="127.0.0.1", port=8765):
    server = ThreadingHTTPServer((host, port), Handler)
    server.bind_host = host
    return server


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--host", default="127.0.0.1", help="bind address (keep it loopback unless you must)")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--verbose", action="store_true", help="log every request")
    args = ap.parse_args(argv)
    Handler.quiet = not args.verbose
    server = make_server(args.host, args.port)
    print(f"Decisive agent UI: http://{args.host}:{server.server_address[1]}  (Ctrl+C to stop)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print()
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
