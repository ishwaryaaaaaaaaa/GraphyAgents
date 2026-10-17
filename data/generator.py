"""Random fictional lives with ground-truth answers.

    generate(seed) -> {"seed", "persona", "steps", "length", ...}   (always the same for a seed)

Seeds 0-299 are train, 300-499 are test. Test lives also use items held out of training and
two change patterns training never sees (restarting an ended goal, a taste that flips twice).

The generator keeps its own `World`: what the person has told the agent so far, with
corrections applied. Ground truth comes from data/oracle.py reading a snapshot of that world,
never from the engine. Steps use the same shape as data/meera.py, so eval/replay.py runs both.
"""
import argparse
import copy
import json
import random
from collections import defaultdict

from data import oracle

CAT = oracle.CATALOGUE
ACTIVITIES = [n for n, i in CAT.items() if set(i["tags"]) & {"study", "leisure", "exercise", "social"}]
FOODS = [n for n in CAT if n not in ACTIVITIES]
HELDOUT = {n for n, i in CAT.items() if i.get("heldout")}
GOALS = ("sugar", "fried", "exercise", "study")
HOMES = ("hostel", "flat", "home")
PROMISES = {"study": ["study before sleep", "finish my assignment every day"],
            "exercise": ["walk every evening", "go to the gym three times a week"]}
ACTIVITY_FOR = {"study": "study_session", "exercise": "evening_walk"}
TEST_FROM = 300


def split_of(seed):
    return "test" if seed >= TEST_FROM else "train"


def pretty(name):
    return name.replace("_", " ")


# ---- the true world -----------------------------------------------------------------------

class World:
    """What the agent has been told, with corrections applied. Mirrors the written spec."""

    def __init__(self):
        self.facts, self.first_facts, self.parents = {}, {}, {}
        self.hist = defaultdict(list)       # key -> [{"start","end","value","retracted"}]
        self.retracted_keys = set()
        self.goals, self.goals_ever = set(), set()
        self.events, self.promises = [], []

    def _close(self, key, day, retracted=False):
        iv = self.hist[key][-1]
        iv["end"] = day
        iv["retracted"] = iv["retracted"] or retracted

    def _cascade(self, parent, day, retracted):
        dropped = []
        for k in sorted(self.facts):
            if parent in self.parents.get(k, ()):
                del self.facts[k]
                self._close(k, day, retracted)
                dropped.append(k)
                dropped += self._cascade(k, day, retracted)
        return sorted(dropped)

    def set(self, key, value, day, parents=()):
        cur = self.facts.get(key)
        if cur == value:
            return []
        if cur is not None:
            self._close(key, day)
        self.facts[key] = value
        self.first_facts.setdefault(key, value)
        self.hist[key].append({"start": day, "end": None, "value": value, "retracted": False})
        if parents:
            self.parents[key] = list(parents)
        return self._cascade(key, day, False) if cur is not None else []

    def retract(self, key, day):
        if key not in self.facts:
            return []
        del self.facts[key]
        self._close(key, day, retracted=True)
        self.retracted_keys.add(key)
        return self._cascade(key, day, True)

    def snapshot(self, stale=False):
        return {"facts": dict(self.first_facts if stale else self.facts),
                "goals": sorted(self.goals_ever if stale else self.goals),
                "events": copy.deepcopy(self.events),
                "promises": copy.deepcopy(self.promises)}


# ---- step constructors (same shape as data/meera.py) ---------------------------------------

def _set(day, key, value, derived_from=(), expect_dropped=None, says=()):
    return {"op": "set", "day": day, "key": key, "value": value, "derived_from": list(derived_from),
            "expect_dropped": expect_dropped, "says": list(says)}


def _retract(day, key, reason, expect_dropped, says=()):
    return {"op": "retract", "day": day, "key": key, "reason": reason,
            "expect_dropped": expect_dropped, "says": list(says)}


