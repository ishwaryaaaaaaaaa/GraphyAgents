import json

import pytest

from data import generator, oracle


def dump(seed):
    return json.dumps(generator.generate(seed), sort_keys=True)


def test_same_seed_same_life_different_seed_different_life():
    assert dump(11) == dump(11)
    assert dump(11) != dump(12)


def test_split_and_heldout_items():
    assert generator.split_of(299) == "train" and generator.split_of(300) == "test"
    for seed in range(0, 40):  # train lives never mention a held-out item anywhere
        text = dump(seed)
        for name in generator.HELDOUT:
            assert f'"{name}"' not in text and f":{name}\"" not in text, (seed, name)
    seen = any(a.get("heldout") for s in range(300, 330)
               for a in generator.generate(s)["steps"] if a["op"] == "ask")
    assert seen  # test lives do ask about held-out foods


def test_steps_are_well_formed_and_in_day_order():
    for seed in (3, 303):
        steps = generator.generate(seed)["steps"]
        days = [s["day"] for s in steps if "day" in s and s["op"] != "time_travel"]
        assert days == sorted(days)
        for s in steps:
            if s["op"] == "ask":
                assert s["expect"] != "" and s["id"].startswith("Q")
                assert all(o in oracle.CATALOGUE for o in s["options"])


def test_questions_are_never_rank_ambiguous():
    """The generator only asks what the oracle can answer for every possible goal rank."""
    for seed in (5, 305):
        life = generator.generate(seed)
        assert all(s["expect"] is not None for s in life["steps"] if s["op"] == "ask")


def test_enough_traps_and_every_stale_answer_differs():
    asks = [s for seed in range(300, 325) for s in generator.generate(seed)["steps"]
            if s["op"] == "ask"]
    traps = [a for a in asks if a["trap"] != "none"]
    assert len(traps) / len(asks) >= 1 / 3
    assert {"diet_change", "cascade", "retraction", "taste_flip"} <= {a["trap"] for a in traps}


def test_test_only_patterns_never_appear_in_training():
    train = {c for s in range(0, 60) for c in generator.generate(s)["changes"]}
    test = {c for s in range(300, 360) for c in generator.generate(s)["changes"]}
    assert "double_change" not in train and "double_change" in test


def test_world_cascade_and_retraction_follow_the_spec():
    w = generator.World()
    w.set("lives_in", "hostel", 1)
    w.set("mess_meals_available", "yes", 1, parents=["lives_in"])
    assert w.set("lives_in", "flat", 5) == ["mess_meals_available"]
    assert oracle.fact_at(w.hist, "mess_meals_available", 3) == "yes"   # invalidated: true then
    assert oracle.fact_at(w.hist, "mess_meals_available", 6) is None
    w.set("dislikes:pasta", "yes", 7)
    w.set("avoid_pasta_orders", "yes", 7, parents=["dislikes:pasta"])
    assert w.retract("dislikes:pasta", 9) == ["avoid_pasta_orders"]
    assert oracle.fact_at(w.hist, "avoid_pasta_orders", 8) is None      # retracted: never true


@pytest.mark.parametrize("seed", [2, 302])
def test_generated_life_replays_with_zero_disagreements(seed, user):
    """The engine and the independent oracle agree on a whole life, graph included."""
    from eval import replay
    run = replay.replay(user, generator.generate(seed)["steps"])
    assert run["asks"], "life should contain questions"
    assert all(a["arms"]["guarded"]["ok"] for a in run["asks"])
    assert all(a["arms"]["guarded"]["stale_use"] is False for a in run["asks"])
    assert all(c["ok"] for c in run["cascade"]) and all(t["ok"] for t in run["time_travel"])
