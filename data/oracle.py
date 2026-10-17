"""The oracle: ground truth for generated lives, written from the README rule table.

It reads a snapshot of the generator's TRUE world (what the person has told the agent so far,
with corrections applied) and applies the written spec. It must NOT import anything from
agent/: if it shared code with decide.py a bug would grade itself. The constants below are
copied from the spec on purpose; tests/test_oracle.py checks they still match rules.json.

World snapshot shape:
  {"facts": {key: value}, "goals": [active tags],
   "events": [{"day", "kind", "tag"}], "promises": [{"tag", "text", "made", "status", "closed"}]}

PageRank is not reimplemented here. Goal rank only scales the fried penalty (x1.0 to x1.5) and
breaks exact ties, so `expected_pick` tries a grid of possible ranks and returns None
("ambiguous") if the answer depends on them. Ambiguous questions are never asked.
"""
import itertools
import json
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
CATALOGUE = {i["name"]: i for i in json.loads(
    (_ROOT / "data" / "foods.json").read_text(encoding="utf-8"))["items"]}
SKIP = {"name": "skip", "tags": []}

# --- the spec ---
STREAK_DAYS = 5          # sugar item needs this many clean days since the last treat/slip
LIKE_BONUS = 2
HEALTHY_BONUS = 1
FRIED_GOAL_PENALTY = -3  # times goal rank in [1.0, 1.5]
SUGAR_EARNED_BONUS = 5
PROMISE_BONUS = 3
PROMISE_RECENT_DAYS = 3
RANK_GRID = (1.0, 1.25, 1.5)


def streak(events, tag, day):
    """Clean days with this tag since the last treat or slip (all of them if none)."""
    last = max((e["day"] for e in events
                if e["tag"] == tag and e["kind"] in ("treat", "slip") and e["day"] <= day),
               default=-1)
    return sum(1 for e in events
               if e["tag"] == tag and e["kind"] == "clean_day" and last < e["day"] <= day)


def _promise_bonus(world, tags, day):
    for t in sorted(tags):
        for p in world["promises"]:
            if p["tag"] != t or p["made"] > day:
                continue
            if p["status"] == "open" or (p["status"] == "broken"
                                         and p["closed"] is not None
                                         and p["closed"] >= day - PROMISE_RECENT_DAYS):
                return PROMISE_BONUS
    return 0


def _score(world, opt, day, ranks):
    """None if the option is rejected, else (score, goal_rank)."""
    facts, goals = world["facts"], set(world["goals"])
    tags, name = set(opt["tags"]), opt["name"]
    if "meat" in tags and facts.get("diet_style") == "vegetarian":
        return None
    if facts.get(f"dislikes:{name}") == "yes":
        return None
    if opt.get("requires") and facts.get(opt["requires"]) != "yes":
        return None
    sugar_on = "sugar" in tags and "sugar" in goals
    if sugar_on and streak(world["events"], "sugar", day) < STREAK_DAYS:
        return None
    score = 0.0
    if sugar_on:
        score += SUGAR_EARNED_BONUS
    if facts.get(f"likes:{name}") == "yes":
        score += LIKE_BONUS
    if "healthy" in tags:
        score += HEALTHY_BONUS
    if "fried" in tags and "fried" in goals:
        score += FRIED_GOAL_PENALTY * ranks.get("fried", 1.0)
    score += _promise_bonus(world, tags, day)
    goal_rank = max([ranks.get(t, 1.0) for t in tags if t in goals], default=0.0)
    return (score, goal_rank)


def _pick_with(world, options, day, ranks):
    best, pick = None, "none"
    for opt in options:  # strictly greater: the first listed wins a full tie
        s = _score(world, opt, day, ranks)
        if s is not None and (best is None or s > best):
            best, pick = s, opt["name"]
    return pick


def margin(world, names, day):
    """Score gap between the best and second-best allowed option (goal rank taken as 1.0).
    Used to aim questions at close calls, where rule weights decide the answer."""
    scores = sorted((s[0] for o in resolve(names)
                     if (s := _score(world, o, day, {})) is not None), reverse=True)
    return scores[0] - scores[1] if len(scores) >= 2 else None


def resolve(names):
    return [SKIP if n == "skip" else CATALOGUE[n] for n in names]


def expected_pick(world, names, day):
    """The right answer, or None if it depends on the unknown goal ranks."""
    options = resolve(names)
    goals = sorted(set(world["goals"]))
    picks = set()
    for combo in itertools.product(RANK_GRID, repeat=len(goals)):
        picks.add(_pick_with(world, options, day, dict(zip(goals, combo))))
        if len(picks) > 1:
            return None
    return picks.pop()


def fact_at(history, key, day):
    """Value true on `day` from interval history [{"start","end","value","retracted"}]."""
    for iv in reversed(history.get(key, [])):
        if iv["retracted"]:
            continue
        if iv["start"] <= day and (iv["end"] is None or iv["end"] > day):
            return iv["value"]
    return None
