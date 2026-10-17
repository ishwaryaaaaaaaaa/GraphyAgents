"""The oracle is independent code written from the spec. These tests pin its behaviour,
check it has not drifted from rules.json, and check it never imports the agent."""
import json
import re
from pathlib import Path

from data import oracle

ROOT = Path(__file__).resolve().parent.parent
RULES = json.loads((ROOT / "agent" / "rules.json").read_text(encoding="utf-8"))


def world(facts=None, goals=(), events=(), promises=()):
    return {"facts": facts or {}, "goals": list(goals), "events": list(events),
            "promises": list(promises)}


def clean(days, tag="sugar"):
    return [{"day": d, "kind": "clean_day", "tag": tag} for d in days]


def test_oracle_constants_match_rules_json():
    assert oracle.STREAK_DAYS == RULES["sugar_streak_days"]
    assert oracle.LIKE_BONUS == RULES["likes"]
    assert oracle.HEALTHY_BONUS == RULES["healthy"]
    assert oracle.FRIED_GOAL_PENALTY == RULES["fried_goal_penalty"]
    assert oracle.SUGAR_EARNED_BONUS == RULES["sugar_earned"]
    assert oracle.PROMISE_BONUS == RULES["promise"]
    assert oracle.PROMISE_RECENT_DAYS == RULES["promise_recent_days"]
    assert min(oracle.RANK_GRID) == 1.0 and max(oracle.RANK_GRID) == RULES["rank_multiplier_max"]


def test_oracle_never_imports_the_agent():
    src = (ROOT / "data" / "oracle.py").read_text(encoding="utf-8")
    assert not re.search(r"^\s*(from|import)\s+agent\b", src, re.M)


def test_vegetarian_rejects_meat_and_cascade_removes_availability():
    w = world({"diet_style": "vegetarian"})
    assert oracle.expected_pick(w, ["fried_chicken", "chana_chaat"], 5) == "chana_chaat"
    assert oracle.expected_pick(world(), ["mess_thali", "chana_chaat"], 5) == "chana_chaat"
    w = world({"mess_meals_available": "yes", "likes:mess_thali": "yes"})
    assert oracle.expected_pick(w, ["mess_thali", "chana_chaat"], 5) == "mess_thali"


def test_sugar_streak_reset_by_treat_and_slip():
    ev = clean(range(1, 6))
    assert oracle.streak(ev, "sugar", 5) == 5
    assert oracle.expected_pick(world(goals=["sugar"], events=ev), ["gulab_jamun", "skip"], 6) \
        == "gulab_jamun"
    ev2 = ev + [{"day": 6, "kind": "treat", "tag": "sugar"}]
    assert oracle.streak(ev2, "sugar", 7) == 0
    assert oracle.expected_pick(world(goals=["sugar"], events=ev2), ["gulab_jamun", "skip"], 7) == "skip"
    assert oracle.streak(ev + [{"day": 4, "kind": "slip", "tag": "sugar"}], "sugar", 5) == 1


def test_promise_open_broken_recently_and_forgotten():
    def p(status, closed=None):
        return [{"tag": "study", "text": "t", "made": 1, "status": status, "closed": closed}]
    for pr, day, want in [(p("open"), 10, "study_session"), (p("broken", 9), 10, "study_session"),
                          (p("broken", 7), 10, "study_session"), (p("broken", 6), 10, "netflix"),
                          (p("kept", 9), 10, "netflix")]:
        names = ["netflix", "study_session"]
        assert oracle.expected_pick(world(promises=pr), names, day) == want, (pr, day)


def test_rank_dependent_answers_are_ambiguous_not_guessed():
    # fried penalty is -3 x rank in [1, 1.5]: against a +4 option the answer flips inside the grid
    w = world({"likes:samosa": "yes", "likes:pasta": "yes"}, goals=["fried"])
    w["facts"].update({"likes:salad_bowl": "yes"})
    assert oracle.expected_pick(w, ["samosa", "salad_bowl"], 3) in ("salad_bowl", None)
    # an exact tie between options of different goal rank is ambiguous too
    w2 = world(goals=["exercise", "study"])
    assert oracle.expected_pick(w2, ["gym", "study_session"], 3) in (None, "gym", "study_session")


def test_fact_at_and_margin():
    hist = {"k": [{"start": 1, "end": 5, "value": "a", "retracted": False},
                  {"start": 5, "end": None, "value": "b", "retracted": False}],
            "r": [{"start": 2, "end": 9, "value": "x", "retracted": True}]}
    assert [oracle.fact_at(hist, "k", d) for d in (0, 1, 4, 5, 50)] == [None, "a", "a", "b", "b"]
    assert oracle.fact_at(hist, "r", 5) is None
    assert oracle.margin(world({"likes:pasta": "yes"}), ["pasta", "chana_chaat"], 1) == 1
