"""The trained scorer: features, the hard rules that always come first, the model plumbing, and the
evaluation harness (with stub models, so these tests do not depend on how training turns out)."""
import pytest

from agent import decide, scorer, store, tools
from eval import scorer_eval


class Stub:
    """A model whose score for an option is a function of its feature vector."""
    def __init__(self, fn):
        self.fn = fn

    def decision_function(self, X):
        return [self.fn(dict(zip(scorer.FEATURES, x))) for x in X]


def ctx(facts=None, goals=(), streak=None, promises=None, rank=None):
    return {"day": 10, "facts": facts or {}, "goals": set(goals), "streak": streak or {},
            "promises": promises or {}, "rank": rank or {}, "weights": {}}


def run(model, names, **kw):
    return scorer.decide_with_scorer(ctx(**kw), decide.resolve(names), model)


# ---- features ----

def test_a_feature_vector_has_one_number_per_feature_and_names_the_option():
    c = ctx(facts={"likes:samosa": ("yes", "f1")}, goals=["fried"], rank={"fried": 1.4})
    options = decide.resolve(["samosa", "chana_chaat", "skip"])
    base, rows = scorer.allowed_rows(c, options)
    by = {o["name"]: dict(zip(scorer.FEATURES, x)) for o, x in rows}
    assert all(len(x) == len(scorer.FEATURES) for _, x in rows)
    assert by["samosa"]["rule_likes"] == 1 and by["samosa"]["rule_fried_goal"] == 1
    assert by["samosa"]["tag_fried"] == 1 and by["samosa"]["goal_rank"] == pytest.approx(1.4)
    assert by["chana_chaat"]["rule_healthy"] == 1 and by["chana_chaat"]["tag_healthy"] == 1
    assert by["skip"]["is_skip"] == 1 and by["samosa"]["is_skip"] == 0
    assert by["samosa"]["n_options"] == pytest.approx(3 / 5)
    assert [by[n]["list_position"] for n in ("samosa", "chana_chaat", "skip")] == [0.0, 0.25, 0.5]


def test_list_position_counts_only_options_that_passed_the_hard_rules():
    c = ctx(facts={"diet_style": ("vegetarian", "f1")})
    _, rows = scorer.allowed_rows(c, decide.resolve(["fried_chicken", "pasta", "samosa"]))
    by = {o["name"]: dict(zip(scorer.FEATURES, x))["list_position"] for o, x in rows}
    assert by == {"pasta": 0.0, "samosa": 0.25}      # the rejected meat dish takes no place


def test_activities_and_the_sugar_streak_are_visible_to_the_model():
    c = ctx(goals=["sugar"], streak={"sugar": 5})
    _, rows = scorer.allowed_rows(c, decide.resolve(["gulab_jamun", "study_session"]))
    by = {o["name"]: dict(zip(scorer.FEATURES, x)) for o, x in rows}
    assert by["study_session"]["is_activity"] == 1 and by["gulab_jamun"]["is_activity"] == 0
    assert by["gulab_jamun"]["sugar_streak"] == pytest.approx(0.5)
    assert by["gulab_jamun"]["rule_sugar_earned"] == 1 and by["study_session"]["sugar_streak"] == 0


# ---- the hard rules still come first ----

def test_a_model_can_never_pick_what_the_hard_rules_reject():
    loves_meat = Stub(lambda f: 100 * f["tag_meat"] + f["rule_healthy"])
    c = dict(facts={"diet_style": ("vegetarian", "f1")})
    r = run(loves_meat, ["fried_chicken", "chana_chaat"], **c)
    assert r["pick"] == "chana_chaat" and r["rejected"] == {"fried_chicken": "you are vegetarian"}
    r = run(loves_meat, ["fried_chicken", "chana_chaat"])             # no diet fact: meat is allowed
    assert r["pick"] == "fried_chicken"


