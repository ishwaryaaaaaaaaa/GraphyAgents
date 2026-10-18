"""Random social lives with ground truth for the advice-about-people layer.

    generate(seed) -> {"seed", "contacts", "steps", ...}   (always the same for a seed)

A life has 3 contacts and a timeline of things told to the agent: interactions (cancelled plans,
arguments), status changes (strained from a fight, strained from a rumour, made up), retractions,
promises, stated values, and questions ("should I say something?"). Each scenario is built so a
specific principle should fire, and several are stale-memory traps: a friend who made up but is
still "strained" in an unguarded memory, or a rumour that was retracted.

The generator keeps its own spec-level world; ground truth comes from data/social_oracle.py reading
a snapshot of it, never from agent/. Steps are replayed by eval/social.py.
"""
import argparse
import copy
import json
import random
from collections import defaultdict

from data import social_oracle as so

NAMES = ["Priya", "Rhea", "Asha", "Kavya", "Ishan", "Neha", "Dev", "Tara", "Nikhil", "Sana"]
RELATIONS = ("friend", "friend", "friend", "colleague", "sister", "roommate", "cousin")
VALUE_TAGS = tuple(so.VALUE_LEAN)
PROMISES = ["call on Sunday", "return the book", "help with the move", "come to the recital"]
OPTIONS = ("talk", "wait", "let_it_go")


def cid(name):
    return name.lower()


class _Seq:
    def __init__(self):
        self.n = 0

    def __call__(self):
        self.n += 1
        return self.n


def _step(seq, day, op, **kw):
    return {"op": op, "day": day, "seq": seq(), **kw}


def _ask(seq, day, contact, options=OPTIONS, kind=None):
    return _step(seq, day, "counsel", contact=contact, options=list(options), kind=kind)


def _scenario_pattern(rng, seq, name, d0):
    kind = "cancel" if rng.random() < 0.8 else "ghosted"
    k = rng.choice([1, 2, 3, 3, 4])
    day, steps = d0, []
    for _ in range(k):
        steps.append(_step(seq, day, "interaction", contact=cid(name), kind=kind,
                           tone="neutral" if kind == "cancel" else "cold"))
        day += rng.randint(3, 12)
    last = steps[-1]["day"]
    steps.append(_ask(seq, last + rng.choice([0, 0, 1, 2]), cid(name), kind=kind))
    return steps


def _scenario_aging_pattern(rng, seq, name, d0):
    """Three cancellations spread over about 40 days: a pattern only if the window is long enough.
    Tests that old events stop counting (the 30-day window), not just that patterns are noticed."""
    days = [d0, d0 + rng.randint(17, 24)]
    days.append(days[-1] + rng.randint(17, 24))
    steps = [_step(seq, d, "interaction", contact=cid(name), kind="cancel", tone="neutral")
             for d in days]
    steps.append(_ask(seq, days[-1] + rng.choice([0, 1, 2]), cid(name), kind="cancel"))
    return steps


def _scenario_fresh_fight(rng, seq, name, d0):
    steps = [_step(seq, d0, "interaction", contact=cid(name), kind="argument", tone="tense"),
             _step(seq, d0, "status", contact=cid(name), value="strained", source="typed")]
    steps.append(_ask(seq, d0 + rng.choice([0, 1, 3, 6]), cid(name), kind="argument"))
    return steps


def _scenario_made_up(rng, seq, name, d0):
    made = d0 + rng.randint(2, 5)
    steps = [_step(seq, d0, "interaction", contact=cid(name), kind="argument", tone="tense"),
             _step(seq, d0, "status", contact=cid(name), value="strained", source="typed"),
             _step(seq, made, "interaction", contact=cid(name), kind="made_up", tone="warm"),
             _step(seq, made, "status", contact=cid(name), value="fine", source="typed")]
    steps.append(_ask(seq, made + rng.choice([0, 1, 2]), cid(name)))
    return steps


def _scenario_rumour(rng, seq, name, d0):
    steps = [_step(seq, d0, "status", contact=cid(name), value="strained", source="hearsay"),
             _ask(seq, d0 + 1, cid(name)),
             _step(seq, d0 + 2, "retract", contact=cid(name)),
             _ask(seq, d0 + 3, cid(name))]
    return steps


def _scenario_promise(rng, seq, name, d0):
    return [_step(seq, d0, "promise", contact=cid(name), text=rng.choice(PROMISES)),
            _ask(seq, d0 + rng.randint(1, 3), cid(name))]


