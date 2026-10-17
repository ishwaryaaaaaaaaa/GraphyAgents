"""Development sweep for the learning rule. Tunes on seeds 0-99; results are REPORTED on 1000+.

    python scripts/learning_sweep.py

Findings recorded here so agent/learn.py is a documented decision, not a guess:
  1. Updating on every outcome ("symmetric": reinforce good picks too) makes weights drift and
     HURTS accuracy, because easy correct picks keep inflating whichever rules favoured them.
  2. Learning from mistakes only (bad outcomes, perceptron style) never hurts.
  3. How much it helps depends on how far the person is from the default weights, and on the
     learning rate; the sweep below measures both.
"""
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent import decide, learn  # noqa: E402
from eval import learning  # noqa: E402

LEVELS = {"mild": (0.6, 1.6), "moderate": (0.3, 2.2), "strong": (0.05, 3.0)}


def tradeoff_fork(rng, persona):
    return learning._tradeoff_fork(rng, persona)


def run(policy, level, lr, seeds, n=60, lo=0.05, hi=3.0):
    learn.LO, learn.HI = lo, hi
    wins, fixed = [[0, 0] for _ in range(3)], [0, 0, 0]
    for seed in seeds:
        rng = random.Random(seed)
        persona = learning._persona(rng)
        hidden = {r: rng.uniform(*LEVELS[level]) for r in decide.LEARNABLE}
        learned = {}
        for i in range(n):
            options = tradeoff_fork(rng, persona)
            truth = decide.decide_with(learning._ctx(persona, hidden), options)
            fx = decide.decide_with(learning._ctx(persona, {}), options)
            mine = decide.decide_with(learning._ctx(persona, learned), options)
            w = i // 20
            wins[w][0] += mine["pick"] == truth["pick"]
            wins[w][1] += 1
            fixed[w] += fx["pick"] == truth["pick"]
            gap = truth["scores"].get(truth["pick"], 0) - truth["scores"].get(mine["pick"], 0)
            result = "good" if mine["pick"] == truth["pick"] else ("bad" if gap >= 1 else "mixed")
            if policy == "mistake_only" and result != "bad":
                continue
            alt = learn.runner_up(mine["scores"], mine["pick"])
            if alt is not None and mine["pick"] in mine["features"]:
                learned = learn.update(learned, mine["features"][mine["pick"]],
                                       mine["features"][alt], result, lr=lr)
    pct = lambda a, b: f"{100 * a / b:.1f}"  # noqa: E731
    return ([pct(a, b) for a, b in wins], [pct(f, wins[i][1]) for i, f in enumerate(fixed)])


if __name__ == "__main__":
    seeds = range(0, 100)
    print("dev seeds 0-99, trade-off forks; accuracy % per 20-decision window\n")
    print(f"{'users':9} {'policy':13} {'lr':>5}  learned (w1, w2, w3)        fixed (w1, w2, w3)")
    for level in LEVELS:
        for policy, lr in (("symmetric", 0.15), ("mistake_only", 0.15), ("mistake_only", 0.3),
                           ("mistake_only", 0.5)):
            learned, fixed = run(policy, level, lr, seeds)
            print(f"{level:9} {policy:13} {lr:>5}  {learned}   {fixed}")
        print()
