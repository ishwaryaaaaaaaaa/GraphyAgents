"""Advice about people: each principle fires on its graph pattern and only then, the verdict
logic, the wording, the grounding checker, the LLM path and the safety filter."""
import pytest

import cli
from agent import counsel, extract, learn, llm, store, tools


@pytest.fixture
def priya(user):
    store.add_contact(user, "Priya", "friend", 1)
    return user, "priya"


def advise(user, cid, day, **kw):
    kw.setdefault("use_llm", False)
    kw.setdefault("record", False)
    return counsel.counsel(user, cid, day, **kw)


def cancels(user, cid, days):
    for d in days:
        store.log_interaction(user, cid, "cancel", "neutral", "cancelled", d)


# ---- principles ----

def test_repeated_pattern_needs_three_in_thirty_days(priya):
    user, cid = priya
    cancels(user, cid, [10, 18])
    assert "repeated_pattern" not in advise(user, cid, 19)["principles"]
    cancels(user, cid, [25])
    r = advise(user, cid, 26)
    assert "repeated_pattern" in r["principles"] and r["verdict"] == "talk"
    assert "3 times in the last 30 days" in r["text"] and "days 10, 18 and 25" in r["text"]


def test_old_cancellations_stop_counting(priya):
    user, cid = priya
    cancels(user, cid, [1, 15, 40])           # only two fall inside the 30 days before day 41
    assert "repeated_pattern" not in advise(user, cid, 41)["principles"]


def test_fresh_anger_means_wait_a_day(priya):
    user, cid = priya
    store.log_interaction(user, cid, "argument", "tense", "argued", 10)
    for day, fresh in [(10, True), (11, True), (12, False)]:
        r = advise(user, cid, day)
        assert ("fresh_anger" in r["principles"]) is fresh
    r = advise(user, cid, 10)
    assert r["verdict"] == "wait" and r["confidence"] == "high"
    assert r["text"].startswith("Wait a day")


def test_a_rumour_is_checked_at_the_source_and_a_retraction_removes_it(priya):
    user, cid = priya
    store.set_fact(user, "contact:priya:status", "strained", 5, source="hearsay")
    r = advise(user, cid, 6)
    assert "grudge_check" in r["principles"] and "cheap_repair" not in r["principles"]
    assert "came from someone else" in r["text"]
    store.retract_fact(user, "contact:priya:status", 7, "misread")
    assert "grudge_check" not in advise(user, cid, 8)["principles"]   # the guard hides it


def test_typed_strained_status_invites_a_cheap_check_in(priya):
    user, cid = priya
    store.set_fact(user, "contact:priya:status", "strained", 5, source="typed")
    r = advise(user, cid, 9)
    assert "cheap_repair" in r["principles"] and r["verdict"] == "talk"


def test_making_up_drops_the_strain_and_what_hung_off_it(priya):
    user, cid = priya
    base = {"confidence": 1.0, "days_ago": 0}
    extract.apply_ops(user, [{**base, "op": "set_fact", "key": "contact:priya:status",
                              "value": "strained"}], 5)
    assert "avoid_inviting_priya" in tools.get_facts(user, 5)
    extract.apply_ops(user, [{**base, "op": "set_fact", "key": "contact:priya:status",
                              "value": "fine"}], 9)
    assert "avoid_inviting_priya" not in tools.get_facts(user, 9)
    r = advise(user, cid, 10)
    assert "cheap_repair" not in r["principles"] and "no_pattern" in r["principles"]


def test_cutting_someone_off_is_never_decided_in_one_sitting(priya):
    user, cid = priya
    r = advise(user, cid, 5, options=counsel.OPTIONS + ("cut_off",))
    assert "irreversible" in r["principles"] and r["verdict"] == "wait"
    assert r["scores"]["cut_off"] < 0
    assert "very hard to undo" in r["text"]


def test_an_open_promise_comes_first(priya):
    user, cid = priya
    store.make_promise(user, "call on Sunday", "social", 3, contact=cid)
    r = advise(user, cid, 4)
    assert "honour_promise" in r["principles"]
    assert r["first_step"].startswith("First, keep your promise to Priya: call on Sunday.")