def test_everything_rejected_gives_none_and_a_short_sugar_streak_still_blocks_sugar():
    anything = Stub(lambda f: 1.0)
    veg = {"diet_style": ("vegetarian", "f1")}
    assert run(anything, ["fried_chicken", "chicken_curry"], facts=veg)["pick"] == "none"
    r = run(Stub(lambda f: 10 * f["tag_sugar"]), ["gulab_jamun", "skip"], goals=["sugar"],
            streak={"sugar": 2})
    assert r["pick"] == "skip" and r["rejected"] == {"gulab_jamun": "only 2 of 5 days"}


def test_the_model_decides_among_the_allowed_and_ties_go_to_the_first_listed():
    prefers_healthy = Stub(lambda f: f["rule_healthy"])
    assert run(prefers_healthy, ["pasta", "chana_chaat"])["pick"] == "chana_chaat"
    flat = Stub(lambda f: 0.0)
    assert run(flat, ["pasta", "masala_dosa"])["pick"] == "pasta"
    assert run(flat, ["masala_dosa", "pasta"])["pick"] == "masala_dosa"


def test_the_result_has_the_same_shape_as_the_rule_engines_and_records_the_mode():
    r = run(Stub(lambda f: f["rule_sugar_earned"]), ["gulab_jamun", "skip"], goals=["sugar"],
            streak={"sugar": 6})
    assert r["mode"] == "scorer" and r["pick"] == "gulab_jamun" and r["earned_treat"] == "gulab_jamun"
    assert r["rules_fired"] == ["sugar_earned"] and "the learned scorer's choice" in r["reasons"]
    for key in ("pick", "reasons", "rejected", "used_fact_ids", "scores", "features", "earned_treat"):
        assert key in r


# ---- plumbing ----

def test_training_is_deterministic_and_the_model_round_trips(tmp_path):
    X = [[0.0] * len(scorer.FEATURES) for _ in range(40)]
    for i, row in enumerate(X):
        row[1] = float(i % 2)
    y = [i % 2 for i in range(40)]
    a, b = scorer.new_model(), scorer.new_model()
    a.fit(X, y)
    b.fit(X, y)
    assert list(scorer.scores_of(a, X)) == list(scorer.scores_of(b, X))
    path = tmp_path / "m.joblib"
    scorer.save(a, meta={"kind": "logistic"}, path=path)
    assert list(scorer.scores_of(scorer.load(path), X)) == list(scorer.scores_of(a, X))
    assert next(iter(scorer.weights(a))) == "rule_healthy"           # the only informative feature


def test_the_pairwise_model_learns_which_option_beats_the_others():
    """Pointwise labels cannot say 'better than the alternatives'; differences can."""
    names = scorer.FEATURES
    like, healthy = names.index("rule_likes"), names.index("rule_healthy")
    data = []
    for i in range(60):   # the liked option always beats the healthy one in these made-up questions
        a, b = [0.0] * len(names), [0.0] * len(names)
        a[like], b[healthy] = 1.0, 1.0
        data.append({"seed": i, "expect": "a", "readers": {"guarded": {"names": ["a", "b"],
                                                                      "X": [a, b]}}})
    X, y = scorer_eval._xy(data, "pairwise")
    assert len(X) == 120 and sorted(set(y)) == [0, 1]
    model = scorer.new_model("pairwise")
    model.fit(X, y)
    assert model.intercept_[0] == 0.0
    assert scorer_eval.accuracy(model, data) == 1.0
    w = scorer.weights(model)
    assert w["rule_likes"] > 0 > w["rule_healthy"]
    assert scorer.weights(scorer.new_model("boosting")) == {}        # no readable weights for trees


def test_a_missing_or_mismatched_model_is_reported_clearly(tmp_path, monkeypatch):
    with pytest.raises(FileNotFoundError, match="run_eval.py --set scorer"):
        scorer.load(tmp_path / "nope.joblib")
    import joblib
    path = tmp_path / "old.joblib"
    joblib.dump({"model": object(), "features": ("a", "b"), "meta": {}}, path)
    with pytest.raises(RuntimeError, match="retrain"):
        scorer.load(path)


