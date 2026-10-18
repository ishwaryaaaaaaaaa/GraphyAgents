"""Train the scorer on seeds 0-299 and compare it with the rules on seeds 300-499.

Six arms, one per (memory read, decider):

                      rules        trained scorer
  guarded memory      A            B
  first-write read    D            C          (the four main arms are A, B, C, D)
  last-write-wins     -            -          (extra rows)

B and C use the same model: only the memory read differs. If C is much worse than B, a smart model
fed stale facts still decides wrongly, so memory correctness matters more than model choice.

Rules of the experiment, fixed before training:
  * the model is fit on seeds 0-299 only, using the GUARDED view and the oracle's answer as label;
  * logistic regression vs gradient boosting is decided on a validation split inside the training
    seeds (0-249 fit, 250-299 validate), never on the test seeds;
  * accuracy is reported on seeds 300-499 only, split by trap vs no trap and by held-out foods
    (items that never appear in a training life).
"""
import hashlib
import pickle
import sys
from pathlib import Path

from agent import decide, scorer, store
from data import generator
from eval import baseline, replay
from eval.metrics import wilson

CACHE = Path(__file__).resolve().parent.parent / ".cache"
READERS = ("guarded", "first_write", "last_write_wins")
TRAIN, TEST = range(0, 300), range(300, 500)
VAL_FROM = 250
BOOSTING_MARGIN = 0.01   # boosting must beat logistic regression by a point on validation


def _contexts(user, step, options):
    day = step["day"]
    out = {"guarded": decide.build_context(user, day, options)}
    for name, reader in (("first_write", baseline.first_write_facts),
                         ("last_write_wins", baseline.last_write_wins_facts)):
        out[name] = decide.build_context(user, day, options, facts=reader(user),
                                         goal_tags=baseline.all_goal_tags(user))
    return out


def _snapshot(user, step, options):
    snap = {}
    for reader, ctx in _contexts(user, step, options).items():
        base, rows = scorer.allowed_rows(ctx, options)
        snap[reader] = {"rules_pick": base["pick"], "names": [o["name"] for o, _ in rows],
                        "X": [x for _, x in rows]}
    return snap


def collect(seeds, use_cache=True):
    """One record per question: the features each reader gives every allowed option."""
    tag = hashlib.md5(",".join(scorer.FEATURES).encode()).hexdigest()[:8]  # new features, new cache
    path = CACHE / f"scorer_{tag}_{seeds.start}-{seeds[-1]}.pkl"
    if use_cache and path.exists():
        return pickle.loads(path.read_bytes())
    data = []
    for i, seed in enumerate(seeds):
        user, captured = f"scr{seed}", []
        try:
            run = replay.replay(user, generator.generate(seed)["steps"],
                                observer=lambda u, s, o: captured.append(_snapshot(u, s, o)))
        finally:
            store.reset(user)
        for snap, ask in zip(captured, run["asks"]):
            data.append({"seed": seed, "id": ask["id"], "trap": ask["trap"],
                         "heldout": ask["heldout"], "expect": ask["expect"], "readers": snap})
        if (i + 1) % 25 == 0:
            print(f"  collected {i + 1}/{len(seeds)} lives", file=sys.stderr)
    CACHE.mkdir(exist_ok=True)
    path.write_bytes(pickle.dumps(data))
    return data


def scorer_pick(model, snap):
    if not snap["names"]:
        return "none"
    s = scorer.scores_of(model, snap["X"])
    return snap["names"][max(range(len(s)), key=lambda i: (s[i], -i))]


def accuracy(model, data, reader="guarded"):
    return sum(scorer_pick(model, q["readers"][reader]) == q["expect"] for q in data) / len(data)


