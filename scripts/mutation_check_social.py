"""Does the social oracle catch real bugs in agent/counsel.py?

    python scripts/mutation_check_social.py [first_seed last_seed]

Injects known faults and counts disagreements with data/social_oracle.py. A mutation with 0
disagreements means the evaluation could not see that bug.
"""
import contextlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent import counsel, store, tools  # noqa: E402
from data import social_generator  # noqa: E402
from eval import social  # noqa: E402


@contextlib.contextmanager
def patched(obj, name, value):
    old = getattr(obj, name)
    setattr(obj, name, value)
    try:
        yield
    finally:
        setattr(obj, name, old)


def _no_source(user, key, day, _orig=tools.get_fact_meta):
    meta = _orig(user, key, day)
    return {**meta, "source": "typed"} if meta else meta


MUTATIONS = {
    "none (control)": contextlib.nullcontext,
    "pattern needs 2, not 3": lambda: patched(counsel, "PATTERN_MIN", 2),
    "pattern window 60 days, not 30": lambda: patched(counsel, "PATTERN_DAYS", 60),
    "anger is fresh for 0 days, not 1": lambda: patched(counsel, "FRESH_DAYS", 0),
    "own values count 1.0x, not 1.5x": lambda: patched(counsel, "VALUE_BOOST", 1.0),
    "never says 'your call'": lambda: patched(counsel, "HUMILITY_MARGIN", 0.0),
    "says 'your call' too often": lambda: patched(counsel, "HUMILITY_MARGIN", 2.5),
    "ignores how earlier advice went": lambda: patched(tools, "past_advice", lambda *a, **k: []),
    "forgets where a status came from": lambda: patched(tools, "get_fact_meta", _no_source),
    "guard removed (reads every status)": lambda: patched(tools, "_LIVE", "true"),
}


def disagreements(seeds):
    bad = 0
    for seed in seeds:
        user = f"smut{seed}"
        try:
            run = social.replay(user, social_generator.generate(seed))
        finally:
            store.reset(user)
        bad += sum(not (a["arms"]["guarded"]["verdict_ok"] and a["arms"]["guarded"]["principles_ok"])
                   for a in run)
    return bad


if __name__ == "__main__":
    lo, hi = (int(sys.argv[1]), int(sys.argv[2])) if len(sys.argv) == 3 else (2000, 2029)
    print(f"social seeds {lo}-{hi}\n")
    print(f"{'mutation':<40} disagreements")
    for name, make in MUTATIONS.items():
        with make():
            try:
                n = disagreements(range(lo, hi + 1))
            except Exception as e:  # noqa: BLE001 - a crash is also a detected fault
                n = f"crash: {type(e).__name__}"
        print(f"{name:<40} {n}")
