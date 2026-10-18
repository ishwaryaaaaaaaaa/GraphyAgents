"""Replay social lives and measure the advice-about-people layer.

There is no single correct answer to "should I talk to her", so this measures what is exact:

  principle consistency   the set of principles that fired equals what the independent oracle says
  verdict agreement       the verdict equals the oracle's (same spec: see README limits)
  stale-use               the status fact the advice rested on was no longer active
  audit                   the Decision node records the principles that fired and a graph path
  grounding               the advice text names only people, days, events and statuses that exist
                          in the brief; plus a test that corrupted texts are caught

Three readers see the same graph; only the read of the contact's status differs:
  guarded          the real agent (active status only)
  first_write      the first status ever written for the contact
  last_write_wins  the newest status row, whatever its lifecycle status
Only the guarded agent writes decisions and outcomes.
"""
from agent import counsel, extract, learn, store, tools
from eval.metrics import wilson

ARMS = ("guarded", "last_write_wins", "first_write")


def _rate(k, n):
    lo, hi = wilson(k, n)
    return {"k": k, "n": n, "pct": round(100 * k / n, 1) if n else None,
            "ci": [round(100 * lo, 1), round(100 * hi, 1)]}


def _apply(user, day, op):
    base = {"confidence": 1.0, "days_ago": 0}
    extract.apply_ops(user, [{**base, **op}], day)


def _status_meta(row):
    if row is None:
        return None
    return {"value": row["value"], "id": row["id"], "source": row["source"],
            "since": row["valid_from"]}


def corruptions(text, brief, other_names):
    """Texts that break the rules, each of which the checker must catch."""
    out = {}
    own = brief["contact"]["name"]
    if other_names and own in text:
        out["wrong_person"] = text.replace(own, other_names[0])
    out["invented_day"] = text + f" The last time was on day {max(counsel.brief_days(brief)) + 40}."
    kinds = {e["kind"] for e in brief["timeline"]} | {k for k, n in brief["counts"].items() if n}
    status = (brief["status"] or {}).get("value")
    if not (status == "strained" or brief["fresh_argument"] or "argument" in kinds):
        out["stale_status"] = text + " You two are still on strained terms."
    if "ghosted" not in kinds:
        out["invented_event"] = text + " They also ghosted you last week."
    if "argument" not in kinds:
        out["invented_argument"] = text + " They also had an argument with you."
    out["diagnosis"] = text + " Honestly, they sound toxic."
    return out


def _ask(user, step, others):
    cid, day, options = step["contact"], step["day"], tuple(step["options"])
    raw = [r for r in store.raw_facts(user) if r["key"] == f"contact:{cid}:status"]
    statuses = {r["id"]: r["status"] for r in store.raw_facts(user)}
    readers = {"guarded": counsel._UNSET,
               "first_write": _status_meta(raw[0] if raw else None),
               "last_write_wins": _status_meta(raw[-1] if raw else None)}

    arms, results = {}, {}
    for arm, status in readers.items():
        res = counsel.counsel(user, cid, day, kind=step["kind"], options=options, use_llm=False,
                              status=status, record=(arm == "guarded"))
        meta = res["brief"]["status"]
        arms[arm] = {
            "verdict": res["verdict"],
            "verdict_ok": res["verdict"] == step["expect_verdict"],
            "principles_ok": sorted(res["principles"]) == step["expect_principles"],
            "stale_use": bool(meta and statuses.get(meta["id"]) != "active"),
            "principles": sorted(res["principles"]),
        }
        results[arm] = res
    guarded = results["guarded"]

    audit =tools.explain_decision(user, guarded["decision_id"])
    audit_ok = bool(audit and audit["mode"] == "counsel" and audit["path_length"] is not None
                    and audit["contact"] == cid and audit["rules"] == guarded["principles"])
    brief = {**guarded["brief"], "_user": user}
    clean_ok = counsel.grounded(guarded["text"], brief, guarded["verdict"])
    caught = {name: not counsel.grounded(text, brief, guarded["verdict"])
              for name, text in corruptions(guarded["text"], guarded["brief"], others).items()}
    if step["outcome"]:
        learn.apply_outcome(user, guarded["decision_id"], step["outcome"], day)
    return {"id": step["id"], "day": day, "contact": cid, "trap": step["trap"],
            "expect_verdict": step["expect_verdict"], "expect_principles": step["expect_principles"],
            "arms": arms, "audit_ok": audit_ok, "grounded_clean": clean_ok, "corruptions": caught}


