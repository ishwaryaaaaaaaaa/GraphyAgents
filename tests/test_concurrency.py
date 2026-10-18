"""Concurrency: the safeguards hold under parallel writers, and the stress-test harness itself is
sound. Sizes are small so this stays fast; `python run_eval.py --set concurrency` runs the big one."""
import threading

from agent import store
from agent.db import get_graph
from eval import concurrency as cc


def raw_two_active(user, key):
    """Create the damage a cross-process race leaves behind: two active facts for one slot."""
    store.ensure_user(user)
    g = get_graph(user)
    for seq, value in ((1, "old"), (2, "new")):
        g.query("MATCH (p:Person {id:$u}) CREATE (f:Fact {id:$id, key:$k, value:$v, status:'active', "
                "valid_from:1, seq:$s}) CREATE (p)-[:HAS_FACT]->(f)",
                {"u": user, "id": f"f{seq}", "k": key, "v": value, "s": seq})


# ---- the repair step ----

def test_settle_keeps_the_newest_fact_and_is_idempotent(user):
    raw_two_active(user, "k")
    assert store.settle(user, "k", 5) == 1
    rep = cc.slot_report(user, "k")
    assert rep["active"] == 1 and rep["edges"] == 1 and rep["unreachable"] == 0
    from agent import tools
    assert tools.get_fact(user, "k", 6)[0] == "new"          # the highest seq wins
    assert store.settle(user, "k", 5) == 0                    # nothing left to repair
    assert cc.slot_report(user, "k")["edges"] == 1            # and no duplicate edges


def test_settle_runs_the_cascade_of_what_it_supersedes(user):
    """A fact derived from the loser must not outlive it."""
    from agent import tools
    raw_two_active(user, "lives_in")                                   # f1 (old) and f2 (new)
    g = get_graph(user)
    g.query("MATCH (p:Person {id:$u}) CREATE (m:Fact {id:'f3', key:'mess', value:'yes', "
            "status:'active', valid_from:1, seq:3}) CREATE (p)-[:HAS_FACT]->(m)", {"u": user})
    g.query("MATCH (m:Fact {id:'f3'}), (o:Fact {id:'f1'}) CREATE (m)-[:DERIVED_FROM]->(o)")
    assert "mess" in tools.get_facts(user, 5)
    store.settle(user, "lives_in", 5)
    assert "mess" not in tools.get_facts(user, 5)                      # dropped with its parent
    assert tools.get_fact(user, "lives_in", 5)[0] == "new"


def test_a_normal_sequence_leaves_a_linear_history(user):
    for i in range(6):
        store.set_fact(user, "diet", f"v{i}", 1)
    rep = cc.slot_report(user, "diet")
    assert (rep["facts"], rep["active"], rep["edges"], rep["max_out"], rep["max_in"]) == (6, 1, 5, 1, 1)


# ---- agents on one person ----

def test_event_ids_stay_unique_under_parallel_writers():
    r = cc.contention_ids(agents=6, per_agent=15, locking=True)
    assert r["unique_ids"] == r["events"] == r["expected"] == 90 and r["errors"] == 0


def test_a_contested_slot_ends_with_one_active_fact_when_protected():
    r = cc.contention_slot(agents=6, per_agent=12, locking=True, settle=True)
    assert r["consistent"], r
    assert r["active"] == 1 and r["facts"] == 72 and r["max_out"] <= 1 and r["errors"] == 0


def test_the_unprotected_slot_really_breaks_so_the_test_has_teeth():
    r = cc.contention_slot(agents=8, per_agent=25, locking=False, settle=False)
    assert not r["consistent"] and r["active"] > 1, r


def test_holding_the_lock_across_a_two_step_update_keeps_it_consistent():
    t = cc.compound_trials(hold_lock=True, trials=3, rounds=20)
    assert t["violations"] == 0, t