def _goal(op, day, tag, says=()):
    return {"op": op, "day": day, "tag": tag, "says": list(says)}


def _event(day, kind, tag, what):
    return {"op": "event", "day": day, "kind": kind, "what": what, "tag": tag}


# ---- change templates -----------------------------------------------------------------------

class Ctx:
    def __init__(self, rng, foods, length):
        self.rng, self.foods, self.length = rng, foods, length
        self.locked, self.later, self.n_promises = set(), defaultdict(list), 0

    def unlocked(self, names):
        return [n for n in names if n not in self.locked]


def t_diet(w, c, day):
    new = "vegetarian" if w.facts.get("diet_style") == "non_veg" else "non_veg"
    w.set("diet_style", new, day)
    says = (["I turned vegetarian", "ok I've gone vegetarian now"] if new == "vegetarian"
            else ["I eat meat again", "I'm now non-veg"])
    meat = [n for n in c.foods if "meat" in CAT[n]["tags"]]
    return [_set(day, "diet_style", new, says=says)], c.rng.sample(meat, min(2, len(meat)))


def t_taste(w, c, day):
    liked = [n for n in c.unlocked(c.foods) if w.facts.get(f"likes:{n}") == "yes"]
    if liked and c.rng.random() < 0.6:
        x, val = c.rng.choice(liked), "no"
        says = [f"I don't like {pretty(x)} anymore".replace(" anymore", ""), f"I'm over {pretty(x)}"]
    else:
        pool = [n for n in c.unlocked(c.foods) if w.facts.get(f"likes:{n}") != "yes"]
        if not pool:
            return None
        x, val = c.rng.choice(pool), "yes"
        says = [f"I love {pretty(x)}", f"I really like {pretty(x)}"]
    w.set(f"likes:{x}", val, day)
    return [_set(day, f"likes:{x}", val, says=says)], [x]


def t_move(w, c, day):
    cur = w.facts.get("lives_in")
    new = c.rng.choice([h for h in HOMES if h != cur])
    dropped = w.set("lives_in", new, day)
    place = {"hostel": "the hostel", "flat": "a flat", "home": "home"}[new]
    steps = [_set(day, "lives_in", new, expect_dropped=dropped, says=[f"I moved to {place}"])]
    if new == "hostel":
        w.set("mess_meals_available", "yes", day, parents=["lives_in"])
        steps.append(_set(day, "mess_meals_available", "yes", derived_from=["lives_in"]))
    return steps, [n for n in ("mess_thali", "mess_dinner") if n in c.foods]


def _items_for_goal(c, tag):
    return [n for n in c.foods if tag in CAT[n]["tags"]][:4]


def t_goal_start(w, c, day, allow_restart):
    pool = [g for g in GOALS if g not in w.goals and (allow_restart or g not in w.goals_ever)]
    if not pool:
        return None
    tag = c.rng.choice(pool)
    w.goals.add(tag)
    w.goals_ever.add(tag)
    says = {"sugar": ["I want to cut sugar", "I'm off sugar from today"],
            "fried": ["I want to eat less fried food", "I want to cut fried food"]}.get(tag, [])
    return [_goal("goal_start", day, tag, says)], _items_for_goal(c, tag)


def t_goal_end(w, c, day):
    if not w.goals:
        return None
    tag = c.rng.choice(sorted(w.goals))
    w.goals.discard(tag)
    says = [f"I'm done with the {tag} goal", f"drop the {tag} goal"] if tag in ("sugar", "fried") else []
    return [_goal("goal_end", day, tag, says)], _items_for_goal(c, tag)


