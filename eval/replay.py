"""Replay a scripted life and answer every question with each reader.

All readers answer against the same live graph at the moment of the question, so the only
difference between arms is the read rule. Only the guarded agent writes (its decisions and
earned treats); the baselines never touch the graph.
"""
from agent import decide, store, tools
from eval import baseline

STALE_KILLERS = ("retracted", "invalidated")


def _statuses(user):
    return {r["id"]: r["status"] for r in store.raw_facts(user)}


def _arm_result(user, day, options, arm, statuses):
    if arm == "guarded":
        facts, goal_tags = None, None
    else:
        facts = baseline.ARMS[arm](user)
        goal_tags = baseline.all_goal_tags(user)
    ctx = decide.build_context(user, day, options, facts=facts, goal_tags=goal_tags)
    res = decide.decide_with(ctx, options)
    stale = [i for i in res["used_fact_ids"] if statuses.get(i) != "active"]
    return res, stale


def _ask(user, step, observer=None):
    day, names = step["day"], list(step["options"])
    if step["add_skip"]:
        names.append("skip")
    options = decide.resolve(names)
    if observer:  # lets another evaluation look at the world just before the agent answers
        observer(user, step, options)
    statuses = _statuses(user)
    active_keys = {r["key"] for r in store.raw_facts(user) if r["status"] == "active"}

    arms = {}
    for arm in baseline.ARMS:
        res, stale = _arm_result(user, day, options, arm, statuses)
        ok = res["pick"] == step["expect"]
        arms[arm] = {
            "pick": res["pick"], "ok": ok, "used": res["used_fact_ids"], "stale": stale,
            "stale_use": bool(stale),
            "wrongful_keep": (not ok) and any(statuses[i] in STALE_KILLERS for i in stale),
        }

    # the real agent: same answer as the guarded arm, but it logs the decision and grants treats
    final = decide.decide(user, day, step["options"], add_skip=step["add_skip"])
    assert final["pick"] == arms["guarded"]["pick"], "guarded arm and agent disagree"

    seen = set(tools.get_facts(user, day))
    audit = tools.explain_decision(user, final["decision_id"])
    audit_ok = bool(
        audit and audit["path_length"] is not None and final["reasons"] is not None
        and sorted(u["id"] for u in audit["used"]) == final["used_fact_ids"]
    )
    return {
        "id": step["id"], "day": day, "trap": step["trap"], "expect": step["expect"],
        "heldout": step.get("heldout", False),
        "options": names, "arms": arms, "reasons": final["reasons"],
        "wrongful_drop": bool(active_keys - seen), "audit_ok": audit_ok,
    }


def replay(user, steps, observer=None):
    store.reset(user)
    out = {"asks": [], "cascade": [], "time_travel": []}
    promises = {}
    for s in steps:
        op, day = s["op"], s.get("day")
        if op == "set":
            _, dropped = store.set_fact(user, s["key"], s["value"], day,
                                        derived_from=s["derived_from"])
            if s["expect_dropped"] is not None:
                out["cascade"].append({"key": s["key"], "day": day, "expected": s["expect_dropped"],
                                       "got": dropped, "ok": sorted(dropped) == sorted(s["expect_dropped"])})
        elif op == "retract":
            dropped = store.retract_fact(user, s["key"], day, s["reason"])
            if s["expect_dropped"] is not None:
                out["cascade"].append({"key": s["key"], "day": day, "expected": s["expect_dropped"],
                                       "got": dropped, "ok": sorted(dropped) == sorted(s["expect_dropped"])})
        elif op == "goal_start":
            store.start_goal(user, s["tag"], day)
        elif op == "goal_end":
            store.end_goal(user, s["tag"], day)
        elif op == "event":
            store.log_event(user, s["kind"], s["what"], s["tag"], day)
        elif op == "promise":
            promises[s["alias"]] = store.make_promise(user, s["text"], s["tag"], day)
        elif op == "promise_mark":
            store.mark_promise(user, promises[s["alias"]], s["status"], day)
        elif op == "ask":
            out["asks"].append(_ask(user, s, observer))
        elif op == "time_travel":
            got = tools.get_fact_at(user, s["key"], s["as_of"])
            out["time_travel"].append({"id": s["id"], "key": s["key"], "as_of": s["as_of"],
                                       "expected": s["expect"], "got": got, "ok": got == s["expect"]})
        else:
            raise ValueError(f"unknown step op {op!r}")
    return out
