"""Track 2 stress test: many people at once, many agents on one person, many processes on one slot.

  1. People in parallel   N generated lives replayed at once, each in its own graph (one graph per
                          person). Every graph carries an `owner` marker that is checked at each
                          question; a life must give the SAME answers as when replayed alone, agree
                          with the oracle, use no stale fact, and never see another person's data.
  2. Agents on one person  several threads write to the SAME graph. Ids stay unique, a contested slot
                          ends with exactly one active fact in a linear history, and a two-step
                          update (lives_in then mess_meals_available) stays consistent when the
                          caller holds store.user_lock. Each check is also run with its safeguard
                          switched off, to show what it prevents.
  3. Processes on one slot separate OS processes (like two MCP servers) write one slot at once. The
                          in-process lock cannot help here; store.settle() repairs the graph.

Throughput is measured on the real server: queries per second and latency percentiles for reads
and writes, with and without parallelism.
"""
import multiprocessing
import random
import re
import threading
import time
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor

from falkordb.graph import Graph

from agent import store, tools
from agent.db import get_graph
from data import generator
from eval import replay

_WRITE = re.compile(r"\b(CREATE|SET|MERGE|DELETE)\b")


class Meter:
    """Counts and times every graph query while installed."""

    def __init__(self):
        self.reads, self.writes = [], []

    def __enter__(self):
        original = self._original = Graph.query

        def timed(graph, q, *args, **kwargs):
            start = time.perf_counter()
            try:
                return original(graph, q, *args, **kwargs)
            finally:
                (self.writes if _WRITE.search(q) else self.reads).append(time.perf_counter() - start)

        Graph.query = timed
        return self

    def __exit__(self, *exc):
        Graph.query = self._original

    @staticmethod
    def pct(xs, p):
        return round(1000 * sorted(xs)[min(len(xs) - 1, int(len(xs) * p))], 2) if xs else None

    def summary(self, seconds):
        total = len(self.reads) + len(self.writes)
        return {"queries": total, "queries_per_second": round(total / seconds),
                "reads": len(self.reads), "writes": len(self.writes),
                "read_ms": {p: self.pct(self.reads, v) for p, v in (("p50", .5), ("p95", .95), ("p99", .99))},
                "write_ms": {p: self.pct(self.writes, v) for p, v in (("p50", .5), ("p95", .95), ("p99", .99))}}


# ---- 1. people in parallel ----------------------------------------------------------------------

def _one_life(seed):
    life = generator.generate(seed)
    user = f"conc{seed}"
    owner = {"op": "set", "day": 0, "key": "owner", "value": user, "derived_from": [],
             "expect_dropped": None}
    leaks = []

    def watch(u, step, options):  # runs just before every answer, inside the worker
        mine = tools.get_facts(u, step["day"]).get("owner", (None,))[0]
        if mine != user:
            leaks.append(f"{step['id']}: owner marker is {mine!r}")

    try:
        run = replay.replay(user, [owner] + life["steps"], observer=watch)
        g = get_graph(user)
        people = [r[0] for r in g.query("MATCH (p:Person) RETURN p.id").result_set]
        owners = [r["value"] for r in store.raw_facts(user) if r["key"] == "owner"]
        if people != [user]:
            leaks.append(f"graph holds people {people}")
        if owners != [user]:
            leaks.append(f"graph holds owner markers {owners}")
    finally:
        store.reset(user)
    signature = [(a["id"], a["arms"]["guarded"]["pick"], a["arms"]["guarded"]["stale_use"],
                  a["arms"]["guarded"]["ok"]) for a in run["asks"]]
    signature += [(t["id"], t["got"], t["ok"]) for t in run["time_travel"]]
    return {"seed": seed, "leaks": leaks, "signature": signature, "asks": run["asks"],
            "cascade_ok": all(c["ok"] for c in run["cascade"]), "steps": len(life["steps"])}


def run_lives(seeds, workers):
    start = time.perf_counter()
    with Meter() as meter:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            results = list(pool.map(_one_life, seeds))
    seconds = time.perf_counter() - start
    asks = [a for r in results for a in r["asks"]]
    return {
        "workers": workers, "lives": len(results), "seconds": round(seconds, 1),
        "operations": sum(r["steps"] for r in results),
        "operations_per_second": round(sum(r["steps"] for r in results) / seconds),
        "questions": len(asks),
        "oracle_disagreements": sum(not a["arms"]["guarded"]["ok"] for a in asks),
        "stale_uses": sum(a["arms"]["guarded"]["stale_use"] for a in asks),
        "leaks": [x for r in results for x in r["leaks"]],
        "cascades_wrong": sum(not r["cascade_ok"] for r in results),
        "signatures": {r["seed"]: r["signature"] for r in results},
        "throughput": meter.summary(seconds),
    }


# ---- 2. agents on one person ---------------------------------------------------------------------