def t_promise(w, c, day):
    open_tags = {p["tag"] for p in w.promises if p["status"] == "open"}
    pool = [t for t in sorted(PROMISES) if t not in open_tags]
    delta = c.rng.randint(2, 8)
    if not pool or day + delta > c.length:
        return None
    tag = c.rng.choice(pool)
    text = c.rng.choice(PROMISES[tag])
    c.n_promises += 1
    alias = f"p{c.n_promises}"
    w.promises.append({"alias": alias, "tag": tag, "text": text, "made": day, "status": "open",
                       "closed": None})
    outcome = c.rng.choice(["kept", "broken"])

    def mark(w_, c_, d):
        for p in w_.promises:
            if p["alias"] == alias:
                p["status"], p["closed"] = outcome, d
        return [{"op": "promise_mark", "day": d, "alias": alias, "status": outcome}], \
            [ACTIVITY_FOR[tag]]

    c.later[day + delta].append(mark)
    step = {"op": "promise", "day": day, "alias": alias, "text": text, "tag": tag,
            "says": [f"I promise to {text}"]}
    return [step], [ACTIVITY_FOR[tag]]


def t_mistaken_dislike(w, c, day):
    pool = [n for n in c.unlocked(c.foods) if f"dislikes:{n}" not in w.hist]
    delta = c.rng.randint(3, 12)
    if not pool or day + delta > c.length:
        return None
    x = c.rng.choice(pool)
    key, derived = f"dislikes:{x}", f"avoid_{x}_orders"
    w.set(key, "yes", day)
    w.set(derived, "yes", day, parents=[key])
    c.locked.add(x)

    def fix(w_, c_, d):
        dropped = w_.retract(key, d)
        c_.locked.discard(x)
        return [_retract(d, key, "that message was misread as hers", dropped,
                         says=[f"that was wrong about {pretty(x)}", f"I never disliked {pretty(x)}"])], [x]

    c.later[day + delta].append(fix)
    return [_set(day, key, "yes", says=[f"I hate {pretty(x)}"]),
            _set(day, derived, "yes", derived_from=[key])], [x]


def t_double_change(w, c, day):
    """Test lives only: a taste that flips twice within a week."""
    delta = c.rng.randint(2, 6)
    pool = c.unlocked(c.foods)
    if day + delta > c.length or not pool:
        return None
    x = c.rng.choice(pool)
    key = f"likes:{x}"
    first = "no" if w.facts.get(key) == "yes" else "yes"
    w.set(key, first, day)
    c.locked.add(x)

    def flip(w_, c_, d):
        second = "yes" if first == "no" else "no"
        w_.set(key, second, d)
        c_.locked.discard(x)
        return [_set(d, key, second)], [x]

    c.later[day + delta].append(flip)
    return [_set(day, key, first)], [x]


def _choose_change(rng, w, c, day, test):
    options = [("diet", 2), ("taste", 3), ("move", 2), ("goal_start", 2), ("goal_end", 1),
               ("promise", 2), ("mistaken_dislike", 2)]
    if test:
        options.append(("double_change", 1))
    names = [n for n, wt in options for _ in range(wt)]
    rng.shuffle(names)
    for name in names:
        if name == "diet":
            r = t_diet(w, c, day)
        elif name == "taste":
            r = t_taste(w, c, day)
        elif name == "move":
            r = t_move(w, c, day)
        elif name == "goal_start":
            r = t_goal_start(w, c, day, allow_restart=test)
        elif name == "goal_end":
            r = t_goal_end(w, c, day)
        elif name == "promise":
            r = t_promise(w, c, day)
        elif name == "mistaken_dislike":
            r = t_mistaken_dislike(w, c, day)
        else:
            r = t_double_change(w, c, day)
        if r:
            return name, r
    return None, None


# ---- questions -------------------------------------------------------------------------------