def _xy(data, kind):
    """Training rows. Pointwise: one 0/1 label per option. Pairwise: for the right option and each
    other allowed option, the feature difference (label 1) and its negation (label 0)."""
    X, y = [], []
    for q in data:
        snap = q["readers"]["guarded"]
        if kind == "pairwise":
            if q["expect"] not in snap["names"]:
                continue
            i = snap["names"].index(q["expect"])
            for j, other in enumerate(snap["X"]):
                if j == i:
                    continue
                diff = [a - b for a, b in zip(snap["X"][i], other)]
                X += [diff, [-d for d in diff]]
                y += [1, 0]
        else:
            for name, x in zip(snap["names"], snap["X"]):
                X.append(x)
                y.append(int(name == q["expect"]))
    return X, y


def train(data, val_from=VAL_FROM):
    """Pick the model type on a validation split inside the training seeds, then refit every type
    on all training questions. Preference order on a tie: pairwise, logistic, boosting; boosting
    must beat the best linear model by a point to be chosen."""
    fit = [q for q in data if q["seed"] < val_from]
    val = [q for q in data if q["seed"] >= val_from]
    validation = {}
    for kind in scorer.KINDS:
        model = scorer.new_model(kind)
        model.fit(*_xy(fit, kind))
        validation[kind] = accuracy(model, val)
    linear = max(("pairwise", "logistic"), key=lambda k: (validation[k], k == "pairwise"))
    kind = "boosting" if validation["boosting"] - validation[linear] >= BOOSTING_MARGIN else linear
    models = {}
    for k in scorer.KINDS:
        models[k] = scorer.new_model(k)
        models[k].fit(*_xy(data, k))
    rows = len(_xy(data, "logistic")[1])
    info = {"kind": kind, "validation": validation, "train_questions": len(data),
            "train_rows": rows, "val_questions": len(val),
            "weights": scorer.weights(models["pairwise"] if kind == "pairwise" else models["logistic"]),
            "weights_of": "pairwise" if kind == "pairwise" else "logistic"}
    return models, info


def _rate(k, n):
    lo, hi = wilson(k, n)
    return {"k": k, "n": n, "pct": round(100 * k / n, 1) if n else None,
            "ci": [round(100 * lo, 1), round(100 * hi, 1)]}


def evaluate(models, info, data):
    """models: every trained kind; info["kind"] is the one chosen on validation (arm B and C)."""
    model = models[info["kind"]]
    arms = {}
    for reader in READERS:
        arms[f"{reader}/rules"] = [q["readers"][reader]["rules_pick"] == q["expect"] for q in data]
        arms[f"{reader}/scorer"] = [scorer_pick(model, q["readers"][reader]) == q["expect"]
                                    for q in data]
    slices = {
        "all questions": lambda q: True,
        "stale-memory traps": lambda q: q["trap"] != "none",
        "no trap": lambda q: q["trap"] == "none",
        "involve a held-out food": lambda q: q["heldout"],
        "only foods seen in training": lambda q: not q["heldout"],
    }
    out = {"questions": len(data), "arms": {}, "slices": {}, "chosen": info["kind"],
           "models_compared": {k: _rate(sum(scorer_pick(m, q["readers"]["guarded"]) == q["expect"]
                                            for q in data), len(data)) for k, m in models.items()}}
    for arm, oks in arms.items():
        out["arms"][arm] = _rate(sum(oks), len(oks))
    for name, keep in slices.items():
        idx = [i for i, q in enumerate(data) if keep(q)]
        out["slices"][name] = {arm: _rate(sum(oks[i] for i in idx), len(idx))
                               for arm, oks in arms.items()
                               if arm in ("guarded/rules", "guarded/scorer", "first_write/scorer")}
    rules, mine = arms["guarded/rules"], arms["guarded/scorer"]
    rule_picks = [q["readers"]["guarded"]["rules_pick"] for q in data]
    scorer_picks = [scorer_pick(model, q["readers"]["guarded"]) for q in data]
    out["scorer_vs_rules"] = {
        "differ": sum(a != b for a, b in zip(rule_picks, scorer_picks)),
        "scorer_right_rules_wrong": sum(b and not a for a, b in zip(rules, mine)),
        "rules_right_scorer_wrong": sum(a and not b for a, b in zip(rules, mine)),
        "both_wrong_differently": sum(not a and not b and x != y for a, b, x, y
                                      in zip(rules, mine, rule_picks, scorer_picks)),
    }
    return out


