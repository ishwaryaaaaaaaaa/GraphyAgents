"""The LLM client, the Gemini extractor (replayed fixtures) and the explainer. No key needed."""
import json
from pathlib import Path

import pytest

from agent import explain, extract, llm

FIXTURES = json.loads((Path(__file__).parent / "fixtures" / "extract_llm.json")
                      .read_text(encoding="utf-8"))["cases"]


class RateLimit(Exception):
    code = 429


@pytest.fixture
def live(tmp_path, monkeypatch):
    """LLM mode on, with a temp cache/log and a stub in place of the network call."""
    monkeypatch.setenv("LLM_MODE", "on")
    monkeypatch.setattr(llm, "CACHE_PATH", tmp_path / "cache.json")
    monkeypatch.setattr(llm, "LOG_PATH", tmp_path / "log.jsonl")
    monkeypatch.setattr(llm, "_cache", None)
    monkeypatch.setattr(llm, "MIN_GAP", 0)
    state = {"calls": 0, "reply": "ok", "errors": []}

    def fake(prompt, schema=None):
        state["calls"] += 1
        if state["errors"]:
            raise state["errors"].pop(0)
        return state["reply"]

    monkeypatch.setattr(llm, "_call_gemini", fake)
    return state


# ---- the client ----

def test_off_mode_raises_so_callers_fall_back(monkeypatch):
    monkeypatch.setenv("LLM_MODE", "off")
    with pytest.raises(llm.LLMUnavailable):
        llm.ask("hi")


def test_second_identical_prompt_is_a_cache_hit(live):
    assert llm.ask("hello") == "ok" and llm.ask("hello") == "ok"
    assert live["calls"] == 1
    lines = [json.loads(x) for x in llm.LOG_PATH.read_text().splitlines()]
    assert [x["cached"] for x in lines] == [False, True]


def test_cache_is_keyed_by_prompt(live):
    llm.ask("a")
    llm.ask("b")
    assert live["calls"] == 2


def test_rate_limit_is_retried_with_backoff_then_succeeds(live):
    live["errors"] = [RateLimit(), RateLimit()]
    waits = []
    assert llm.ask("x", sleep=waits.append) == "ok"
    assert waits == [1, 2] and live["calls"] == 3


def test_gives_up_after_four_backoffs(live):
    live["errors"] = [RateLimit() for _ in range(10)]
    waits = []
    with pytest.raises(llm.LLMUnavailable):
        llm.ask("x", sleep=waits.append)
    assert waits == [1, 2, 4, 8] and live["calls"] == 5


def test_other_errors_do_not_retry(live):
    live["errors"] = [ValueError("boom")]
    with pytest.raises(llm.LLMUnavailable):
        llm.ask("x", sleep=lambda s: None)
    assert live["calls"] == 1


def test_request_config_is_valid_for_the_sdk():
    from google.genai import types
    types.GenerateContentConfig(temperature=0, response_mime_type="application/json",
                                response_json_schema=extract._SCHEMA)


# ---- the Gemini extractor, replaying fixtures ----

@pytest.mark.parametrize("case", FIXTURES, ids=[c["name"] for c in FIXTURES])
def test_extraction_fixture(case, live):
    live["reply"] = json.dumps(case["response"])
    got = extract.extract(case["text"], case["day"])
    assert got["source"] == "llm"
    shape = []
    for o in got["ops"]:
        shape.append([o["op"], o.get("key") or o.get("tag"), o.get("value"), o["days_ago"]])
    assert shape == case["expect"]
    assert len(got["errors"]) == case.get("errors", 0)
    sure, unsure = extract.split_by_confidence(got["ops"])
    assert len(unsure) == case.get("unsure", 0)


def test_garbage_from_the_model_falls_back_to_regex(live):
    live["reply"] = "sorry, I cannot help with that"
    got = extract.extract("I turned vegetarian last week", 20)
    assert got["source"] == "regex" and got["ops"][0]["value"] == "vegetarian"


def test_llm_outage_falls_back_to_regex(live):
    live["errors"] = [ValueError("down")] * 5
    got = extract.extract("I moved to a flat", 20)
    assert got["source"] == "regex" and got["ops"][0]["key"] == "lives_in"


# ---- the explainer ----

DECISION = {"pick": "chana_chaat", "reasons": ["you are vegetarian", "goal: eat less fried"],
            "rejected": {"fried_chicken": "you are vegetarian"},
            "scores": {"chana_chaat": 1.0}, "used_fact_ids": ["f1"]}


def test_template_is_verdict_first_with_two_reasons():
    assert explain.template(DECISION) == ("chana chaat. you are vegetarian; "
                                          "goal: eat less fried.")


def test_template_when_everything_is_rejected():
    d = {"pick": "none", "reasons": [], "rejected": {"fried_chicken": "you are vegetarian"}}
    assert explain.template(d).startswith("None of those work right now")


@pytest.mark.parametrize("text,ok", [
    ("Go for chana chaat: you are vegetarian.", True),
    ("Chana chaat, since fried chicken is out and you are vegetarian.", True),
    ("Chana chaat, and pasta would also be fine.", False),          # invented food
    ("Chana chaat; you live in the hostel.", False),               # invented fact
    ("Chana chaat, you have 9 days of streak.", False),             # invented number
    ("Chana chaat is better for your cholesterol.", False),         # medical claim
])
def test_grounding_checker(text, ok):
    assert explain.grounded(text, DECISION) is ok


def test_llm_text_is_used_only_when_grounded(live, user):
    live["reply"] = "Chana chaat: you are vegetarian."
    assert explain.explain(user, DECISION) == "Chana chaat: you are vegetarian."
    live["reply"] = "Chana chaat, but pasta is lovely too."
    out = explain.explain(user, {**DECISION, "reasons": ["you are vegetarian"]})
    assert out == "chana chaat. you are vegetarian."   # invented food, so the template wins


def test_explain_works_with_the_llm_off(user, monkeypatch):
    monkeypatch.setenv("LLM_MODE", "off")
    assert explain.explain(user, DECISION).startswith("chana chaat.")
