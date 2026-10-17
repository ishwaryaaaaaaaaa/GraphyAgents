"""One test per row of the rule table. Pure: no database, just contexts."""
import pytest

from agent import decide


def ctx(facts=None, goals=(), streak=None, promises=None, rank=None):
    return {"day": 10, "facts": facts or {}, "goals": set(goals), "streak": streak or {},
            "promises": promises or {}, "rank": rank or {}}


def run(names, **kw):
    return decide.decide_with(ctx(**kw), decide.resolve(names))


def test_meat_rejected_when_vegetarian():
    r = run(["fried_chicken", "chana_chaat"], facts={"diet_style": ("vegetarian", "f1")})
    assert r["pick"] == "chana_chaat"
    assert r["rejected"] == {"fried_chicken": "you are vegetarian"}
    assert "you are vegetarian" in r["reasons"]
    assert r["used_fact_ids"] == ["f1"]


def test_meat_allowed_when_not_vegetarian():
    r = run(["fried_chicken", "chana_chaat"], facts={"diet_style": ("non_veg", "f1")})
    assert r["rejected"] == {}


def test_dislike_rejects():
    r = run(["paneer_wrap", "chana_chaat"], facts={"dislikes:paneer_wrap": ("yes", "f2")})
    assert r["rejected"] == {"paneer_wrap": "you dislike it"} and r["pick"] == "chana_chaat"


def test_requires_key_must_be_yes():
    r = run(["mess_thali", "chana_chaat"])
    assert r["rejected"] == {"mess_thali": "not available"}
    r = run(["mess_thali", "chana_chaat"], facts={"mess_meals_available": ("yes", "f3")})
    assert r["rejected"] == {}


def test_sugar_rejected_when_streak_short():
    r = run(["gulab_jamun", "skip"], goals=["sugar"], streak={"sugar": 2})
    assert r["pick"] == "skip" and r["rejected"] == {"gulab_jamun": "only 2 of 5 days"}


def test_sugar_earned_when_streak_long_enough():
    r = run(["gulab_jamun", "skip"], goals=["sugar"], streak={"sugar": 5})
    assert r["pick"] == "gulab_jamun" and r["earned_treat"] == "gulab_jamun"
    assert "5 days off sugar: earned" in r["reasons"]


def test_sugar_not_restricted_without_a_goal():
    r = run(["gulab_jamun", "skip"], goals=[], streak={})
    assert r["rejected"] == {} and r["earned_treat"] is None


def test_likes_adds_two():
    r = run(["samosa", "pasta"], facts={"likes:samosa": ("yes", "f4")})
    assert r["scores"] == {"samosa": 2.0, "pasta": 0.0} and r["pick"] == "samosa"


def test_likes_no_adds_nothing():
    r = run(["samosa", "chana_chaat"], facts={"likes:samosa": ("no", "f4")})
    assert r["scores"]["samosa"] == 0 and r["pick"] == "chana_chaat"


def test_healthy_adds_one_without_a_reason():
    r = run(["chana_chaat", "pasta"])
    assert r["scores"]["chana_chaat"] == 1 and r["reasons"] == []


def test_fried_goal_penalty_scales_with_goal_rank():
    r = run(["samosa", "pasta"], goals=["fried"], rank={"fried": 1.5})
    assert r["scores"]["samosa"] == pytest.approx(-4.5)
    assert r["pick"] == "pasta" and r["reasons"] == ["goal: eat less fried"]
    r = run(["pasta", "samosa"], goals=["fried"], rank={"fried": 1.0})
    assert r["scores"]["samosa"] == -3


def test_fried_penalty_is_explained_when_the_fried_option_loses():
    r = run(["samosa", "chana_chaat"], goals=["fried"], rank={"fried": 1.0})
    assert r["pick"] == "chana_chaat"
    assert r["reasons"] == ["goal: eat less fried"]
    r = run(["samosa", "skip"], goals=["fried"], rank={"fried": 1.0})
    assert r["pick"] == "skip" and "goal: eat less fried" in r["reasons"]


def test_fried_penalty_is_not_listed_as_a_reason_to_pick_that_option():
    r = run(["samosa"], goals=["fried"], rank={"fried": 1.0})
    assert r["pick"] == "samosa" and r["reasons"] == []


def test_open_and_broken_promises_add_three_with_text():
    p = {"study": [{"text": "study before sleep", "status": "open", "closed": None}]}
    r = run(["study_session", "netflix"], promises=p)
    assert r["pick"] == "study_session"
    assert "promise: study before sleep (still open)" in r["reasons"]
    p["study"][0].update(status="broken", closed=9)
    r = run(["netflix", "study_session"], promises=p)
    assert r["pick"] == "study_session"
    assert "promise: study before sleep (broken last time)" in r["reasons"]


def test_full_tie_goes_to_first_listed():
    assert run(["netflix", "study_session"])["pick"] == "netflix"
    assert run(["study_session", "netflix"])["pick"] == "study_session"


def test_tie_prefers_better_goal_rank():
    r = run(["pasta", "gym"], goals=["exercise"], rank={"exercise": 1.4})
    assert r["pick"] == "gym"


def test_all_rejected_gives_none_and_invents_nothing():
    r = run(["fried_chicken", "chicken_curry"], facts={"diet_style": ("vegetarian", "f1")})
    assert r["pick"] == "none" and set(r["rejected"]) == {"fried_chicken", "chicken_curry"}


def test_unknown_option_is_an_error():
    with pytest.raises(KeyError):
        decide.resolve(["moon_cheese"])


def test_used_facts_are_only_those_consulted():
    facts = {"diet_style": ("vegetarian", "f1"), "likes:pasta": ("yes", "f2"),
             "likes:unrelated": ("yes", "f9")}
    r = run(["pasta", "chana_chaat"], facts=facts)
    assert r["used_fact_ids"] == ["f2"]  # no meat option, so diet was never consulted
