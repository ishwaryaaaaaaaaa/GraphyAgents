from agent import decide, store, tools


def test_streak_counts_clean_days_since_last_treat_or_slip(user):
    store.start_goal(user, "sugar", 1)
    for d in (1, 2, 3):
        store.log_event(user, "clean_day", "ok", "sugar", d)
    assert tools.count_streak(user, "sugar", 3) == 3
    store.log_event(user, "slip", "party", "sugar", 4)
    assert tools.count_streak(user, "sugar", 4) == 0
    store.log_event(user, "clean_day", "ok", "sugar", 5)
    assert tools.count_streak(user, "sugar", 5) == 1
    assert tools.count_streak(user, "sugar", 3) == 3  # asking about the past still works


def test_streak_and_treat_five_days_earns_then_next_day_says_no(user):
    store.start_goal(user, "sugar", 1)
    for d in range(1, 6):
        store.log_event(user, "clean_day", "ok", "sugar", d)
    first = decide.decide(user, 6, ["gulab_jamun"], add_skip=True)
    assert first["pick"] == "gulab_jamun" and first["earned_treat"] == "gulab_jamun"
    assert tools.count_streak(user, "sugar", 6) == 0  # treat reset it
    second = decide.decide(user, 7, ["gulab_jamun"], add_skip=True)
    assert second["pick"] == "skip" and second["rejected"]["gulab_jamun"] == "only 0 of 5 days"


def test_treat_and_slip_do_not_advance_the_goal(user):
    store.start_goal(user, "sugar", 1)
    store.log_event(user, "treat", "earned", "sugar", 2)
    store.log_event(user, "slip", "oops", "sugar", 3)
    store.log_event(user, "clean_day", "ok", "sugar", 4)
    n = store_count(user, "MATCH ()-[r:ADVANCES]->() RETURN count(r)")
    assert n == 1


def store_count(user, q):
    from agent.db import get_graph
    return get_graph(user).query(q).result_set[0][0]


def test_promise_open_then_broken_then_forgotten(user):
    store.make_promise(user, "study before sleep", "study", 1)
    assert [p["status"] for p in tools.get_open_promises(user, "study", 2)] == ["open"]
    pid = tools.get_open_promises(user, "study", 2)[0]["id"]
    tools.mark_promise(user, pid, "broken", 5)
    assert [p["status"] for p in tools.get_open_promises(user, "study", 6)] == ["broken"]
    assert tools.get_open_promises(user, "study", 20) == []  # long forgotten
    r = decide.decide(user, 6, ["netflix", "study_session"])
    assert r["pick"] == "study_session"  # a broken promise raises the study score


def test_promise_kept_no_longer_counts(user):
    store.make_promise(user, "study before sleep", "study", 1)
    pid = tools.get_open_promises(user, "study", 1)[0]["id"]
    tools.mark_promise(user, pid, "kept", 2)
    assert tools.get_open_promises(user, "study", 3) == []


def test_pagerank_ranks_the_goal_you_act_on_most(user):
    store.start_goal(user, "sugar", 1)
    store.start_goal(user, "fried", 1)
    for d in range(2, 8):
        store.log_event(user, "clean_day", "ok", "sugar", d)
    store.log_event(user, "clean_day", "ok", "fried", 8)
    ranks = tools.rank_goals(user)
    assert ranks["sugar"] > ranks["fried"]


def test_pagerank_with_no_events_is_empty_not_an_error(user):
    store.start_goal(user, "sugar", 1)
    assert tools.rank_goals(user) == {}


def test_recent_events_newest_first(user):
    for d in (1, 2, 3):
        store.log_event(user, "clean_day", f"day {d}", "sugar", d)
    got = tools.get_recent_events(user, "sugar", 2, 3)
    assert [e["day"] for e in got] == [3, 2]


def test_related_facts_follow_derived_links_both_ways(user):
    store.set_fact(user, "lives_in", "hostel", 1)
    store.set_fact(user, "mess_meals_available", "yes", 1, derived_from=["lives_in"])
    assert set(tools.related_facts(user, "lives_in", 2, day=1)) == {"mess_meals_available"}
    assert set(tools.related_facts(user, "mess_meals_available", 2, day=1)) == {"lives_in"}


def test_fact_history_lists_every_value_with_how_it_ended(user):
    store.set_fact(user, "diet_style", "non_veg", 1)
    store.set_fact(user, "diet_style", "vegetarian", 10)
    h = tools.fact_history(user, "diet_style")
    assert [(x["value"], x["status"]) for x in h] == [("non_veg", "superseded"),
                                                     ("vegetarian", "active")]


def test_explain_decision_shows_facts_history_and_path(user):
    store.set_fact(user, "diet_style", "non_veg", 1)
    store.set_fact(user, "diet_style", "vegetarian", 10)
    r = decide.decide(user, 10, ["fried_chicken", "chana_chaat"])
    audit = tools.explain_decision(user, r["decision_id"])
    assert audit["pick"] == "chana_chaat" and audit["path_length"] == 1
    (used,) = audit["used"]
    assert used["key"] == "diet_style" and used["value"] == "vegetarian"
    assert [h["value"] for h in used["history"]] == ["non_veg", "vegetarian"]
    assert tools.explain_decision(user, "d999") is None


def test_guarded_decision_never_uses_a_stale_fact(user):
    store.set_fact(user, "lives_in", "hostel", 1)
    store.set_fact(user, "mess_meals_available", "yes", 1, derived_from=["lives_in"])
    store.set_fact(user, "lives_in", "flat", 5)
    r = decide.decide(user, 6, ["mess_thali", "chana_chaat"])
    assert r["pick"] == "chana_chaat" and r["rejected"] == {"mess_thali": "not available"}