def _trap_label(true_w, stale_w, names, day, expected, retracted):
    comps = [("fact", k) for k in sorted(set(true_w["facts"]) | set(stale_w["facts"]))
             if true_w["facts"].get(k) != stale_w["facts"].get(k)]
    if set(true_w["goals"]) != set(stale_w["goals"]):
        comps.append(("goals", None))
    for kind, k in comps:
        patched = copy.deepcopy(true_w)
        if kind == "goals":
            patched["goals"] = stale_w["goals"]
        elif k in stale_w["facts"]:
            patched["facts"][k] = stale_w["facts"][k]
        else:
            patched["facts"].pop(k, None)
        if oracle.expected_pick(patched, names, day) != expected:
            if kind == "goals":
                return "goal_ended"
            if k == "diet_style":
                return "diet_change"
            if k.startswith("likes:"):
                return "taste_flip"
            if k == "mess_meals_available":
                return "cascade"
            return "retraction" if k in retracted or k.replace("avoid_", "dislikes:").removesuffix("_orders") in retracted else "dislike"
    return "combined"


def make_question(rng, w, c, day, related, want_trap, qid):
    true_w, stale_w = w.snapshot(), w.snapshot(stale=True)
    # open, kept or broken promises: asking days after one closed tests that it stops counting
    open_promise = [p["tag"] for p in w.promises
                    if p["status"] == "open" or (p["closed"] is not None and p["closed"] >= day - 8)]
    need_close = rng.random() < 0.35  # aim at a close call, where rule weights decide the answer
    fallback = None
    for _ in range(40):
        if open_promise and rng.random() < 0.35:
            tag = rng.choice(sorted(set(open_promise)))
            names = [ACTIVITY_FOR[tag], "netflix"]
            names += rng.sample([n for n in c.foods if n not in names], rng.choice([0, 0, 1, 2]))
            rng.shuffle(names)
            add_skip = False
        elif "sugar" in w.goals and rng.random() < 0.35:
            names, add_skip = [rng.choice([n for n in c.foods if "sugar" in CAT[n]["tags"]])], True
        else:
            n = rng.choice([2, 2, 3, 4])
            pool = [r for r in related if r in c.foods]
            names = rng.sample(pool, min(len(pool), rng.randint(1, 2))) if pool else []
            while len(names) < n:
                cand = rng.choice(c.foods)
                if cand not in names:
                    names.append(cand)
            rng.shuffle(names)
            add_skip = False
        asked = names + (["skip"] if add_skip else [])
        expected = oracle.expected_pick(true_w, asked, day)
        if expected is None:
            continue  # depends on the unknown goal ranks: never asked
        stale = oracle.expected_pick(stale_w, asked, day)
        is_trap = stale is not None and stale != expected
        q = {"op": "ask", "day": day, "id": qid, "options": names, "expect": expected,
             "trap": "none", "add_skip": add_skip, "note": "",
             "heldout": any(n in HELDOUT for n in names)}
        if is_trap:
            q["trap"] = _trap_label(true_w, stale_w, asked, day, expected, w.retracted_keys)
        m = oracle.margin(true_w, asked, day)
        close = m is not None and 1 <= m <= 2
        if (is_trap or not want_trap) and (close or not need_close):
            return q
        fallback = fallback or q
    return fallback


# ---- one life --------------------------------------------------------------------------------