def test_the_users_own_value_outranks_the_agents_taste(priya):
    user, cid = priya
    store.add_value(user, "honesty", "I value honesty", 2)
    r = advise(user, cid, 5)
    assert r["verdict"] == "talk" and r["scores"]["talk"] == pytest.approx(3.0)
    store.end_value(user, "honesty", 6)
    assert "value:honesty" not in advise(user, cid, 7)["principles"]


def test_a_value_alone_decides_but_conflicting_values_say_your_call(priya):
    user, cid = priya
    store.add_value(user, "peace", "I value peace", 2)      # let_it_go 1.5 + 1 (nothing wrong) = 2.5
    assert advise(user, cid, 5)["verdict"] == "let_it_go"
    store.add_value(user, "honesty", "I value honesty", 2)  # talk 3.0 against 2.5: too close
    r = advise(user, cid, 5)
    assert r["verdict"] == "your_call" and r["confidence"] == "low"
    assert r["text"].startswith("This one is your call.")
    assert "explain to yourself in a month" in r["first_step"]


def test_earlier_advice_and_how_it_went_shape_the_next(priya):
    user, cid = priya
    first = counsel.counsel(user, cid, 5, use_llm=False)
    assert first["verdict"] == "let_it_go"
    learn.apply_outcome(user, first["decision_id"], "bad", 6)
    second = advise(user, cid, 10)
    assert "past_advice" in second["principles"] and second["verdict"] != "let_it_go"
    assert "last time you chose to let it go" in second["text"] or \
        "last time you chose to let it go" in " ".join(second["reasons"])


def test_good_outcomes_reinforce_the_same_advice(priya):
    user, cid = priya
    first = counsel.counsel(user, cid, 5, use_llm=False)
    learn.apply_outcome(user, first["decision_id"], "good", 6)
    second = advise(user, cid, 10)
    assert second["verdict"] == first["verdict"] and second["scores"]["let_it_go"] == 2.0


def test_a_mutual_friend_is_offered_as_a_go_between(user):
    store.add_contact(user, "Priya", "friend", 1)
    store.add_contact(user, "Asha", "friend", 1)
    store.link_contacts(user, "asha", "priya")
    store.set_fact(user, "contact:priya:status", "strained", 5)
    r = advise(user, "priya", 9)
    assert r["verdict"] == "talk" and "Asha knows Priya too" in r["first_step"]


# ---- bookkeeping ----

def test_advice_is_recorded_with_the_contact_and_values_applied(priya):
    user, cid = priya
    store.add_value(user, "show_up", "I want to be someone who shows up", 1)
    cancels(user, cid, [10, 18, 25])
    r = counsel.counsel(user, cid, 26, use_llm=False)
    audit = tools.explain_decision(user, r["decision_id"])
    assert audit["mode"] == "counsel" and audit["contact"] == "priya"
    assert audit["rules"] == r["principles"] and audit["values_applied"] == ["show_up"]
    assert audit["path_length"] == 1


def test_contacts_belong_to_one_person(user):
    other = user + "_x"
    store.reset(other)
    try:
        store.add_contact(user, "Priya", "friend", 1)
        with pytest.raises(KeyError):
            counsel.counsel(other, "priya", 5, use_llm=False)
    finally:
        store.reset(other)


def test_centrality_counts_shared_history(user):
    store.add_contact(user, "Priya", "friend", 1)
    store.add_contact(user, "Asha", "friend", 1)
    cancels(user, "priya", [3, 6, 9])
    store.log_interaction(user, "asha", "favor", "warm", "helped", 4)
    ranks = tools.rank_contacts(user)
    assert ranks["priya"] > ranks["asha"]


# ---- wording and the checker ----

def test_the_template_leads_with_the_verdict_and_says_what_would_change_its_mind(priya):
    user, cid = priya
    cancels(user, cid, [10, 18, 25])
    text = advise(user, cid, 26)["text"]
    assert text.startswith("Talk to Priya.") and "What would change my mind" in text
    assert "Hey Priya, plans have fallen through" in text


def _brief_for(user, cid, day):
    return {**advise(user, cid, day)["brief"], "_user": user}


