"""A small trained model that ranks the options the hard rules allow.

What it is: a small model (a ranking logistic regression, a pointwise logistic regression or gradient
boosting, whichever a validation split prefers) that gives each option a number from its features;
the highest number wins.
The hard rules (diet, dislikes, availability, sugar streak) still run first as safety checks, so
the model only ever ranks what is allowed: a learned model can never make a vegetarian eat meat.

The graph supplies the features through the same context the rule engine reads, so a stale read
gives the model stale features. That is the experiment in eval/scorer_eval.py: the same model
with guarded versus unguarded memory.

Not used as features, on purpose: whether an item was held out of training (meaningless to learn),
and history features such as "times chosen in the last 14 days" (generated lives hold no pick history).
"""
from pathlib import Path

from agent import decide

MODEL_PATH = Path(__file__).resolve().parent.parent / "models" / "scorer.joblib"

TAGS = ("meat", "fried", "sugar", "healthy", "snack", "meal", "dessert")
FEATURES = (
    # the five soft rules, as 0/1 (the same signals the rule table uses)
    "rule_likes", "rule_healthy", "rule_fried_goal", "rule_sugar_earned", "rule_promise",
    # what the option is
    *(f"tag_{t}" for t in TAGS), "is_activity", "is_skip",
    # context the rules only use implicitly
    "sugar_streak", "goal_rank", "n_options", "fried_goal_x_rank",
    # where the option was listed among those allowed: the rules break exact ties by "first listed",
    # which no feature of the option itself can express (found by scripts/scorer_mismatch_analysis.py
    # on the validation seeds: 66 of 67 disagreements with the rules were ties)
    "list_position",
)
ACTIVITY_TAGS = {"study", "leisure", "exercise", "social"}


def featurize(ctx, opt, rule_feats, n_options, position=0):
    """One option's feature vector, in FEATURES order. `position` is its place (0 = first) among
    the options that passed the hard rules."""
    tags = set(opt["tags"])
    sugar_on = "sugar" in tags and "sugar" in ctx["goals"]
    goal_rank = max([ctx["rank"].get(t, 1.0) for t in tags if t in ctx["goals"]], default=0.0)
    row = {
        "rule_likes": rule_feats["likes"], "rule_healthy": rule_feats["healthy"],
        "rule_fried_goal": rule_feats["fried"], "rule_sugar_earned": rule_feats["sugar_earned"],
        "rule_promise": rule_feats["promise"],
        "is_activity": float(bool(tags & ACTIVITY_TAGS)), "is_skip": float(opt["name"] == "skip"),
        "sugar_streak": min(ctx["streak"].get("sugar", 0), 10) / 10 if sugar_on else 0.0,
        "goal_rank": goal_rank, "n_options": n_options / 5,
        "fried_goal_x_rank": rule_feats["fried"] * goal_rank,  # the rule scales the penalty by rank
        "list_position": min(position, 4) / 4,
    }
    row.update({f"tag_{t}": float(t in tags) for t in TAGS})
    return [float(row[f]) for f in FEATURES]


def allowed_rows(ctx, options):
    """Run the rule engine for the hard rules and the 0/1 rule features; return
    (result, [(option, feature vector)]) for the options that survive."""
    base = decide.decide_with(ctx, options)
    allowed = [o for o in options if o["name"] in base["features"]]
    rows = [(o, featurize(ctx, o, base["features"][o["name"]], len(options), position=i))
            for i, o in enumerate(allowed)]
    return base, rows


KINDS = ("pairwise", "logistic", "boosting")


def new_model(kind="logistic"):
    """pairwise  logistic regression trained on feature DIFFERENCES between the right option and each
                 other option, no intercept: a ranking model whose score is just w . features
       logistic  logistic regression trained on one 0/1 label per option (a pointwise classifier)
       boosting  gradient boosted trees on the same pointwise labels"""
    if kind == "boosting":
        from sklearn.ensemble import GradientBoostingClassifier
        return GradientBoostingClassifier(random_state=0)
    from sklearn.linear_model import LogisticRegression
    return LogisticRegression(max_iter=2000, C=1.0, random_state=0,
                              fit_intercept=(kind != "pairwise"))


def scores_of(model, X):
    return model.decision_function(X) if hasattr(model, "decision_function") else \
        model.predict_proba(X)[:, 1]


def decide_with_scorer(ctx, options, model):
    """Same output shape as decide.decide_with, ranked by the model after the hard rules."""
    base, rows = allowed_rows(ctx, options)
    if not rows:
        return {**base, "mode": "scorer"}
    scores = scores_of(model, [x for _, x in rows])
    best = max(range(len(rows)), key=lambda i: (scores[i], -i))  # first listed wins a tie
    pick = rows[best][0]["name"]
    feats = base["features"][pick]
    return {
        **base, "pick": pick, "mode": "scorer",
        "scores": {o["name"]: float(s) for (o, _), s in zip(rows, scores)},
        "rules_fired": [r for r in decide.LEARNABLE if feats[r]],
        "reasons": list(dict.fromkeys(list(base["rejected"].values()) + ["the learned scorer's choice"])),
        "earned_treat": pick if feats["sugar_earned"] else None,
    }


def weights(model):
    """Readable coefficients for a logistic regression, largest first; {} for other models."""
    if not hasattr(model, "coef_"):
        return {}
    return dict(sorted(zip(FEATURES, (float(c) for c in model.coef_[0])), key=lambda kv: -abs(kv[1])))


def save(model, meta=None, path=MODEL_PATH):
    import joblib
    path.parent.mkdir(exist_ok=True)
    joblib.dump({"model": model, "features": FEATURES, "meta": meta or {}}, path)


def load(path=MODEL_PATH):
    import joblib
    if not path.exists():
        raise FileNotFoundError(f"{path} not found: run `python run_eval.py --set scorer` to train it")
    blob = joblib.load(path)
    if tuple(blob["features"]) != FEATURES:
        raise RuntimeError("the saved scorer was trained on different features: retrain it")
    return blob["model"]
