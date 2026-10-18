"""Handoffs between agents: they live in the graph, claims are atomic, and the whole demo runs with
two real processes that share nothing but the graph."""
import asyncio
import json
import sys
import threading
from pathlib import Path

import mcp_server
from agent import store, tools

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))


def call(name, args):
    result = asyncio.run(mcp_server.mcp.call_tool(name, args))
    return json.loads(result.content[0].text)


# ---- the store and tools ----

def test_a_handoff_goes_open_claimed_done_and_links_to_the_decision(user):
    hid = store.create_handoff(user, "intake", "advisor", "pick dinner", {"options": ["a"]}, 3)
    assert [p["id"] for p in tools.pending_handoffs(user, "advisor")] == [hid]
    assert tools.pending_handoffs(user, "somebody_else") == []
    assert tools.get_handoff(user, hid)["status"] == "open"

    assert store.claim_handoff(user, hid, "advisor", 4) is True
    assert tools.pending_handoffs(user, "advisor") == []        # a claimed handoff is no longer pending
    assert store.claim_handoff(user, hid, "advisor", 4) is False   # and cannot be claimed twice
    assert store.complete_handoff(user, hid, "intake", {"pick": "x"}, 5) is False   # not yours

    store.set_fact(user, "likes:pasta", "yes", 1)
    from agent import decide
    d = decide.decide(user, 5, ["pasta", "chana_chaat"])
    assert store.complete_handoff(user, hid, "advisor", {"pick": d["pick"]}, 5, d["decision_id"])
    h = tools.get_handoff(user, hid)
    assert (h["status"], h["claimed_by"], h["decision_id"]) == ("done", "advisor", d["decision_id"])
    assert h["result"] == {"pick": "pasta"} and h["payload"] == {"options": ["a"]}
    assert store.complete_handoff(user, hid, "advisor", {"pick": "y"}, 6) is False   # already done


def test_a_handoff_to_any_can_be_claimed_by_anyone_but_one_to_a_named_agent_cannot(user):
    anyone = store.create_handoff(user, "intake", "any", "t", {}, 1)
    named = store.create_handoff(user, "intake", "advisor", "t", {}, 1)
    assert store.claim_handoff(user, anyone, "whoever", 2) is True
    assert store.claim_handoff(user, named, "whoever", 2) is False
    assert store.claim_handoff(user, "h999", "advisor", 2) is False
    assert [h["status"] for h in tools.list_handoffs(user)] == ["claimed", "open"]


def test_exactly_one_agent_wins_each_handoff_when_many_race(user):
    ids = [store.create_handoff(user, "intake", "any", f"t{i}", {}, 1) for i in range(10)]
    wins, lock = {h: [] for h in ids}, threading.Lock()
    barrier = threading.Barrier(12)

    def racer(name):
        barrier.wait()
        for h in ids:
            if store.claim_handoff(user, h, name, 2):
                with lock:
                    wins[h].append(name)

    threads = [threading.Thread(target=racer, args=(f"agent{i}",)) for i in range(12)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert all(len(w) == 1 for w in wins.values()), wins          # never two winners, never none
    assert {h["claimed_by"] for h in tools.list_handoffs(user)} <= {f"agent{i}" for i in range(12)}


def test_handoffs_belong_to_one_person(user):
    other = user + "_x"
    store.reset(other)
    try:
        store.create_handoff(user, "intake", "advisor", "t", {}, 1)
        assert tools.pending_handoffs(other, "advisor") == [] and tools.list_handoffs(other) == []
    finally:
        store.reset(other)


# ---- over MCP ----

def test_the_handoff_tools_are_listed_and_work_over_mcp(user):
    names = {t.name for t in asyncio.run(mcp_server.mcp.list_tools())}
    assert {"handoff_create", "handoff_pending", "handoff_claim", "handoff_complete",
            "handoff_status"} <= names
    hid = call("handoff_create", dict(user=user, from_agent="intake", to_agent="advisor",
                                      task="dinner?", day=2, payload={"options": ["a", "b"]}))["handoff_id"]
    pending = call("handoff_pending", dict(user=user, agent="advisor"))
    assert [p["id"] for p in pending["pending"]] == [hid]            # a dict, even for one item
    assert call("handoff_claim", dict(user=user, handoff_id=hid, agent="advisor", day=3)) == {"claimed": True}
    assert call("handoff_claim", dict(user=user, handoff_id=hid, agent="other", day=3)) == {"claimed": False}
    done = call("handoff_complete", dict(user=user, handoff_id=hid, agent="advisor",
                                         result={"pick": "a"}, day=4))
    assert done == {"completed": True}
    assert call("handoff_status", dict(user=user, handoff_id=hid))["status"] == "done"
    assert "error" in call("handoff_status", dict(user=user, handoff_id="h404"))


# ---- two real processes ----

def test_two_agent_processes_coordinate_only_through_the_graph():
    import handoff_demo
    try:
        res = handoff_demo.run_demo(print_output=False)
    finally:
        store.reset(handoff_demo.USER)
    assert res["exit_codes"] == {"advisor": 0, "intake": 0}
    assert res["answers"] == ["chana_chaat", "chana_chaat", "paneer_wrap"]
    assert [h["status"] for h in res["handoffs"]] == ["done"] * 3
    assert {h["claimed_by"] for h in res["handoffs"]} == {"advisor"}
    for h, audit in zip(res["handoffs"], res["audits"]):
        assert audit["path_length"] == 1 and audit["pick"] == h["result"]["pick"]
        for used in audit["used"]:   # the advisor never rested an answer on a fact that was not active
            current = [x for x in used["history"] if x["id"] == used["id"]][0]
            assert current["status"] in ("active", "retracted", "superseded")
    assert res["other_tenant"] == {"facts": {}, "handoffs": []}
    pids = [line for line in res["transcript"] if "pid" in line]
    assert len(pids) == 2 and pids[0].split("pid ")[1] != pids[1].split("pid ")[1]   # really two processes