def _threads(n, fn):
    barrier = threading.Barrier(n)
    errors = []

    def run(i):
        barrier.wait()  # start together
        try:
            fn(i)
        except Exception as e:  # noqa: BLE001 - a crash is a finding, not a reason to stop
            errors.append(repr(e))

    threads = [threading.Thread(target=run, args=(i,)) for i in range(n)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    return errors


def slot_report(user, key):
    """Structure of one slot's history: how many active, edges, degrees, anything unreachable."""
    return store.raw_slot_report(user, key)


def contention_ids(agents=8, per_agent=40, locking=True):
    user = "conc_ids"
    store.reset(user)
    store.ensure_user(user)
    old = store.LOCKING
    store.LOCKING = locking
    try:
        errors = _threads(agents, lambda i: [store.log_event(user, "clean_day", "x", "sugar", 1)
                                             for _ in range(per_agent)])
    finally:
        store.LOCKING = old
    ids = [r[0] for r in get_graph(user).query("MATCH (e:Event) RETURN e.id").result_set]
    store.reset(user)
    return {"expected": agents * per_agent, "events": len(ids), "unique_ids": len(set(ids)),
            "errors": len(errors)}


def contention_slot(agents=8, per_agent=25, locking=True, settle=True):
    user = "conc_slot"
    store.reset(user)
    store.ensure_user(user)
    old = (store.LOCKING, store.SETTLE)
    store.LOCKING, store.SETTLE = locking, settle
    try:
        errors = _threads(agents, lambda i: [store.set_fact(user, "contested", f"a{i}-{j}", 1)
                                             for j in range(per_agent)])
    finally:
        store.LOCKING, store.SETTLE = old
    rep = slot_report(user, "contested")
    store.reset(user)
    rep.update(expected_facts=agents * per_agent, errors=len(errors))
    rep["consistent"] = (rep["active"] == 1 and rep["unreachable"] == 0 and rep["max_out"] <= 1
                         and rep["max_in"] <= 1 and rep["facts"] == rep["expected_facts"])
    return rep


def contention_compound(agents=8, rounds=40, hold_lock=True):
    """Two-step update: set lives_in, then (if hostel) the derived mess_meals_available. Another
    agent can move the person out in between unless the caller holds store.user_lock."""
    user = "conc_compound"
    store.reset(user)
    store.ensure_user(user)

    def agent(i):
        rng = random.Random(i)
        for _ in range(rounds):
            home = rng.choice(["hostel", "flat", "home"])
            with (store.user_lock(user) if hold_lock else _null()):
                store.set_fact(user, "lives_in", home, 1)
                if home == "hostel":
                    try:
                        store.set_fact(user, "mess_meals_available", "yes", 1,
                                       derived_from=["lives_in"])
                    except ValueError:
                        pass

    errors = _threads(agents, agent)
    active = {r["key"]: r["value"] for r in store.raw_facts(user) if r["status"] == "active"}
    mess = store.raw_parent_status(user, "mess_meals_available")   # (parent id, parent status)
    store.reset(user)
    # consistent: no active mess unless the person lives in the hostel AND it hangs off that fact
    bad = "mess_meals_available" in active and (active.get("lives_in") != "hostel"
                                                or not mess or mess[1] != "active")
    return {"final_home": active.get("lives_in"), "mess_active": "mess_meals_available" in active,
            "violation": bad, "errors": len(errors)}


class _null:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def compound_trials(hold_lock, trials=6, **kw):
    """The compound race is probabilistic: run it several times and count violations."""
    return {"trials": trials, "violations": sum(contention_compound(hold_lock=hold_lock, **kw)["violation"]
                                                for _ in range(trials))}


# ---- 3. processes on one slot ---------------------------------------------------------------------

def _proc_worker(args):
    user, idx, n, settle = args
    from agent import store as s
    s.SETTLE = settle
    for i in range(n):
        s.set_fact(user, "contested", f"p{idx}-{i}", 1)
    return n


def contention_processes(procs=4, per_proc=30, settle=True):
    user = "conc_proc"
    store.reset(user)
    store.ensure_user(user)
    # "spawn", not the Linux default "fork": a forked child inherits the parent's open database
    # sockets and deadlocks. Each spawned worker starts clean and opens its own connection.
    with ProcessPoolExecutor(max_workers=procs, mp_context=multiprocessing.get_context("spawn")) as pool:
        list(pool.map(_proc_worker, [(user, i, per_proc, settle) for i in range(procs)]))
    rep = slot_report(user, "contested")
    store.reset(user)
    rep["consistent"] = rep["active"] == 1 and rep["unreachable"] == 0
    return rep


# ---- everything -------------------------------------------------------------------------------------

def engine_info():
    """Which FalkorDB produced the numbers: a throughput figure means little without it."""
    from agent.db import get_client
    conn = get_client().connection
    mods = {(m[1].decode() if isinstance(m[1], bytes) else m[1]): m[3]
            for m in conn.execute_command("MODULE", "LIST")}
    return {"redis": conn.info("server").get("redis_version"), "graph_module": mods.get("graph"),
            "os": conn.info("server").get("os")}


def run(seeds=range(300, 348), workers=16):
    alone = run_lives(seeds, workers=1)
    together = run_lives(seeds, workers=workers)
    same = sum(alone["signatures"][s] == together["signatures"][s] for s in seeds)
    return {
        "engine": engine_info(), "lives": len(seeds), "workers": workers,
        "alone": {k: v for k, v in alone.items() if k != "signatures"},
        "together": {k: v for k, v in together.items() if k != "signatures"},
        "same_answers_as_alone": same,
        "agents": {
            "ids_locked": contention_ids(locking=True), "ids_unlocked": contention_ids(locking=False),
            "slot_protected": contention_slot(locking=True, settle=True),
            "slot_unprotected": contention_slot(locking=False, settle=False),
            "compound_locked": compound_trials(True), "compound_unlocked": compound_trials(False),
        },
        "processes": {"settle_on": contention_processes(settle=True),
                      "settle_off": contention_processes(settle=False)},
    }


def to_markdown(r):
    a, t = r["alone"], r["together"]
    ag, pr = r["agents"], r["processes"]
    rd, wr = t["throughput"]["read_ms"], t["throughput"]["write_ms"]
    e = r["engine"]
    rows = [
        f"{r['lives']} generated lives, each in its own graph on one FalkorDB server (graph module "
        f"{e['graph_module']}, Redis {e['redis']}), replayed alone and then {r['workers']} at a time.", "",
        "**Many people at once**", "",
        "| Check | Result |", "|---|---|",
        f"| Same answers when run in parallel as when run alone | {r['same_answers_as_alone']} of {r['lives']} lives |",
        f"| Disagreements with the oracle (parallel run) | {t['oracle_disagreements']} of {t['questions']} questions |",
        f"| Stale facts used | {t['stale_uses']} |",
        f"| Cross-person leaks (owner marker and graph contents checked at every question) | {len(t['leaks'])} |",
        f"| Cascades dropped wrongly | {t['cascades_wrong']} |", "",
        "| Run | Wall time | Operations / s | Queries / s | Read latency p50 / p95 / p99 (ms) | Write latency p50 / p95 / p99 (ms) |",
        "|---|---|---|---|---|---|",
        f"| 1 worker | {a['seconds']} s | {a['operations_per_second']} | {a['throughput']['queries_per_second']} | "
        f"{a['throughput']['read_ms']['p50']} / {a['throughput']['read_ms']['p95']} / {a['throughput']['read_ms']['p99']} | "
        f"{a['throughput']['write_ms']['p50']} / {a['throughput']['write_ms']['p95']} / {a['throughput']['write_ms']['p99']} |",
        f"| {r['workers']} workers | {t['seconds']} s | {t['operations_per_second']} | {t['throughput']['queries_per_second']} | "
        f"{rd['p50']} / {rd['p95']} / {rd['p99']} | {wr['p50']} / {wr['p95']} / {wr['p99']} |",
        "", f"Speed-up from parallelism: {a['seconds'] / t['seconds']:.1f}x.", "",
        "**Many agents on one person** (8 threads, same graph)", "",
        "| Check | Safeguard on | Safeguard off |", "|---|---|---|",
        f"| Event ids unique ({ag['ids_locked']['expected']} written) | {ag['ids_locked']['unique_ids']} unique | {ag['ids_unlocked']['unique_ids']} unique |",
        f"| One contested slot: exactly one active fact, linear history, nothing lost | "
        f"{'consistent' if ag['slot_protected']['consistent'] else 'BROKEN'} "
        f"({ag['slot_protected']['active']} active of {ag['slot_protected']['facts']}) | "
        f"{'consistent' if ag['slot_unprotected']['consistent'] else 'broken'} "
        f"({ag['slot_unprotected']['active']} active of {ag['slot_unprotected']['facts']}) |",
        f"| Two-step update (lives_in then derived mess_meals_available) left consistent | "
        f"{ag['compound_locked']['trials'] - ag['compound_locked']['violations']} of {ag['compound_locked']['trials']} runs | "
        f"{ag['compound_unlocked']['trials'] - ag['compound_unlocked']['violations']} of {ag['compound_unlocked']['trials']} runs |", "",
        "**Many processes on one slot** (4 separate OS processes, like two MCP servers)", "",
        "| | settle on | settle off |", "|---|---|---|",
        f"| Active facts in the slot | {pr['settle_on']['active']} | {pr['settle_off']['active']} |",
        f"| Facts that cannot reach the active one | {pr['settle_on']['unreachable']} | {pr['settle_off']['unreachable']} |",
        f"| Consistent | {'yes' if pr['settle_on']['consistent'] else 'NO'} | {'yes' if pr['settle_off']['consistent'] else 'no'} |",
    ]
    return "\n".join(rows) + "\n"
