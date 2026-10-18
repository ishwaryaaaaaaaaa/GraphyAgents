"""Drive the chat loop through Session, the way a person would."""
import pytest

import cli
from agent import extract, tools


@pytest.fixture
def chat(user, monkeypatch):
    monkeypatch.setenv("LLM_MODE", "off")
    return cli.Session(user, day=1, auto=True)


def test_diet_change_then_a_fork(chat):
    chat.handle("I eat meat again")
    chat.handle("I love fried chicken")
    assert chat.handle("fried chicken or chana chaat?").startswith("fried chicken.")
    chat.handle("/day 10")
    out = chat.handle("I turned vegetarian")
    assert "diet_style = vegetarian" in out and "no longer true" not in out
    answer = chat.handle("fried chicken or chana chaat?")
    assert answer.startswith("chana chaat.") and "you are vegetarian" in answer


def test_why_shows_history_and_path(chat):
    chat.handle("I eat meat again")
    chat.handle("/day 10")
    chat.handle("I turned vegetarian")
    chat.handle("fried chicken or chana chaat?")
    why = chat.handle("/why")
    assert "graph path Person -> Decision: length 1" in why
    assert "non_veg[superseded] -> vegetarian[active]" in why
    assert "vegetarian on day 10; before that non veg" in chat.handle("fried chicken or chana chaat?")


def test_moving_out_cascades_and_changes_the_answer(chat):
    chat.handle("I moved to the hostel")
    chat.handle("I love mess thali")
    assert chat.handle("mess thali or chana chaat?").startswith("mess thali.")
    chat.handle("/day 25")
    out = chat.handle("I moved to a flat")
    assert "no longer true: mess_meals_available" in out
    answer = chat.handle("mess thali or chana chaat?")
    assert answer.startswith("chana chaat.") and "not available" in answer


def test_dislike_then_retraction(chat):
    chat.handle("I love paneer wrap")
    chat.handle("I hate paneer wrap")
    assert chat.handle("paneer wrap or chana chaat?").startswith("chana chaat.")
    chat.handle("/day 5")
    out = chat.handle("that was wrong about paneer wrap")
    assert "retracted dislikes:paneer_wrap" in out and "avoid_paneer_wrap_orders" in out
    assert chat.handle("paneer wrap or chana chaat?").startswith("paneer wrap.")


def test_sugar_streak_through_the_chat(chat):
    chat.handle("I want to cut sugar")
    for _ in range(5):
        chat.handle("/clean")
        chat.handle("/next")
    assert chat.handle("/streak sugar") == "sugar: 5 clean days"
    out = chat.handle("can I have gulab jamun?")
    assert out.startswith("gulab jamun.") and "5 days off sugar: earned" in out
    chat.handle("/next")
    assert chat.handle("can I have gulab jamun?").startswith("skip.")


def test_unknown_food_is_never_invented(chat):
    assert "moon cheese" in chat.handle("moon cheese or pasta?")


def test_without_auto_changes_wait_for_a_yes(user, monkeypatch):
    monkeypatch.setenv("LLM_MODE", "off")
    s = cli.Session(user, day=3, auto=False)
    out = s.handle("I turned vegetarian")
    assert "OK? (y/n)" in out and tools.get_facts(user, 3) == {}
    assert s.handle("y").startswith("Okay, noted:")
    assert tools.get_fact(user, "diet_style", 3)[0] == "vegetarian"
    s.handle("I love pasta")
    assert s.handle("n") == "OK, nothing written."
    assert "likes:pasta" not in tools.get_facts(user, 3)


def test_moving_on_without_answering_says_what_was_dropped(user, monkeypatch):
    monkeypatch.setenv("LLM_MODE", "off")
    s = cli.Session(user, day=3, auto=False)
    s.handle("I turned vegetarian")
    out = s.handle("I love pasta")
    assert out.startswith("(I did not write: set diet_style to vegetarian)")
    assert "I'll set likes:pasta to yes" in out and tools.get_facts(user, 3) == {}


def test_low_confidence_is_never_written_without_a_yes(user, monkeypatch):
    monkeypatch.setenv("LLM_MODE", "off")
    unsure = {"ops": [{"op": "set_fact", "key": "likes:pasta", "value": "no", "confidence": 0.4,
                       "days_ago": 0}], "errors": [], "source": "llm"}
    monkeypatch.setattr(extract, "extract", lambda text, day, use_llm=True, contacts=(): unsure)
    s = cli.Session(user, day=3, auto=True)   # even auto-confirm must not write it
    out = s.handle("hmm maybe I don't like pasta")
    assert "Did you mean" in out and tools.get_facts(user, 3) == {}
    s.handle("yes")
    assert tools.get_fact(user, "likes:pasta", 3)[0] == "no"


def test_relative_date_cannot_rewrite_history(chat):
    chat.handle("/day 10")
    chat.handle("I turned vegetarian")
    chat.handle("/day 12")
    chat.handle("I eat meat again yesterday")   # would be day 11: after the last write, fine
    chat.handle("/day 13")
    out = chat.handle("I turned vegetarian 9 days ago")   # day 4 < last write: clamped
    assert out.startswith("Okay, noted:")
    assert [h["valid_from"] for h in tools.fact_history(chat.user, "diet_style")][-1] >= 11


def test_fork_parser_shapes():
    with pytest.raises(ValueError) as e:
        cli.parse_fork("dessert or skip?")
    assert "dessert" in str(e.value) and "gulab jamun" in str(e.value)  # suggests real desserts
    assert cli.parse_fork("samosa or chana chaat?") == (["samosa", "chana_chaat"], False)
    assert cli.parse_fork("can I have ice cream?") == (["ice_cream"], True)
    assert cli.parse_fork("I love samosa") is None
    assert cli.parse_fork("/ask pasta vs salad bowl") == (["pasta", "salad_bowl"], False)


def test_help_unknown_and_reset(chat):
    assert "/facts" in chat.handle("/help")
    assert chat.handle("/bogus").startswith("Unknown command")
    chat.handle("I turned vegetarian")
    chat.handle("/reset")
    assert chat.handle("/facts") == "(nothing yet)"
    out = chat.handle("what a lovely day")
    assert out.startswith("Okay, no worries") and "pasta or sprouts?" in out    # friendly, and it says what it can do
    out = chat.handle("I like quinoa bowls")                     # a food it has not learned
    assert "haven't learned" in out and "pasta or sprouts?" in out
