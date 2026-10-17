"""Meera: a fictional student whose life changes over 55 days.

Hand-written. Every `expect` below was worked out by hand from the rule table in the
README, NOT by running decide.py, so the evaluation is not the engine grading itself.
Steps run in list order; days never go backwards.
"""


def _set(day, key, value, derived_from=(), expect_dropped=None):
    return {"op": "set", "day": day, "key": key, "value": value,
            "derived_from": list(derived_from), "expect_dropped": expect_dropped}


def _retract(day, key, reason, expect_dropped=None):
    return {"op": "retract", "day": day, "key": key, "reason": reason,
            "expect_dropped": expect_dropped}


def _ask(day, qid, options, expect, trap, add_skip=False, note=""):
    return {"op": "ask", "day": day, "id": qid, "options": options, "expect": expect,
            "trap": trap, "add_skip": add_skip, "note": note}


def _clean(day):
    return {"op": "event", "day": day, "kind": "clean_day", "what": "no sugar today", "tag": "sugar"}


def _tt(qid, key, day, expect):
    return {"op": "time_travel", "id": qid, "key": key, "as_of": day, "expect": expect}


STEPS = [
    # day 1: who she is
    _set(1, "diet_style", "non_veg"),
    _set(1, "lives_in", "hostel"),
    _set(1, "mess_meals_available", "yes", derived_from=["lives_in"]),
    _set(1, "likes:samosa", "yes"),
    _set(1, "likes:fried_chicken", "yes"),
    _set(1, "likes:dal_rice", "yes"),
    _set(1, "likes:paneer_wrap", "yes"),
    _set(1, "likes:mess_thali", "yes"),
    _ask(2, "Q1", ["fried_chicken", "dal_rice"], "dal_rice", "control",
         note="likes both; dal rice is also healthy"),

    # days 3-8: a sugar goal and a 5-day streak
    {"op": "goal_start", "day": 3, "tag": "sugar"},
    _clean(3), _clean(4), _clean(5),
    _ask(5, "Q2", ["gulab_jamun"], "skip", "streak", add_skip=True, note="3 of 5 days: not yet"),
    _clean(6), _clean(7),
    _ask(8, "Q3", ["gulab_jamun"], "gulab_jamun", "streak", add_skip=True,
         note="5 clean days: earned (a treat is granted)"),
    _ask(9, "Q4", ["gulab_jamun"], "skip", "streak", add_skip=True,
         note="the treat reset the streak"),
    _clean(9), _clean(10),

    # day 10: she goes vegetarian
    _set(10, "diet_style", "vegetarian"),
    _ask(10, "Q5", ["fried_chicken", "chana_chaat"], "chana_chaat", "diet_change",
         note="stale memory still says non_veg and likes fried chicken"),
    _clean(11), _clean(12), _clean(13),
    _ask(14, "Q6", ["ice_cream"], "ice_cream", "streak", add_skip=True,
         note="five clean days since the treat: second one earned"),

    # day 15: stops liking samosa
    _set(15, "likes:samosa", "no"),
    _ask(15, "Q7", ["samosa", "chana_chaat"], "chana_chaat", "taste_flip",
         note="stale memory still says she likes samosa"),

    # day 25: moves out of the hostel; the mess meals fact must go with it
    _set(25, "lives_in", "flat", expect_dropped=["mess_meals_available"]),
    _ask(25, "Q8", ["mess_thali", "chana_chaat"], "chana_chaat", "cascade",
         note="no more mess: stale memory still offers the thali"),

    # days 28-40: a promise made, broken, and eventually forgotten
    {"op": "promise", "day": 28, "alias": "study", "text": "study before sleep", "tag": "study"},
    _ask(30, "Q9", ["study_session", "netflix"], "study_session", "promise",
         note="promise still open"),
    {"op": "promise_mark", "day": 31, "alias": "study", "status": "broken"},
    _ask(32, "Q10", ["study_session", "netflix"], "study_session", "promise",
         note="broken yesterday: lean towards study"),

    # day 36: a dislike is read from a message (wrongly); day 41 it is retracted
    _set(36, "dislikes:paneer_wrap", "yes"),
    _set(36, "avoid_paneer_wrap_orders", "yes", derived_from=["dislikes:paneer_wrap"]),
    _ask(38, "Q11", ["paneer_wrap", "chana_chaat"], "chana_chaat", "dislike",
         note="the dislike is believed at this point"),
    _ask(40, "Q12", ["netflix", "study_session"], "netflix", "promise",
         note="a promise broken 9 days ago no longer counts; tie goes to the first listed"),
    _retract(41, "dislikes:paneer_wrap", "friend's message was misread as hers",
             expect_dropped=["avoid_paneer_wrap_orders"]),
    _ask(42, "Q13", ["paneer_wrap", "chana_chaat"], "paneer_wrap", "retraction",
         note="the dislike was never true; stale memory still rejects paneer wrap"),

    # day 45: a slip; day 50: she drops the sugar goal altogether
    {"op": "event", "day": 45, "kind": "slip", "what": "dessert at a party", "tag": "sugar"},
    {"op": "goal_end", "day": 50, "tag": "sugar"},
    _ask(51, "Q14", ["gulab_jamun"], "gulab_jamun", "goal_ended", add_skip=True,
         note="no sugar goal any more; stale memory still enforces it"),

    # days 52-54: a taste that changes twice in one week
    _set(52, "likes:pasta", "yes"),
    _set(54, "likes:pasta", "no"),
    _ask(55, "Q15", ["pasta", "chana_chaat"], "chana_chaat", "double_change",
         note="changed twice; only the last value counts"),

    # time travel, asked after the whole story has played out
    _tt("T1", "diet_style", 8, "non_veg"),
    _tt("T2", "diet_style", 20, "vegetarian"),
    _tt("T3", "likes:samosa", 12, "yes"),
    _tt("T4", "likes:samosa", 16, "no"),
    _tt("T5", "lives_in", 24, "hostel"),
    _tt("T6", "lives_in", 26, "flat"),
    _tt("T7", "mess_meals_available", 24, "yes"),
    _tt("T8", "mess_meals_available", 26, None),
    _tt("T9", "dislikes:paneer_wrap", 40, None),
    _tt("T10", "likes:pasta", 53, "yes"),
]