LABELS = {"guarded/rules": "A: guarded memory, rules", "guarded/scorer": "B: guarded memory, scorer",
          "first_write/scorer": "C: first-write read, scorer",
          "first_write/rules": "D: first-write read, rules",
          "last_write_wins/rules": "last-write-wins read, rules",
          "last_write_wins/scorer": "last-write-wins read, scorer"}
ORDER = ["guarded/rules", "guarded/scorer", "first_write/scorer", "first_write/rules",
         "last_write_wins/scorer", "last_write_wins/rules"]


def _cell(r):
    return f"{r['k']} of {r['n']} ({r['pct']}%)"


def to_markdown(res, info):
    v = info["validation"]
    lines = [
        f"Model for arms B and C: **{info['kind']}**, chosen on a validation split inside the training "
        f"seeds ({info['val_questions']} validation questions: " +
        ", ".join(f"{k} {100 * v[k]:.1f}%" for k in scorer.KINDS) + "). "
        f"Trained on seeds 0-299 ({info['train_questions']} questions, {info['train_rows']} option rows). "
        f"Evaluated on seeds 300-499 ({res['questions']} questions), never used for any choice.", "",
        "| Arm | Task success (95% interval) |", "|---|---|"]
    for arm in ORDER:
        r = res["arms"][arm]
        lines.append(f"| {LABELS[arm]} | {_cell(r)} [{r['ci'][0]}-{r['ci'][1]}] |")
    lines += ["", "By kind of question (task success):", "",
              "| Slice | A: guarded, rules | B: guarded, scorer | C: first-write, scorer |",
              "|---|---|---|---|"]
    for name, row in res["slices"].items():
        lines.append(f"| {name} | {_cell(row['guarded/rules'])} | {_cell(row['guarded/scorer'])} | "
                     f"{_cell(row['first_write/scorer'])} |")
    d = res["scorer_vs_rules"]
    lines += ["", f"With guarded memory the scorer and the rules picked different options on {d['differ']} "
              f"questions: the scorer was right and the rules wrong on {d['scorer_right_rules_wrong']}, "
              f"the rules right and the scorer wrong on {d['rules_right_scorer_wrong']}, "
              f"and both wrong in different ways on {d['both_wrong_differently']}."]
    lines += ["", "All three model types on the same test questions (guarded memory). The first version "
              "of this experiment had only the pointwise models; the pairwise ranking model was added "
              "after seeing that they cannot express \"better than the alternatives\", and the choice "
              "between all three is made on the validation seeds only:", "",
              "| Model | Task success (95% interval) |", "|---|---|"]
    for k, r in res["models_compared"].items():
        mark = " (chosen on validation)" if k == res["chosen"] else ""
        lines.append(f"| {k}{mark} | {_cell(r)} [{r['ci'][0]}-{r['ci'][1]}] |")
    if info["weights"]:
        top = list(info["weights"].items())[:8]
        lines += ["", f"Largest weights of the {info['weights_of']} model (what it learned to like; "
                  "a positive weight pushes an option up):", "", "| Feature | Weight |", "|---|---|"]
        lines += [f"| {k} | {w:+.2f} |" for k, w in top]
    return "\n".join(lines) + "\n"


def run(use_cache=True):
    train_data = collect(TRAIN, use_cache)
    models, info = train(train_data)
    scorer.save(models[info["kind"]], meta={"kind": info["kind"], "validation": info["validation"]})
    res = evaluate(models, info, collect(TEST, use_cache))
    return res, info
