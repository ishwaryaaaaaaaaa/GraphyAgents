"""The social oracle is independent code from the same written spec. These tests pin it, check it
has not drifted from counsel.py, and check the whole evaluation: engine and oracle agree, and the
unguarded readers fail on the stale-memory traps."""
import json
import re
from pathlib import Path

import pytest

from agent import counsel
from data import social_generator as sg
from data import social_oracle as so
from eval import social

ROOT = Path(__file__).resolve().parent.parent


def test_oracle_constants_match_counsel():
    assert (so.PATTERN_DAYS, so.PATTERN_MIN, so.FRESH_DAYS) == (
        counsel.PATTERN_DAYS, counsel.PATTERN_MIN, counsel.FRESH_DAYS)
    assert so.VALUE_BOOST == counsel.VALUE_BOOST and so.HUMILITY_MARGIN == counsel.HUMILITY_MARGIN
    assert so.TIE_ORDER == counsel.TIE_ORDER and so.VALUE_LEAN == counsel.VALUE_LEAN


def test_oracle_never_imports_the_agent():
    for name in ("social_oracle.py", "social_generator.py"):
        src = (ROOT / "data" / name).read_text(encoding="utf-8")
        assert not re.search(r"^\s*(from|import)\s+agent\b", src, re.M), name


def world(**kw):
    base = {"day": 30, "options": ["talk", "wait", "let_it_go"], "events": [], "status": None,
            "values": [], "promises": [], "past": []}
    return {**base, **kw}


def test_oracle_spec_cases():
    ev = [{"kind": "cancel", "day": d} for d in (10, 18, 25)]
    assert so.verdict(world(events=ev, day=26)) == ("talk", ["repeated_pattern"])
    assert so.verdict(world(events=[{"kind": "argument", "day": 30}])) == ("wait", ["fresh_anger"])
    assert so.verdict(world(events=[{"kind": "argument", "day": 28}]))[1] == ["no_pattern"]
    hearsay = {"value": "strained", "source": "hearsay"}
    assert so.principles(world(status=hearsay))[0][0] == "grudge_check"
    typed = {"value": "strained", "source": "typed"}
    assert so.verdict(world(status=typed)) == ("talk", ["cheap_repair"])
    assert so.verdict(world(options=["talk", "wait", "let_it_go", "cut_off"]))[0] == "wait"
    assert so.verdict(world(values=["peace", "honesty"]))[0] == "your_call"
    old = [{"pick": "let_it_go", "result": "bad", "day": 5}]
    assert so.verdict(world(past=old))[1] == ["no_pattern", "past_advice"]
    unrated = [{"pick": "let_it_go", "result": None, "day": 5}] * 3
    assert "past_advice" not in so.verdict(world(past=unrated))[1]


def test_generator_is_deterministic_and_varied():
    dump = lambda s: json.dumps(sg.generate(s), sort_keys=True)  # noqa: E731
    assert dump(2001) == dump(2001) and dump(2001) != dump(2002)
    steps = sg.generate(2001)["steps"]
    days = [s["day"] for s in steps]
    assert days == sorted(days)


def test_generator_covers_every_principle_and_both_trap_kinds():
    principles, traps = set(), set()
    for seed in range(2000, 2040):
        for s in sg.generate(seed)["steps"]:
            if s["op"] == "counsel":
                principles |= {p.split(":")[0] for p in s["expect_principles"]}
                traps.add(s["trap"])
    assert principles >= {"fresh_anger", "irreversible", "repeated_pattern", "grudge_check",
                          "cheap_repair", "honour_promise", "value", "past_advice", "no_pattern"}
    assert {"made_up", "rumour_retracted"} <= traps


@pytest.fixture(scope="module")
def runs():
    out = []
    for seed in range(2000, 2012):
        user = f"soctest{seed}"
        out.append(social.replay(user, sg.generate(seed)))
        from agent import store
        store.reset(user)
    return out


def test_engine_and_oracle_agree_on_whole_lives(runs):
    for run in runs:
        for a in run:
            g = a["arms"]["guarded"]
            assert g["verdict_ok"] and g["principles_ok"], (a["id"], a["expect_principles"], g)
            assert not g["stale_use"] and a["audit_ok"]


def test_unguarded_readers_fail_exactly_where_theory_says(runs):
    s = social.summarise(runs)
    by = s["by_trap"]
    assert by["rumour_retracted"]["guarded"] == by["rumour_retracted"]["n"]
    assert by["rumour_retracted"]["last_write_wins"] == 0 and by["rumour_retracted"]["first_write"] == 0
    assert by["made_up"]["last_write_wins"] == by["made_up"]["n"]       # fixes a plain change
    assert by["made_up"]["first_write"] == 0                            # but not the first-write read
    assert s["arms"]["guarded"]["stale_use"]["k"] == 0
    assert s["arms"]["first_write"]["stale_use"]["k"] > 0


def test_the_grounding_checker_accepts_real_advice_and_catches_every_corruption(runs):
    s = social.summarise(runs)["guarded_only"]
    assert s["clean_text_accepted"]["k"] == s["clean_text_accepted"]["n"] > 0
    for name, r in s["corruptions_caught"].items():
        assert r["k"] == r["n"] > 0, name
    assert {"wrong_person", "invented_day", "invented_event", "diagnosis"} <= set(
        s["corruptions_caught"])
