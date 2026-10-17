"""Learning from outcomes: procedural memory.

After advice, the user says how it went (good, mixed, bad). The agent compares the option it
picked with the runner-up, using the feature snapshot stored on the Decision at the time, and
nudges that user's multiplier for each soft rule. It learns from MISTAKES only (perceptron style):

    bad    the runner-up would have been better: move toward what the runner-up had
           mult[r] += LR * (feature_runner_up[r] - feature_pick[r])
    good / mixed   record the outcome, change nothing

Why mistakes only: reinforcing good outcomes too was tried (scripts/learning_sweep.py) and made
accuracy WORSE, because easy correct picks keep inflating whichever rules happened to favour
them. LR was chosen on development seeds 0-99; results are reported on seeds 1000+.

Multipliers are clamped to [LO, HI]. Hard rules (diet, dislikes, availability, sugar streak)
are safety checks and are never learned. Every change is an edge Outcome -[ADJUSTED]-> Weight,
so "why does it weigh this for me?" has an answer in the graph. No model is fine-tuned.
"""
from agent import decide, store, tools

LR = 0.3
LO, HI = 0.05, 3.0


def runner_up(scores, pick):
    """Best-scoring option other than the pick (first listed wins a tie), or None."""
    others = [(name, s) for name, s in scores.items() if name != pick]
    if not others:
        return None
    return max(others, key=lambda kv: kv[1])[0]  # max() keeps the first of equal maxima


def deltas(f_pick, f_alt, result, lr=None):
    """Per-rule multiplier change for one outcome. Empty unless the outcome was bad."""
    lr = LR if lr is None else lr
    if result != "bad":
        return {}
    raw = {r: lr * (f_alt.get(r, 0.0) - f_pick.get(r, 0.0)) for r in decide.LEARNABLE}
    return {r: d for r, d in raw.items() if d}


def clamp(x):
    return max(LO, min(HI, x))


def update(mults, f_pick, f_alt, result, lr=None):
    """Pure: new multiplier dict after one outcome (rules not mentioned stay at 1.0)."""
    out = dict(mults)
    for rule, d in deltas(f_pick, f_alt, result, lr).items():
        out[rule] = clamp(out.get(rule, 1.0) + d)
    return out


def apply_outcome(user, decision_id, result, day, note=""):
    """Record the outcome in the graph and move this user's weights. Returns what changed."""
    dec = tools.get_decision(user, decision_id)
    if dec is None:
        raise KeyError(f"no decision {decision_id}")
    outcome_id = tools.record_outcome(user, decision_id, result, day, note)
    changes = []
    alt = runner_up(dec["scores"], dec["pick"])
    if dec["pick"] in dec["features"] and alt is not None:
        current = tools.get_weights(user)
        for rule, d in deltas(dec["features"][dec["pick"]], dec["features"][alt], result).items():
            old = current.get(rule, 1.0)
            new = clamp(old + d)
            if new != old:
                store.set_weight(user, rule, new, outcome_id, round(new - old, 4))
                changes.append({"rule": rule, "old": round(old, 3), "new": round(new, 3)})
    return {"outcome_id": outcome_id, "against": alt, "changes": changes}