def test_apply_ops_holds_the_lock_so_a_fact_and_its_derived_fact_land_together(user):
    """extract.apply_ops writes a fact and what hangs off it under one lock."""
    from agent import extract, tools
    base = {"confidence": 1.0, "days_ago": 0}
    barrier = threading.Barrier(6)

    def mover(i):
        barrier.wait()
        for j in range(15):
            home = ("hostel", "flat", "home")[(i + j) % 3]
            extract.apply_ops(user, [{**base, "op": "set_fact", "key": "lives_in", "value": home}], 1)

    threads = [threading.Thread(target=mover, args=(i,)) for i in range(6)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    facts = tools.get_facts(user, 1)
    # a hostel move creates mess_meals_available; any other move must have dropped it
    assert ("mess_meals_available" in facts) == (facts["lives_in"][0] == "hostel"), facts


# ---- processes on one slot ----

def test_separate_processes_converge_to_one_active_fact_with_settle_on():
    r = cc.contention_processes(procs=3, per_proc=12, settle=True)
    assert r["consistent"] and r["active"] == 1, r


# ---- many people at once ----

def test_people_in_parallel_get_the_same_answers_as_alone_with_no_leaks():
    seeds = range(300, 306)
    alone = cc.run_lives(seeds, workers=1)
    together = cc.run_lives(seeds, workers=4)
    assert together["signatures"] == alone["signatures"]
    assert together["leaks"] == [] and together["oracle_disagreements"] == 0
    assert together["stale_uses"] == 0 and together["cascades_wrong"] == 0
    assert together["throughput"]["queries"] > 0 and together["throughput"]["queries_per_second"] > 0


def test_the_leak_detector_actually_fires():
    """Plant another person's marker in a graph and the per-question check must notice it."""
    from agent import tools
    user = "leak_probe"
    store.reset(user)
    try:
        store.set_fact(user, "owner", "someone_else", 0)
        assert tools.get_facts(user, 1)["owner"][0] != user          # the condition _one_life flags
    finally:
        store.reset(user)


def test_meter_separates_reads_from_writes(user):
    from agent import tools
    with cc.Meter() as m:
        store.set_fact(user, "k", "v", 1)
        tools.get_facts(user, 1)
    assert len(m.writes) >= 1 and len(m.reads) >= 1
    s = m.summary(1.0)
    assert s["queries"] == len(m.reads) + len(m.writes) and s["read_ms"]["p50"] is not None


def test_markdown_report_mentions_the_engine_and_every_check():
    fake_run = {"alone": {"seconds": 10.0, "operations_per_second": 5, "throughput": {
        "queries_per_second": 50, "read_ms": {"p50": 1, "p95": 2, "p99": 3},
        "write_ms": {"p50": 1, "p95": 2, "p99": 3}}}}
    fake_run["together"] = {**fake_run["alone"], "seconds": 5.0, "oracle_disagreements": 0,
                            "questions": 10, "stale_uses": 0, "leaks": [], "cascades_wrong": 0}
    r = {**fake_run, "engine": {"graph_module": 42201, "redis": "8.10.2"}, "lives": 4, "workers": 2,
         "same_answers_as_alone": 4,
         "agents": {"ids_locked": {"expected": 8, "unique_ids": 8}, "ids_unlocked": {"unique_ids": 8},
                    "slot_protected": {"consistent": True, "active": 1, "facts": 8},
                    "slot_unprotected": {"consistent": False, "active": 4, "facts": 8},
                    "compound_locked": {"trials": 3, "violations": 0},
                    "compound_unlocked": {"trials": 3, "violations": 1}},
         "processes": {"settle_on": {"active": 1, "unreachable": 0, "consistent": True},
                       "settle_off": {"active": 9, "unreachable": 0, "consistent": False}}}
    md = cc.to_markdown(r)
    assert "graph module 42201" in md and "Speed-up from parallelism: 2.0x" in md
    assert "BROKEN" not in md and "broken (4 active of 8)" in md
