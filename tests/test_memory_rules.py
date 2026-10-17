import pytest

from agent import store, tools


def test_supersede_closes_old_and_activates_new(user):
    f1, _ = store.set_fact(user, "diet_style", "non_veg", day=1)
    f2, _ = store.set_fact(user, "diet_style", "vegetarian", day=10)
    assert f1 != f2
    snap = {f["id"]: f for f in store.snapshot(user)}
    assert snap[f1]["status"] == "superseded" and snap[f1]["valid_to"] == 10
    assert snap[f2]["status"] == "active" and snap[f2]["valid_to"] is None
    assert tools.get_fact(user, "diet_style", 10) == ("vegetarian", f2)
    rows = tools.get_facts(user, 10)
    assert rows["diet_style"][0] == "vegetarian"


def test_same_value_is_a_noop(user):
    f1, _ = store.set_fact(user, "diet_style", "vegetarian", day=1)
    f2, dropped = store.set_fact(user, "diet_style", "vegetarian", day=5)
    assert f1 == f2 and dropped == []
    assert len(store.snapshot(user)) == 1


def test_two_changes_same_day_keep_a_stable_order(user):
    store.set_fact(user, "lives_in", "hostel", day=3)
    store.set_fact(user, "lives_in", "flat", day=3)
    store.set_fact(user, "lives_in", "hostel", day=3)
    assert tools.get_fact(user, "lives_in", 3)[0] == "hostel"
    assert tools.get_fact_at(user, "lives_in", 3) == "hostel"


def test_earlier_day_than_last_write_is_rejected(user):
    store.set_fact(user, "lives_in", "hostel", day=10)
    with pytest.raises(ValueError):
        store.set_fact(user, "lives_in", "flat", day=4)


def test_retract_is_never_true_and_never_time_travelled(user):
    store.set_fact(user, "dislikes:paneer_wrap", "yes", day=20)
    dropped = store.retract_fact(user, "dislikes:paneer_wrap", day=41, reason="misread")
    assert dropped == []
    assert tools.get_fact(user, "dislikes:paneer_wrap", 41) is None
    assert tools.get_fact_at(user, "dislikes:paneer_wrap", 30) is None
    (f,) = store.snapshot(user)
    assert f["status"] == "retracted"


def test_retract_with_nothing_active_is_empty(user):
    assert store.retract_fact(user, "diet_style", day=2) == []


def test_cascade_drops_a_chain_of_three(user):
    store.set_fact(user, "lives_in", "hostel", day=1)
    store.set_fact(user, "mess_meals_available", "yes", day=1, derived_from=["lives_in"])
    store.set_fact(user, "skip_dinner_ok", "yes", day=1, derived_from=["mess_meals_available"])
    store.set_fact(user, "late_snack_ok", "yes", day=1, derived_from=["skip_dinner_ok"])
    _, dropped = store.set_fact(user, "lives_in", "flat", day=25)
    assert dropped == ["late_snack_ok", "mess_meals_available", "skip_dinner_ok"]
    live = tools.get_facts(user, 25)
    assert set(live) == {"lives_in"}


def test_two_parent_fact_is_dropped_when_either_parent_changes(user):
    store.set_fact(user, "a", "1", day=1)
    store.set_fact(user, "b", "1", day=1)
    store.set_fact(user, "c", "1", day=1, derived_from=["a", "b"])
    _, dropped = store.set_fact(user, "b", "2", day=2)
    assert dropped == ["c"]


def test_retract_cascades_with_retracted_status(user):
    store.set_fact(user, "dislikes:paneer_wrap", "yes", day=20)
    store.set_fact(user, "avoid_paneer_wrap_orders", "yes", day=20,
                   derived_from=["dislikes:paneer_wrap"])
    dropped = store.retract_fact(user, "dislikes:paneer_wrap", day=41)
    assert dropped == ["avoid_paneer_wrap_orders"]
    statuses = {f["key"]: f["status"] for f in store.snapshot(user)}
    assert statuses["avoid_paneer_wrap_orders"] == "retracted"


def test_derived_fact_with_missing_parent_is_a_bug(user):
    with pytest.raises(ValueError):
        store.set_fact(user, "mess_meals_available", "yes", day=1, derived_from=["lives_in"])
    assert store.snapshot(user) == []  # nothing half-written


def test_parent_changing_twice(user):
    store.set_fact(user, "lives_in", "hostel", day=1)
    store.set_fact(user, "mess_meals_available", "yes", day=1, derived_from=["lives_in"])
    store.set_fact(user, "lives_in", "flat", day=5)
    store.set_fact(user, "lives_in", "hostel", day=9)
    assert "mess_meals_available" not in tools.get_facts(user, 9)  # not resurrected


def test_time_travel_before_on_and_after_a_change(user):
    store.set_fact(user, "diet_style", "non_veg", day=1)
    store.set_fact(user, "diet_style", "vegetarian", day=10)
    assert tools.get_fact_at(user, "diet_style", 0) is None
    assert tools.get_fact_at(user, "diet_style", 8) == "non_veg"
    assert tools.get_fact_at(user, "diet_style", 9) == "non_veg"
    assert tools.get_fact_at(user, "diet_style", 10) == "vegetarian"
    assert tools.get_fact_at(user, "diet_style", 99) == "vegetarian"


def test_short_lived_facts_decay_permanent_ones_do_not(user):
    store.set_fact(user, "craving_today", "sweet", day=5, ttl_days=1)
    store.set_fact(user, "studies_at", "iit", day=5)
    assert "craving_today" in tools.get_facts(user, 5)
    assert "craving_today" not in tools.get_facts(user, 6)
    assert "studies_at" in tools.get_facts(user, 500)


def test_two_users_two_graphs_no_leakage(user):
    other = user + "_other"
    store.reset(other)
    try:
        store.set_fact(user, "diet_style", "vegetarian", day=1)
        store.set_fact(other, "diet_style", "non_veg", day=1)
        assert tools.get_fact(user, "diet_style", 1)[0] == "vegetarian"
        assert tools.get_fact(other, "diet_style", 1)[0] == "non_veg"
    finally:
        store.reset(other)


def test_replay_gives_identical_state():
    def run(u):
        store.reset(u)
        store.set_fact(u, "lives_in", "hostel", day=1)
        store.set_fact(u, "mess_meals_available", "yes", day=1, derived_from=["lives_in"])
        store.set_fact(u, "lives_in", "flat", day=25)
        snap = [(f["id"], f["key"], f["value"], f["status"], f["valid_from"], f["valid_to"])
                for f in store.snapshot(u)]
        store.reset(u)
        return snap
    assert run("replay_a") == run("replay_b")