def replay(user, life):
    store.reset(user)
    names = [c["name"] for c in life["contacts"]]
    asks = []
    for s in life["steps"]:
        op, day, c = s["op"], s["day"], s.get("contact")
        if op == "add_contact":
            _apply(user, day, {"op": "add_contact", "name": s["name"], "relation": s["relation"]})
        elif op == "interaction":
            _apply(user, day, {"op": "log_interaction", "contact": c, "kind": s["kind"],
                               "tone": s["tone"], "what": s["kind"]})
        elif op == "status":
            _apply(user, day, {"op": "set_fact", "key": f"contact:{c}:status", "value": s["value"],
                               "source": s["source"]})
        elif op == "retract":
            _apply(user, day, {"op": "retract_fact", "key": f"contact:{c}:status",
                               "reason": "that was wrong"})
        elif op == "promise":
            _apply(user, day, {"op": "make_promise", "text": s["text"], "tag": "social",
                               "contact": c})
        elif op == "value":
            _apply(user, day, {"op": "add_value", "tag": s["tag"], "text": s["tag"]})
        elif op == "counsel":
            others = [n for n in names if n.lower() != c]
            asks.append(_ask(user, s, others))
    return asks


def summarise(runs):
    asks = [a for run in runs for a in run]
    out = {"questions": len(asks), "arms": {}, "by_trap": {}}
    for arm in ARMS:
        out["arms"][arm] = {
            "verdict": _rate(sum(a["arms"][arm]["verdict_ok"] for a in asks), len(asks)),
            "principles": _rate(sum(a["arms"][arm]["principles_ok"] for a in asks), len(asks)),
            "stale_use": _rate(sum(a["arms"][arm]["stale_use"] for a in asks), len(asks)),
        }
    for trap in sorted({a["trap"] for a in asks}):
        sub = [a for a in asks if a["trap"] == trap]
        out["by_trap"][trap] = {"n": len(sub), **{arm: sum(a["arms"][arm]["principles_ok"]
                                                           for a in sub) for arm in ARMS}}
    kinds = sorted({k for a in asks for k in a["corruptions"]})
    out["guarded_only"] = {
        "audit": _rate(sum(a["audit_ok"] for a in asks), len(asks)),
        "clean_text_accepted": _rate(sum(a["grounded_clean"] for a in asks), len(asks)),
        "corruptions_caught": {
            k: _rate(sum(a["corruptions"][k] for a in asks if k in a["corruptions"]),
                     sum(1 for a in asks if k in a["corruptions"])) for k in kinds},
    }
    return out


LABELS = {"guarded": "guarded (agent)", "last_write_wins": "last-write-wins (no guard)",
          "first_write": "first-write (no guard)"}


def _cell(r):
    return f"{r['k']} of {r['n']} ({r['pct']}%)"


def to_markdown(s):
    lines = [f"{s['questions']} questions about friends. 95% Wilson interval in brackets.", "",
             "| Reader | Same principles as the oracle | Same verdict as the oracle | Stale-use |",
             "|---|---|---|---|"]
    for arm in ARMS:
        m = s["arms"][arm]
        lines.append("| {} | {} [{}-{}] | {} | {} |".format(
            LABELS[arm], _cell(m["principles"]), *m["principles"]["ci"], _cell(m["verdict"]),
            _cell(m["stale_use"])))
    lines += ["", "Principle consistency by stale-memory trap (questions where the principles "
              "were exactly right):", "",
              "| Trap | n | " + " | ".join(LABELS[a] for a in ARMS) + " |",
              "|---|---|" + "---|" * len(ARMS)]
    for trap, row in s["by_trap"].items():
        lines.append(f"| {trap} | {row['n']} | " + " | ".join(str(row[a]) for a in ARMS) + " |")
    g = s["guarded_only"]
    lines += ["", "Guarded agent only:", "", "| Check | Result |", "|---|---|",
              f"| Decision records the principles and a graph path | {_cell(g['audit'])} |",
              f"| Advice text passes the grounding checker | {_cell(g['clean_text_accepted'])} |"]
    for name, r in g["corruptions_caught"].items():
        lines.append(f"| Corrupted text caught: {name.replace('_', ' ')} | {_cell(r)} |")
    return "\n".join(lines) + "\n"