def test_decide_in_scorer_mode_uses_guarded_memory_and_records_it(user, monkeypatch):
    monkeypatch.setattr(scorer, "load", lambda path=None: Stub(lambda f: f["tag_meat"] * 10))
    store.set_fact(user, "diet_style", "non_veg", 1)
    store.set_fact(user, "diet_style", "vegetarian", 10)      # supersedes: the old value must not be used
    r = decide.decide(user, 10, ["fried_chicken", "chana_chaat"], mode="scorer")
    assert r["pick"] == "chana_chaat" and r["mode"] == "scorer"
    assert tools.explain_decision(user, r["decision_id"])["mode"] == "scorer"
    assert decide.decide(user, 10, ["fried_chicken", "chana_chaat"])["mode"] == "rules"


def test_the_chat_can_use_the_scorer_and_the_hard_rules_still_hold(user, monkeypatch):
    import cli
    monkeypatch.setenv("LLM_MODE", "off")
    monkeypatch.setattr(scorer, "load", lambda path=None: Stub(lambda f: 10 * f["tag_meat"]))
    s = cli.Session(user, day=1, auto=True, mode="scorer")
    s.handle("I turned vegetarian")
    out = s.handle("fried chicken or chana chaat?")
    assert out.startswith("chana chaat.") and "you are vegetarian" in out
    assert tools.explain_decision(user, s.last_decision["decision_id"])["mode"] == "scorer"
    assert cli.Session(user, day=1, auto=True).mode == "rules"


def test_the_real_trained_model_loads_and_ranks(tmp_path):
    """Skipped until `python run_eval.py --set scorer` has produced models/scorer.joblib."""
    if not scorer.MODEL_PATH.exists():
        pytest.skip("models/scorer.joblib not trained yet")
    model = scorer.load()
    r = run(model, ["fried_chicken", "chana_chaat"], facts={"diet_style": ("vegetarian", "f1")})
    assert r["pick"] == "chana_chaat" and r["mode"] == "scorer"
    r = run(model, ["pasta", "chana_chaat"], facts={"likes:pasta": ("yes", "f2")})
    assert r["pick"] == "pasta"           # liked (+2) beats healthy (+1), as in the rules


# ---- the evaluation harness ----

def test_collect_train_and_evaluate_run_end_to_end_on_a_few_lives(tmp_path, monkeypatch):
    monkeypatch.setattr(scorer_eval, "CACHE", tmp_path)
    data = scorer_eval.collect(range(300, 304), use_cache=False)
    assert data and set(data[0]["readers"]) == set(scorer_eval.READERS)
    q = data[0]
    assert len(q["readers"]["guarded"]["X"]) == len(q["readers"]["guarded"]["names"])
    models, info = scorer_eval.train(data, val_from=302)    # lives 300-301 fit, 302-303 validate
    assert info["kind"] in scorer.KINDS and info["train_rows"] > 0 and set(models) == set(scorer.KINDS)
    res = scorer_eval.evaluate(models, info, data)
    assert set(res["models_compared"]) == set(scorer.KINDS) and res["chosen"] == info["kind"]
    assert set(res["arms"]) == {f"{r}/{d}" for r in scorer_eval.READERS for d in ("rules", "scorer")}
    assert res["arms"]["guarded/rules"]["k"] == res["arms"]["guarded/rules"]["n"] == len(data)  # = oracle
    d = res["scorer_vs_rules"]
    assert d["differ"] == (d["scorer_right_rules_wrong"] + d["rules_right_scorer_wrong"]
                           + d["both_wrong_differently"])        # every difference is accounted for
    md = scorer_eval.to_markdown(res, info)
    assert "A: guarded memory, rules" in md and "C: first-write read, scorer" in md
    assert "pairwise" in md and "All three model types" in md
    # cached the second time
    assert scorer_eval.collect(range(300, 304)) == data
