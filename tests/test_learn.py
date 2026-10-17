import pytest

import cli
from agent import decide, learn, store, tools
from eval import learning


def feats(**kw):
    return {r: kw.get(r, 0.0) for r in decide.LEARNABLE}


# ---- the pure rule ----

def test_bad_outcome_moves_toward_what_the_alternative_had():
    d = learn.deltas(feats(likes=1), feats(healthy=1), "bad", lr=0.3)
    assert d == {"likes": pytest.approx(-0.3), "healthy": pytest.approx(0.3)}


def test_good_and_mixed_outcomes_change_nothing():
    for result in ("good", "mixed"):
        assert learn.deltas(feats(likes=1), feats(healthy=1), result) == {}
        assert learn.update({"likes": 1.2}, feats(likes=1), feats(healthy=1), result) == {"likes": 1.2}


def test_rules_both_options_share_are_untouched():
    d = learn.deltas(feats(likes=1, healthy=1), feats(likes=1), "bad")
    assert set(d) == {"healthy"}


def test_multipliers_are_clamped():
    m = {}
    for _ in range(50):
        m = learn.update(m, feats(likes=1), feats(healthy=1), "bad")
    assert m["likes"] == learn.LO and m["healthy"] == learn.HI


def test_runner_up_prefers_first_listed_on_a_tie():
    assert learn.runner_up({"a": 3, "b": 1, "c": 1}, "a") == "b"
    assert learn.runner_up({"a": 3}, "a") is None


def test_weights_change_a_decision_without_touching_hard_rules():
    ctx = {"day": 1, "facts": {"likes:samosa": ("yes", "f1")}, "goals": set(), "streak": {},
           "promises": {}, "rank": {}}
    options = decide.resolve(["samosa", "chana_chaat"])
    assert decide.decide_with(ctx, options)["pick"] == "samosa"
    ctx["weights"] = {"likes": 0.3, "healthy": 2.0}
    assert decide.decide_with(ctx, options)["pick"] == "chana_chaat"
    # a learned multiplier can never make a vegetarian eat meat
    ctx["facts"]["diet_style"] = ("vegetarian", "f2")
    ctx["weights"] = {"likes": 3.0}
    out = decide.decide_with(ctx, decide.resolve(["fried_chicken", "chana_chaat"]))
    assert out["rejected"] == {"fried_chicken": "you are vegetarian"}


# ---- in the graph ----

def _ask(user, day):
    return decide.decide(user, day, ["samosa", "chana_chaat"])


def test_bad_outcomes_flip_the_advice_and_leave_an_audit_trail(user):
    store.set_fact(user, "likes:samosa", "yes", 1)
    first = _ask(user, 2)
    assert first["pick"] == "samosa"
    res = learn.apply_outcome(user, first["decision_id"], "bad", 3, "felt heavy")
    assert res["against"] == "chana_chaat"
    assert {c["rule"] for c in res["changes"]} == {"likes", "healthy"}
    w = tools.get_weights(user)
    assert w["likes"] == pytest.approx(0.7) and w["healthy"] == pytest.approx(1.3)

    second = _ask(user, 4)
    assert second["pick"] == "samosa"          # 1.4 vs 1.3: still samosa, not yet convinced
    learn.apply_outcome(user, second["decision_id"], "bad", 5)
    third = _ask(user, 6)
    assert third["pick"] == "chana_chaat"      # it learned this person does not want the samosa

    hist = tools.weight_history(user, "likes")
    assert [h["result"] for h in hist] == ["bad", "bad"]
    assert [round(h["mult"], 2) for h in hist] == [0.7, 0.4]
    assert hist[0]["outcome"] == res["outcome_id"]


def test_good_outcome_is_recorded_but_changes_no_weight(user):
    store.set_fact(user, "likes:samosa", "yes", 1)
    d = _ask(user, 2)
    res = learn.apply_outcome(user, d["decision_id"], "good", 3)
    assert res["changes"] == [] and tools.get_weights(user) == {}
    assert tools.pending_outcomes(user, 4) == []


def test_one_outcome_per_decision_and_unknown_decisions_are_rejected(user):
    store.set_fact(user, "likes:samosa", "yes", 1)
    d = _ask(user, 2)
    learn.apply_outcome(user, d["decision_id"], "good", 3)
    with pytest.raises(ValueError):
        learn.apply_outcome(user, d["decision_id"], "bad", 4)
    with pytest.raises(KeyError):
        learn.apply_outcome(user, "d999", "bad", 4)
    with pytest.raises(ValueError):
        tools.record_outcome(user, d["decision_id"], "terrible", 4)


def test_pending_outcomes_lists_unrated_earlier_decisions(user):
    store.set_fact(user, "likes:samosa", "yes", 1)
    a, b = _ask(user, 2), _ask(user, 3)
    learn.apply_outcome(user, a["decision_id"], "good", 4)
    assert [p["id"] for p in tools.pending_outcomes(user, 4)] == [b["decision_id"]]
    assert tools.pending_outcomes(user, 3) == []      # only decisions from an earlier day count
    assert [p["id"] for p in tools.pending_outcomes(user, 10)] == [b["decision_id"]]


def test_each_person_learns_separately(user):
    other = user + "_b"
    store.reset(other)
    try:
        for u in (user, other):
            store.set_fact(u, "likes:samosa", "yes", 1)
        d = _ask(user, 2)
        learn.apply_outcome(user, d["decision_id"], "bad", 3)
        assert tools.get_weights(user) and tools.get_weights(other) == {}
        assert _ask(other, 4)["pick"] == "samosa"
    finally:
        store.reset(other)


def test_weights_survive_replays_of_the_same_life_identically(user):
    def run(u):
        store.reset(u)
        store.set_fact(u, "likes:samosa", "yes", 1)
        d = _ask(u, 2)
        learn.apply_outcome(u, d["decision_id"], "bad", 3)
        out = tools.get_weights(u)
        store.reset(u)
        return out
    assert run("learn_a") == run("learn_b")


# ---- through the chat ----

def test_chat_outcome_flow_and_pending_prompt(user, monkeypatch):
    monkeypatch.setenv("LLM_MODE", "off")
    s = cli.Session(user, day=1, auto=True)
    s.handle("I love samosa")
    out = s.handle("samosa or chana chaat?")
    assert out.startswith("samosa.")
    nxt = s.handle("/next")
    assert "How did d" in nxt and "/outcome good|mixed|bad" in nxt
    rated = s.handle("/outcome bad")
    assert "likes 1.00 -> 0.70" in rated and "healthy 1.00 -> 1.30" in rated
    assert "likes" in s.handle("/weights") and "x0.70" in s.handle("/weights")
    assert "bad" in s.handle("/weights likes")
    assert s.handle("/outcome sideways").startswith("Usage")
    assert s.handle("/outcome good d999").startswith("Can't record that")


# ---- the experiment ----

def test_learning_helps_strongly_different_people_and_never_hurts_mild_ones():
    strong = learning.run("strong", n_users=40)
    mild = learning.run("mild", n_users=40)
    last = strong["windows"][-1]
    assert last["learned_ok"] > last["fixed_ok"]
    assert last["learned_regret"] < last["fixed_regret"]
    m = mild["windows"][-1]
    assert m["learned_ok"] >= m["fixed_ok"] - 0.005 * m["n"]


def test_simulation_is_deterministic():
    assert learning.run("moderate", n_users=10) == learning.run("moderate", n_users=10)
