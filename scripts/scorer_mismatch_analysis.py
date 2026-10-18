"""Why does the trained scorer disagree with the rules? Classify every disagreement on the test seeds.

    python scripts/scorer_mismatch_analysis.py

Needs the cache written by `python run_eval.py --set scorer`. A "tie" disagreement is one where the
rules gave the two picked options the same score: the rules then pick the first listed option, and
a model that only sees features (not list order) cannot know that.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent import scorer  # noqa: E402
from eval import scorer_eval  # noqa: E402

F = {name: i for i, name in enumerate(scorer.FEATURES)}


def rule_score(x):
    """The rule table's score for an option, rebuilt from its feature vector."""
    return (5 * x[F["rule_sugar_earned"]] + 2 * x[F["rule_likes"]] + 1 * x[F["rule_healthy"]]
            - 3 * x[F["fried_goal_x_rank"]] + 3 * x[F["rule_promise"]])


def classify(model, data):
    kinds = {"tie under the rules": 0, "a real score difference": 0}
    total = 0
    for q in data:
        snap = q["readers"]["guarded"]
        mine = scorer_eval.scorer_pick(model, snap)
        if mine == snap["rules_pick"] or mine == "none":
            continue
        total += 1
        score = dict(zip(snap["names"], map(rule_score, snap["X"])))
        if abs(score[mine] - score[snap["rules_pick"]]) < 1e-9:
            kinds["tie under the rules"] += 1
        else:
            kinds["a real score difference"] += 1
    return total, kinds


def main():
    train = scorer_eval.collect(scorer_eval.TRAIN)
    val_from = scorer_eval.VAL_FROM
    # design decisions may only look at validation questions: a model fit on seeds below 250
    # is analysed on seeds 250-299, which no choice about the test seeds has ever used
    model = scorer.new_model("pairwise")
    model.fit(*scorer_eval._xy([q for q in train if q["seed"] < val_from], "pairwise"))
    val = [q for q in train if q["seed"] >= val_from]
    print(f"VALIDATION seeds {val_from}-299 ({len(val)} questions), pairwise model fit on seeds < {val_from}")
    total, kinds = classify(model, val)
    print(f"  {total} disagreements with the rules")
    for k, v in kinds.items():
        print(f"    {v:4d}  {k}")
    if "--test" in sys.argv:   # only for the write-up, never for choices
        models, info = scorer_eval.train(train)
        total, kinds = classify(models[info["kind"]], scorer_eval.collect(scorer_eval.TEST))
        print(f"TEST seeds 300-499: {total} disagreements")
        for k, v in kinds.items():
            print(f"    {v:4d}  {k}")


if __name__ == "__main__":
    main()