def test_the_checker_accepts_the_template_and_rejects_fabrication(user):
    store.add_contact(user, "Priya", "friend", 1)
    store.add_contact(user, "Rhea", "friend", 1)
    cancels(user, "priya", [10, 18, 25])
    r = advise(user, "priya", 26)
    brief = {**r["brief"], "_user": user}
    assert counsel.grounded(r["text"], brief, r["verdict"])
    bad = {
        "another person": r["text"].replace("Priya", "Rhea"),
        "a person nobody told us about": r["text"] + " Meera agrees with you.",
        "invented day": r["text"] + " That was on day 99.",
        "invented event": r["text"] + " They also ghosted you.",
        "invented argument": r["text"] + " You argued with them too.",
        "stale status": r["text"] + " Things are still strained.",
        "diagnosis": r["text"] + " They sound like a narcissist.",
        "verdict not first": "Here is some background first. " + r["text"],
    }
    for name, text in bad.items():
        assert not counsel.grounded(text, brief, r["verdict"]), name


def test_days_in_a_list_are_all_checked(priya):
    user, cid = priya
    cancels(user, cid, [10, 18, 25])
    brief = _brief_for(user, cid, 26)
    assert counsel.grounded("Talk to Priya. She cancelled on days 10, 18 and 25.", brief, "talk")
    assert not counsel.grounded("Talk to Priya. She cancelled on days 10, 18 and 31.", brief, "talk")


@pytest.fixture
def live(tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_MODE", "on")
    monkeypatch.setattr(llm, "CACHE_PATH", tmp_path / "c.json")
    monkeypatch.setattr(llm, "LOG_PATH", tmp_path / "l.jsonl")
    monkeypatch.setattr(llm, "_cache", None)
    monkeypatch.setattr(llm, "MIN_GAP", 0)
    state = {"replies": [], "calls": 0}

    def fake(prompt, schema=None):
        state["calls"] += 1
        return state["replies"].pop(0)

    monkeypatch.setattr(llm, "_call_gemini", fake)
    return state


def test_llm_wording_is_used_only_when_it_stays_inside_the_brief(priya, live):
    user, cid = priya
    cancels(user, cid, [10, 18, 25])
    good = "Talk to Priya. She has cancelled three times lately, so this is a pattern."
    live["replies"] = [good]
    r = counsel.counsel(user, cid, 26, record=False)
    assert r["source"] == "llm" and r["text"] == good and r["verdict"] == "talk"

    # a different day each time, because the client caches by prompt (that is the point of it)
    live["replies"] = ["Talk to Priya, she is toxic.", "Talk to Priya. Rhea agrees."]  # Rhea: invented
    r = counsel.counsel(user, cid, 27, record=False)
    assert r["source"] == "template" and live["calls"] == 3      # regenerated once, then template

    live["replies"] = ["Talk to Priya, she is toxic.", "Talk to Priya. She cancelled again."]
    r = counsel.counsel(user, cid, 28, record=False)
    assert r["source"] == "llm" and "toxic" not in r["text"]    # the second try was clean


def test_the_llm_cannot_change_the_verdict(priya, live):
    user, cid = priya
    cancels(user, cid, [10, 18, 25])
    live["replies"] = ["Let it go, honestly.", "Let it go, honestly."]
    r = counsel.counsel(user, cid, 26, record=False)
    assert r["verdict"] == "talk" and r["source"] == "template"


# ---- safety ----

@pytest.mark.parametrize("text", [
    "I want to kill myself", "I keep thinking about suicide", "he hits me when we argue",
    "my brother threatened me yesterday", "I feel not safe at home", "she abuses me",
])
def test_crisis_language_is_detected(text):
    assert counsel.crisis_check(text)


@pytest.mark.parametrize("text", [
    "my sister hit me up for coffee", "Priya cancelled again", "I killed it at the interview",
    "we argued about the bill", "should I text her?",
])
def test_ordinary_talk_is_not_mistaken_for_a_crisis(text):
    assert not counsel.crisis_check(text)


def test_a_crisis_stops_the_normal_flow_and_writes_nothing(user, monkeypatch):
    monkeypatch.setenv("LLM_MODE", "off")
    s = cli.Session(user, day=1, auto=True)
    s.handle("my friend Priya cancelled again")
    s.pending = ["something"]
    out = s.handle("I want to kill myself, Priya cancelled again")
    assert out == counsel.CRISIS_MESSAGE and s.pending == []
    assert "emergency number" in out and "findahelpline.com" in out
    assert len(tools.list_contacts(user)) == 1 and len(tools.contact_timeline(user, "priya", 9, 9)) == 1
