"""Does the oracle catch real bugs? Inject known faults into the engine and count disagreements.

    python scripts/mutation_check.py [first_seed last_seed]

A mutation that produces 0 disagreements means the evaluation could not see that bug.
"""
import contextlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent import decide, store, tools  # noqa: E402
from data import generator  # noqa: E402
from eval import replay  # noqa: E402


@contextlib.contextmanager
def rule(key, value):
    old = decide.RULES[key]
    decide.RULES[key] = value
    try:
        yield
    finally:
        decide.RULES[key] = old


@contextlib.contextmanager
def patched(obj, name, value):
    old = getattr(obj, name)
    setattr(obj, name, value)
    try:
        yield
    finally:
        setattr(obj, name, old)


MUTATIONS = {
    "none (control)": contextlib.nullcontext,
    "streak needs 4 days, not 5": lambda: rule("sugar_streak_days", 4),
    "like bonus 3, not 2": lambda: rule("likes", 3),
    "healthy bonus 0": lambda: rule("healthy", 0),
    "promise bonus 1, not 3": lambda: rule("promise", 1),
    "broken promise counts 7 days, not 3": lambda: rule("promise_recent_days", 7),
    "cascade disabled": lambda: patched(store, "cascade", lambda *a, **k: []),
    "guard removed (reads every status)": lambda: patched(tools, "_LIVE", "true"),
}


def disagreements(seeds):
    bad = 0
    for seed in seeds:
        user = f"mut{seed}"
        try:
            run = replay.replay(user, generator.generate(seed)["steps"])
        finally:
            store.reset(user)
        bad += sum(not a["arms"]["guarded"]["ok"] for a in run["asks"])
        bad += sum(not c["ok"] for c in run["cascade"]) + sum(not t["ok"] for t in run["time_travel"])
    return bad


if __name__ == "__main__":
    lo, hi = (int(sys.argv[1]), int(sys.argv[2])) if len(sys.argv) == 3 else (300, 309)
    seeds = range(lo, hi + 1)
    print(f"seeds {lo}-{hi}\n")
    print(f"{'mutation':<40} disagreements")
    for name, make in MUTATIONS.items():
        with make():
            try:
                n = disagreements(seeds)
            except AssertionError:
                n = "crash (guarded arm and agent disagree)"
        print(f"{name:<40} {n}")
