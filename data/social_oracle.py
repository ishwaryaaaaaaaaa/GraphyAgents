"""Independent oracle for advice about people, written from the README principle table.

Like data/oracle.py it must NOT import agent/: it reads a snapshot of the generator's true world
and applies the written spec, so a bug in agent/counsel.py cannot grade itself. The constants are
copied on purpose; tests/test_social_eval.py checks they still match counsel.py.

World snapshot:
  {"day", "options", "events": [{"kind","day"}], "status": {"value","source"} or None,
   "values": [tags], "promises": [text], "past": [{"pick","result","day"}]}   (past newest first,
   unrated decisions included: the spec looks at the three newest and ignores unrated ones)
"""

PATTERN_DAYS, PATTERN_MIN, FRESH_DAYS = 30, 3, 1
VALUE_BOOST = 1.5
HUMILITY_MARGIN = 1.0
TIE_ORDER = {"wait": 0.02, "let_it_go": 0.01}
VALUE_LEAN = {
    "honesty": {"talk": 2.0},
    "show_up": {"talk": 1.0},
    "peace": {"let_it_go": 1.0, "wait": 1.0},
    "self_respect": {"talk": 1.0},
    "loyalty": {"talk": 1.0, "let_it_go": 1.0},
}


def principles(world):
    """[(principle id, {option: lean})] in the order the spec lists them."""
    day, opts, ev = world["day"], set(world["options"]), world["events"]
    status = (world["status"] or {}).get("value")
    source = (world["status"] or {}).get("source")
    out = []

    fresh = any(e["kind"] == "argument" and day - (FRESH_DAYS + 1) < e["day"] <= day for e in ev)
    if fresh:
        out.append(("fresh_anger", {"talk": -2.0, "wait": 3.0}))
    if "cut_off" in opts:
        out.append(("irreversible", {"cut_off": -5.0, "wait": 5.0}))
    for kind in ("cancel", "ghosted"):
        n = sum(1 for e in ev if e["kind"] == kind and day - PATTERN_DAYS < e["day"] <= day)
        if n >= PATTERN_MIN:
            out.append(("repeated_pattern", {"talk": 2.0, "let_it_go": -1.0}))
            break
    grudge = status == "strained" and source == "hearsay"
    if grudge:
        out.append(("grudge_check", {"let_it_go": 1.0, "wait": 1.0, "talk": -1.0}))
    if status == "strained" and not grudge and not fresh and "talk" in opts:
        out.append(("cheap_repair", {"talk": 1.0}))
    if world["promises"]:
        out.append(("honour_promise", {}))
    for tag in world["values"]:
        lean = {o: w * VALUE_BOOST for o, w in VALUE_LEAN[tag].items() if o in opts}
        if lean:
            out.append((f"value:{tag}", lean))
    for past in world["past"][:3]:
        if past["result"] in ("good", "bad") and past["pick"] in opts:
            out.append(("past_advice", {past["pick"]: 1.0 if past["result"] == "good" else -2.0}))
    ids = {p for p, _ in out}
    if not ids & {"fresh_anger", "irreversible", "repeated_pattern", "grudge_check", "cheap_repair"}:
        out.append(("no_pattern", {"let_it_go": 1.0}))
    return out


def verdict(world):
    """(verdict, sorted fired principle ids)."""
    fired = principles(world)
    scores = {o: 0.0 for o in world["options"]}
    for _, lean in fired:
        for o, w in lean.items():
            if o in scores:
                scores[o] += w
    ranked = sorted(scores, key=lambda o: -(scores[o] + TIE_ORDER.get(o, 0.0)))
    margin = scores[ranked[0]] - scores[ranked[1]] if len(ranked) > 1 else 99.0
    ids = sorted(p for p, _ in fired)
    if margin < HUMILITY_MARGIN and "cut_off" not in world["options"]:
        return "your_call", ids
    return ranked[0], ids
