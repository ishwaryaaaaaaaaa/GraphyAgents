"""The decision engine: hard rules reject, soft rules score, highest score wins.

No LLM. `decide_with` is a pure function over a context dict, so the same rules can be
run on guarded memory (the agent) or on a baseline reader (the evaluation).
"""
import json
from pathlib import Path

from agent import tools

ROOT = Path(__file__).resolve().parent.parent
RULES = json.loads((Path(__file__).parent / "rules.json").read_text(encoding="utf-8"))
CATALOGUE = {
    i["name"]: i
    for i in json.loads((ROOT / "data" / "foods.json").read_text(encoding="utf-8"))["items"]
}
SKIP = {"name": "skip", "tags": []}
# The soft rules, in scoring order. Each can get a per-user multiplier learned from outcomes.
# Hard rules (diet, dislikes, availability, sugar streak) are safety checks and never learned.
LEARNABLE = ("sugar_earned", "likes", "healthy", "fried", "promise")


def resolve(names):
    """Turn option names into catalogue entries. Unknown names are an error: never invent."""
    out = []
    for n in names:
        if n == "skip":
            out.append(SKIP)
        elif n in CATALOGUE:
            out.append(CATALOGUE[n])
        else:
            raise KeyError(f"unknown option {n!r}: not in data/foods.json")
    return out


def build_context(user, day, options, facts=None, goal_tags=None):
    """Gather everything once, before the option loop. Overrides let a baseline swap the read."""
    if facts is None:
        facts = tools.get_facts(user, day)
    if goal_tags is None:
        goal_tags = [g["tag"] for g in tools.get_active_goals(user)]
    option_tags = {t for o in options for t in o["tags"]}
    scores = tools.rank_goals(user)
    top = max(scores.values()) if scores else 0.0
    cap = RULES["rank_multiplier_max"]
    rank = {t: (1 + (cap - 1) * s / top if top > 0 else 1.0) for t, s in scores.items()}
    return {
        "day": day,
        "facts": facts,
        "goals": set(goal_tags),
        "streak": {t: tools.count_streak(user, t, day) for t in set(goal_tags)},
        "promises": {t: tools.get_open_promises(user, t, day, RULES["promise_recent_days"])
                     for t in option_tags},
        "rank": rank,
        "weights": tools.get_weights(user),
    }


def decide_with(ctx, options):
    used = set()
    rejected = {}
    scored = []  # (score, goal_rank, option, reasons)
    n_days = RULES["sugar_streak_days"]

    def fact(key):
        f = ctx["facts"].get(key)
        if f is None:
            return None
        used.add(f[1])
        return f[0]

    for opt in options:
        name, tags = opt["name"], set(opt["tags"])

        # hard rules
        reject = None
        if "meat" in tags and fact("diet_style") == "vegetarian":
            reject = "you are vegetarian"
        elif fact(f"dislikes:{name}") == "yes":
            reject = "you dislike it"
        elif opt.get("requires") and fact(opt["requires"]) != "yes":
            reject = "not available"
        elif "sugar" in tags and "sugar" in ctx["goals"]:
            streak = ctx["streak"]["sugar"]
            if streak < n_days:
                reject = f"only {streak} of {n_days} days"
        if reject:
            rejected[name] = reject
            continue

        # soft rules: each is a 0/1 feature times a base weight times this user's learned
        # multiplier (ctx["weights"], default 1.0 for every rule)
        reasons, earned, neg = [], False, []
        feats = {r: 0.0 for r in LEARNABLE}
        if "sugar" in tags and "sugar" in ctx["goals"]:  # streak >= n_days here
            feats["sugar_earned"] = 1.0
            reasons.append(f"{ctx['streak']['sugar']} days off sugar: earned")
            earned = True
        if fact(f"likes:{name}") == "yes":
            feats["likes"] = 1.0
            reasons.append("you like it")
        if "healthy" in tags:
            feats["healthy"] = 1.0
        if "fried" in tags and "fried" in ctx["goals"]:
            feats["fried"] = 1.0
            neg.append("goal: eat less fried")  # explains why this option loses, if it does
        for tag in sorted(tags):
            promises = ctx["promises"].get(tag, [])
            if promises:
                p = promises[-1]
                feats["promise"] = 1.0
                how = "broken last time" if p["status"] == "broken" else "still open"
                reasons.append(f"promise: {p['text']} ({how})")
                break
        base = {"sugar_earned": RULES["sugar_earned"], "likes": RULES["likes"],
                "healthy": RULES["healthy"],
                "fried": RULES["fried_goal_penalty"] * ctx["rank"].get("fried", 1.0),
                "promise": RULES["promise"]}
        weights = ctx.get("weights") or {}
        score = 0.0
        for rule in LEARNABLE:
            score += base[rule] * weights.get(rule, 1.0) * feats[rule]
        goal_rank = max([ctx["rank"].get(t, 1.0) for t in tags if t in ctx["goals"]], default=0.0)
        scored.append((score, goal_rank, opt, reasons, earned, neg, feats))

    pick, pick_reasons, earned_treat, rules_fired = "none", [], None, []
    best = None
    for entry in scored:  # strictly greater, so the first listed wins a full tie
        if best is None or (entry[0], entry[1]) > (best[0], best[1]):
            best = entry
    if best is not None:
        pick, pick_reasons = best[2]["name"], best[3]
        earned_treat = pick if best[4] else None
        rules_fired = [r for r in LEARNABLE if best[6][r]]
    loser_penalties = [r for e in scored if e is not best for r in e[5]]

    reasons = []
    for r in list(rejected.values()) + pick_reasons + loser_penalties:
        if r not in reasons:
            reasons.append(r)
    return {
        "pick": pick,
        "mode": "rules",
        "reasons": reasons,
        "rejected": rejected,
        "used_fact_ids": sorted(used),
        "scores": {e[2]["name"]: e[0] for e in scored},
        "features": {e[2]["name"]: e[6] for e in scored},
        "rules_fired": rules_fired,
        "earned_treat": earned_treat,
    }


def decide(user, day, names, add_skip=False, record=True, mode="rules"):
    """Answer a fork from guarded memory, log the decision, grant an earned treat.

    mode="rules" ranks with the rule table (the default). mode="scorer" ranks the options that
    pass the hard rules with the trained model in models/scorer.joblib."""
    options = resolve(list(names) + (["skip"] if add_skip and "skip" not in names else []))
    ctx = build_context(user, day, options)
    if mode == "scorer":
        from agent import scorer  # imported here: scikit-learn is only needed for this mode
        result = scorer.decide_with_scorer(ctx, options, scorer.load())
    else:
        result = decide_with(ctx, options)
    if record:
        result["decision_id"] = tools.record_decision(
            user, day, result["pick"], [o["name"] for o in options], result["used_fact_ids"],
            mode=result["mode"], features=result["features"], scores=result["scores"],
            rules=result["rules_fired"]
        )
    if result["earned_treat"]:
        tools.grant_treat(user, "sugar", day)
    return result