def generate(seed):
    rng = random.Random(seed)
    test = seed >= TEST_FROM
    foods = [n for n in FOODS if test or n not in HELDOUT]
    length = rng.randint(40, 90)
    w, c = World(), Ctx(rng, foods, length)
    steps = []

    # day 1: who she is
    diet0, home0 = rng.choice(["non_veg", "vegetarian"]), rng.choice(HOMES)
    likes = rng.sample(foods, rng.randint(3, 6))
    dislikes = rng.sample([n for n in foods if n not in likes], rng.randint(1, 3))
    w.set("diet_style", diet0, 1)
    steps.append(_set(1, "diet_style", diet0))
    w.set("lives_in", home0, 1)
    steps.append(_set(1, "lives_in", home0))
    if home0 == "hostel":
        w.set("mess_meals_available", "yes", 1, parents=["lives_in"])
        steps.append(_set(1, "mess_meals_available", "yes", derived_from=["lives_in"]))
    for x in likes:
        w.set(f"likes:{x}", "yes", 1)
        steps.append(_set(1, f"likes:{x}", "yes"))
    for x in dislikes:
        w.set(f"dislikes:{x}", "yes", 1)
        w.set(f"avoid_{x}_orders", "yes", 1, parents=[f"dislikes:{x}"])
        steps.append(_set(1, f"dislikes:{x}", "yes"))
        steps.append(_set(1, f"avoid_{x}_orders", "yes", derived_from=[f"dislikes:{x}"]))
    persona = {"diet": diet0, "home": home0, "likes": likes, "dislikes": dislikes}

    # schedule
    n_changes = rng.randint(6, 12)
    change_days = sorted(rng.sample(range(6, length - 1), min(n_changes, length - 7)))
    start_goals = {rng.randint(2, 6): g for g in rng.sample(GOALS, rng.randint(1, 3))}
    n_questions = rng.randint(8, 16)
    asks = defaultdict(list)   # day -> [(related, want_trap)]
    for d in sorted(rng.sample(range(2, length + 1), n_questions // 2)):
        asks[d].append(([], rng.random() < 0.5))
    qn, templates_used = 0, []

    for day in range(2, length + 1):
        fresh = []
        if day in start_goals and start_goals[day] not in w.goals:
            tag = start_goals[day]
            w.goals.add(tag)
            w.goals_ever.add(tag)
            fresh.append(_goal("goal_start", day, tag))
        for fn in c.later.pop(day, []):
            s, rel = fn(w, c, day)
            fresh += s
            asks[min(length, day + rng.randint(0, 3))].append((rel, True))
        if day in change_days:
            name, r = _choose_change(rng, w, c, day, test)
            if r:
                templates_used.append(name)
                fresh += r[0]
                asks[min(length, day + rng.randint(0, 3))].append((r[1], rng.random() < 0.8))
        steps += fresh

        if "sugar" in w.goals:  # a daily log of the goal; occasionally a slip instead
            if rng.random() < 0.04:
                kind, what = "slip", "slipped on sugar"
            elif rng.random() < 0.88:
                kind, what = "clean_day", "stayed off sugar"
            else:
                kind = None
            if kind:
                w.events.append({"day": day, "kind": kind, "tag": "sugar"})
                steps.append(_event(day, kind, "sugar", what))

        for related, want_trap in asks.pop(day, []):
            qn += 1
            q = make_question(rng, w, c, day, related, want_trap, f"Q{qn}")
            if q is None:
                qn -= 1
                continue
            steps.append(q)
            if q["expect"] != "none" and "sugar" in CAT.get(q["expect"], {"tags": []})["tags"] \
                    and "sugar" in w.goals:
                w.events.append({"day": day, "kind": "treat", "tag": "sugar"})  # the agent grants it

    # time travel on slots that changed
    movers = sorted(k for k, ivs in w.hist.items() if len(ivs) >= 2)
    for i, key in enumerate(rng.sample(movers, min(4, len(movers)))):
        for j, d in enumerate(sorted(rng.sample(range(1, length + 1), 2))):
            steps.append({"op": "time_travel", "id": f"T{i}{j}", "key": key, "as_of": d,
                          "expect": oracle.fact_at(w.hist, key, d)})

    return {"seed": seed, "split": split_of(seed), "length": length, "persona": persona,
            "changes": templates_used, "steps": steps}


def summary(life):
    asks = [s for s in life["steps"] if s["op"] == "ask"]
    traps = [a for a in asks if a["trap"] != "none"]
    return {"seed": life["seed"], "split": life["split"], "days": life["length"],
            "steps": len(life["steps"]), "questions": len(asks), "traps": len(traps),
            "heldout_questions": sum(a.get("heldout", False) for a in asks)}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--dump", action="store_true", help="print the whole life as JSON")
    args = ap.parse_args()
    life = generate(args.seed)
    print(json.dumps(life if args.dump else summary(life), indent=2))