def _scenario_cut_off(rng, seq, name, d0):
    steps = []
    if rng.random() < 0.6:
        steps.append(_step(seq, d0, "interaction", contact=cid(name), kind="argument", tone="tense"))
        steps.append(_step(seq, d0, "status", contact=cid(name), value="strained", source="typed"))
    steps.append(_ask(seq, d0 + rng.choice([0, 2, 5]), cid(name), OPTIONS + ("cut_off",)))
    return steps


SCENARIOS = [_scenario_pattern, _scenario_pattern, _scenario_aging_pattern,
             _scenario_aging_pattern, _scenario_fresh_fight, _scenario_made_up,
             _scenario_made_up, _scenario_rumour, _scenario_rumour, _scenario_promise,
             _scenario_cut_off]


# ---- the spec-level world: replay the steps and attach ground truth --------------------------

class _World:
    def __init__(self):
        self.events = defaultdict(list)     # contact -> [{"kind","day"}]
        self.status = {}                    # contact -> {"value","source"} or absent
        self.first_status = {}              # contact -> the first status ever written
        self.promises = defaultdict(list)   # contact -> [text]
        self.values = []
        self.past = defaultdict(list)       # contact -> newest first

    def snapshot(self, contact, day, options, stale=False):
        status = self.first_status.get(contact) if stale else self.status.get(contact)
        return {"day": day, "options": list(options), "events": copy.deepcopy(self.events[contact]),
                "status": dict(status) if status else None, "values": list(self.values),
                "promises": list(self.promises[contact]), "past": copy.deepcopy(self.past[contact])}


def _label(true_status, stale_status):
    t, s = (true_status or {}).get("value"), (stale_status or {}).get("value")
    if t == "fine" and s == "strained":
        return "made_up"
    if t is None and s == "strained" and (stale_status or {}).get("source") == "hearsay":
        return "rumour_retracted"
    return "other_status"


def generate(seed):
    rng = random.Random(seed)
    seq = _Seq()
    names = rng.sample(NAMES, 3)
    relations = {n: rng.choice(RELATIONS) for n in names}
    steps = [_step(seq, 1, "add_contact", name=n, relation=relations[n]) for n in names]

    for tag in rng.sample(VALUE_TAGS, rng.choice([0, 1, 1, 2])):
        steps.append(_step(seq, rng.randint(2, 60), "value", tag=tag))

    for n in names:  # two scenarios per contact, spread over about 90 days
        d = rng.randint(3, 12)
        for _ in range(2):
            scenario = rng.choice(SCENARIOS)
            steps += scenario(rng, seq, n, d)
            d += rng.randint(14, 40)

    steps.sort(key=lambda s: (s["day"], s["seq"]))
    world, n_ask = _World(), 0
    for s in steps:
        c = s.get("contact")
        if s["op"] == "interaction":
            world.events[c].append({"kind": s["kind"], "day": s["day"]})
        elif s["op"] == "status":
            st = {"value": s["value"], "source": s["source"]}
            cur = world.status.get(c)
            if not (cur and cur["value"] == st["value"]):  # spec rule 1: the same value written
                world.status[c] = st                       # again is a no-op, source included
            world.first_status.setdefault(c, dict(st))
        elif s["op"] == "retract":
            world.status.pop(c, None)
        elif s["op"] == "promise":
            world.promises[c].append(s["text"])
        elif s["op"] == "value":
            if s["tag"] not in world.values:
                world.values.append(s["tag"])
        elif s["op"] == "counsel":
            n_ask += 1
            snap = world.snapshot(c, s["day"], s["options"])
            stale = world.snapshot(c, s["day"], s["options"], stale=True)
            verdict, fired = so.verdict(snap)
            _, stale_fired = so.verdict(stale)
            s.update(id=f"S{n_ask}", expect_verdict=verdict, expect_principles=fired,
                     trap="none")
            if fired != stale_fired:
                s["trap"] = _label(snap["status"], stale["status"])
            outcome = rng.choices(["good", "bad", None], weights=[35, 25, 40])[0]
            s["outcome"] = outcome
            world.past[c].insert(0, {"pick": verdict, "result": outcome, "day": s["day"]})

    return {"seed": seed, "contacts": [{"name": n, "relation": relations[n]} for n in names],
            "steps": steps}


def summary(life):
    asks = [s for s in life["steps"] if s["op"] == "counsel"]
    return {"seed": life["seed"], "questions": len(asks),
            "traps": sum(a["trap"] != "none" for a in asks),
            "verdicts": {v: sum(a["expect_verdict"] == v for a in asks)
                         for v in ("talk", "wait", "let_it_go", "your_call")}}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--dump", action="store_true")
    args = ap.parse_args()
    life = generate(args.seed)
    print(json.dumps(life if args.dump else summary(life), indent=2))
