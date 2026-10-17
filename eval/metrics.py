"""Metric definitions. Counts first, percentages second, with a Wilson 95% interval.

task success       share of questions where the pick equals the expected answer
stale-use          share of decisions where any consulted fact was not active at question time
wrongful-keep      share of decisions that were wrong AND consulted a retracted/invalidated fact
wrongful-drop      share of questions where an active fact was missing from the guarded read
cascade complete   share of parent changes whose derived facts were dropped exactly as expected
time-travel        share of "what was true on day X" answers that are correct
audit coverage     share of agent decisions with a Decision node, a graph path from the person,
                   and USED edges matching exactly the facts consulted
"""
from math import sqrt


def wilson(k, n, z=1.96):
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / d
    half = z * sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, centre - half), min(1.0, centre + half))


def _rate(k, n):
    lo, hi = wilson(k, n)
    return {"k": k, "n": n, "pct": round(100 * k / n, 1) if n else None,
            "ci": [round(100 * lo, 1), round(100 * hi, 1)]}


def summarise(runs):
    """runs: list of replay() outputs (one per life)."""
    asks = [a for r in runs for a in r["asks"]]
    arms = sorted({arm for a in asks for arm in a["arms"]})
    result = {"questions": len(asks), "arms": {}, "by_trap": {}}
    for arm in arms:
        rows = [a["arms"][arm] for a in asks]
        result["arms"][arm] = {
            "task_success": _rate(sum(r["ok"] for r in rows), len(rows)),
            "stale_use": _rate(sum(r["stale_use"] for r in rows), len(rows)),
            "wrongful_keep": _rate(sum(r["wrongful_keep"] for r in rows), len(rows)),
        }
    for trap in sorted({a["trap"] for a in asks}):
        sub = [a for a in asks if a["trap"] == trap]
        result["by_trap"][trap] = {
            "n": len(sub),
            **{arm: sum(a["arms"][arm]["ok"] for a in sub) for arm in arms},
        }
    casc = [c for r in runs for c in r["cascade"]]
    tt = [t for r in runs for t in r["time_travel"]]
    result["guarded_only"] = {
        "wrongful_drop": _rate(sum(a["wrongful_drop"] for a in asks), len(asks)),
        "cascade_completeness": _rate(sum(c["ok"] for c in casc), len(casc)),
        "time_travel": _rate(sum(t["ok"] for t in tt), len(tt)),
        "audit_coverage": _rate(sum(a["audit_ok"] for a in asks), len(asks)),
    }
    return result
