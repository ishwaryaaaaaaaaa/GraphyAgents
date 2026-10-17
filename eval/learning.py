"""Does the agent learn what each person actually wants?

Simulated users have HIDDEN preference weights (some barely care about "healthy", some dislike
fried food far more than the defaults assume, some love their favourites more). The agent starts
with the default weights and only ever sees good / mixed / bad feedback on its picks.

For each user the same sequence of forks goes through two agents:
  fixed    default weights, never learns
  learned  the real rule from agent/learn.py, updated after every outcome

Ground truth for a fork is the option the user's hidden weights rank first. The hidden user reuses
decide_with's scoring structure with different multipliers: what is under test is the learning, not
the scoring. Forks are trade-offs (every option has at least one active feature); random catalogue
forks are mostly easy, with nothing to weigh and so nothing to learn. How much a user differs from
the defaults is an assumption, so three populations are reported:

  mild      multipliers in 0.6-1.6   (close to the defaults)
  moderate  multipliers in 0.3-2.2
  strong    multipliers in 0.05-3.0  (a very different person)

Pure Python, no database, deterministic. The update rule and learning rate were chosen on
development seeds 0-99 (scripts/learning_sweep.py); this reports seeds 1000+.
"""
import random

from agent import decide, learn

LEVELS = {"mild": (0.6, 1.6), "moderate": (0.3, 2.2), "strong": (0.05, 3.0)}
WINDOWS = ((0, 20), (20, 40), (40, 60))


def _persona(rng):
    foods = [n for n in decide.CATALOGUE if not decide.CATALOGUE[n].get("requires")
             and not {"study", "leisure", "exercise", "social"} & set(decide.CATALOGUE[n]["tags"])]
    liked = rng.sample(foods, 10)
    facts = {f"likes:{n}": ("yes", f"f{i}") for i, n in enumerate(liked)}
    facts["diet_style"] = (rng.choice(["vegetarian", "non_veg"]), "fd")
    goals = set()
    streak = {}
    if rng.random() < 0.6:
        goals.add("fried")
    if rng.random() < 0.4:
        goals.add("sugar")
        streak["sugar"] = 6  # an earned treat is available
    promises = {}
    if rng.random() < 0.5:
        promises["study"] = [{"text": "study before sleep", "status": "open", "closed": None}]
    return facts, goals, streak, promises, rng.uniform(1.0, 1.5)


def _ctx(persona, weights):
    facts, goals, streak, promises, fried_rank = persona
    return {"day": 1, "facts": facts, "goals": goals, "streak": streak, "promises": promises,
            "rank": {"fried": fried_rank}, "weights": weights}


def _fork(rng):
    pool = list(decide.CATALOGUE)
    names = rng.sample(pool, rng.choice([2, 3, 4]))
    return decide.resolve(names + (["skip"] if rng.random() < 0.15 else []))


def _tradeoff_fork(rng, persona):
    ctx = _ctx(persona, {})
    pool = []
    for name in decide.CATALOGUE:
        feats = decide.decide_with(ctx, decide.resolve([name]))["features"].get(name)
        if feats and any(feats.values()):
            pool.append(name)
    if len(pool) < 3:
        return _fork(rng)
    return decide.resolve(rng.sample(pool, min(len(pool), rng.choice([2, 3, 4]))))


def simulate_user(seed, n=60, level="moderate"):
    """One simulated person. Returns per-decision records for the learned and fixed agents."""
    rng = random.Random(seed)
    persona = _persona(rng)
    hidden = {r: rng.uniform(*LEVELS[level]) for r in decide.LEARNABLE}
    learned, records = {}, []
    for _ in range(n):
        options = _tradeoff_fork(rng, persona)
        truth = decide.decide_with(_ctx(persona, hidden), options)
        fixed = decide.decide_with(_ctx(persona, {}), options)
        mine = decide.decide_with(_ctx(persona, learned), options)
        best = truth["scores"].get(truth["pick"], 0)
        gap = best - truth["scores"].get(mine["pick"], 0)
        ok = mine["pick"] == truth["pick"]
        result = "good" if ok else ("bad" if gap >= 1 else "mixed")
        records.append({
            "learned_ok": ok,
            "fixed_ok": fixed["pick"] == truth["pick"],
            "learned_regret": 0.0 if ok else gap,
            "fixed_regret": 0.0 if fixed["pick"] == truth["pick"]
            else best - truth["scores"].get(fixed["pick"], 0)})
        alt = learn.runner_up(mine["scores"], mine["pick"])
        if alt is not None and mine["pick"] in mine["features"]:
            learned = learn.update(learned, mine["features"][mine["pick"]],
                                   mine["features"][alt], result)
    return records


def run(level="moderate", n_users=100, n=60, first_seed=1000):
    users = [simulate_user(first_seed + i, n, level) for i in range(n_users)]
    rows = []
    for lo, hi in WINDOWS:
        window = [r for u in users for r in u[lo:hi]]
        k = len(window)
        rows.append({"window": f"{lo + 1}-{hi}", "n": k,
                     "fixed_ok": sum(r["fixed_ok"] for r in window),
                     "learned_ok": sum(r["learned_ok"] for r in window),
                     "fixed_regret": sum(r["fixed_regret"] for r in window) / k,
                     "learned_regret": sum(r["learned_regret"] for r in window) / k})
    return {"level": level, "range": LEVELS[level], "users": n_users, "decisions_each": n,
            "windows": rows}


def run_all(**kw):
    return [run(level, **kw) for level in LEVELS]


def to_markdown(results):
    first = results[0]
    lines = [f"{first['users']} simulated users per population, {first['decisions_each']} trade-off "
             "decisions each. Each user has hidden preference weights; the agent only sees "
             "good / mixed / bad feedback and learns from bad outcomes. 'Agrees' = picks the "
             "option the user's hidden weights rank first.", "",
             "| Users | Decisions | Fixed weights agree | Learned weights agree | "
             "Fixed regret | Learned regret |", "|---|---|---|---|---|---|"]
    for res in results:
        for w in res["windows"]:
            lines.append(f"| {res['level']} ({res['range'][0]}-{res['range'][1]}) | {w['window']} | "
                         f"{w['fixed_ok']} of {w['n']} ({100 * w['fixed_ok'] / w['n']:.1f}%) | "
                         f"{w['learned_ok']} of {w['n']} ({100 * w['learned_ok'] / w['n']:.1f}%) | "
                         f"{w['fixed_regret']:.2f} | {w['learned_regret']:.2f} |")
    lines += ["", "Regret is the hidden-score gap between the user's best option and the agent's pick "
              "(0 when it agrees). The multiplier range in brackets is how far the hidden user's "
              "weights stray from the defaults (1.0)."]
    return "\n".join(lines)
