"""Counsel: advice about people, in the way a wise friend would give it.

Wisdom here is not a bigger rule list. Code does five things, each backed by the graph:
  evidence   the real history with this person: last interactions, patterns, open promises,
             how earlier advice turned out
  values     what the user said they care about; it outranks the agent's own taste
  patterns   repeats a single event hides (the third cancellation in a month)
  outcomes   earlier advice and how it went ("last time you waited, it went well")
  humility   says how sure it is, what would change its mind, and when it is simply the
             user's call

The flow: code builds a structured BRIEF from guarded reads, code fires PRINCIPLES (each
triggered by a graph pattern) and scores the options, code picks the verdict. The LLM, if on,
only writes the wording of a verdict code already decided, from the brief and nothing else;
a checker then verifies every person, day, event and status in the text exists in the brief.
On any failure the template is used. With the LLM off it is always the template.

Boundaries: perspective on ordinary friendship and family friction. It does not diagnose anyone or
judge a character from one message. Signs of danger or crisis stop the normal flow.
"""
import json
import re

from agent import llm, tools

OPTIONS = ("talk", "wait", "let_it_go")
PATTERN_DAYS, PATTERN_MIN, FRESH_DAYS = 30, 3, 1
VALUE_BOOST = 1.5          # the user's own value outranks the agent's taste
HUMILITY_MARGIN = 1.0      # a lead smaller than this is "your call"
TIE_ORDER = {"wait": 0.02, "let_it_go": 0.01}   # gentlest reversible option wins an exact tie

REVERSIBLE = {
    "talk": "reversible: a message can be followed by another",
    "wait": "reversible: you lose nothing by sleeping on it",
    "let_it_go": "mostly reversible: you can still raise it later",
    "cut_off": "irreversible: very hard to undo",
}
VALUE_LEAN = {
    "honesty": {"talk": 2.0},
    "show_up": {"talk": 1.0},
    "peace": {"let_it_go": 1.0, "wait": 1.0},
    "self_respect": {"talk": 1.0},
    "loyalty": {"talk": 1.0, "let_it_go": 1.0},
}
VALUE_WORDS = {"honesty": "honesty", "show_up": "showing up", "peace": "peace",
               "self_respect": "self-respect", "loyalty": "loyalty"}
KIND_WORDS = {"cancel": "cancelled", "ghosted": "gone quiet", "argument": "argued",
              "apology": "apologised", "favor": "helped you", "celebration": "celebrated",
              "plan": "made plans", "made_up": "made up"}
_UNSET = object()


# ---- safety: danger and crisis stop the normal flow -------------------------------------

_CRISIS = re.compile(
    r"\b(kill myself|killing myself|end my life|suicid\w*|want to die|hurt myself|harm myself|"
    r"self[- ]harm|(he|she|they|my \w+) (hits|hit|beats|beat|threatens|threatened) me|"
    r"(am|feel) not safe|afraid for my life|being abused|abus(es|ed|ing) me|kill (him|her|them))\b",
    re.I)

CRISIS_MESSAGE = (
    "I'm really sorry you're going through this. What you describe sounds serious, and I am not "
    "the right help for it. If you might be in danger, or thinking about hurting yourself or "
    "someone else, please contact your local emergency number now, or go to someone you trust "
    "and stay with them. A crisis line in your country can talk with you right away "
    "(findahelpline.com lists them by country). I've set the normal advice aside.")


def crisis_check(text):
    return bool(_CRISIS.search(text))


# ---- the brief ---------------------------------------------------------------------------

def build_brief(user, cid, day, options=OPTIONS, status=_UNSET):
    """Everything the advice may rest on, from guarded reads. `status` lets the evaluation swap
    in a stale reader for the contact's status fact (None means no status known)."""
    contact = tools.get_contact(user, cid)
    if contact is None:
        raise KeyError(f"no contact {cid!r}")
    meta = tools.get_fact_meta(user, f"contact:{cid}:status", day) if status is _UNSET else status
    counts = {k: tools.pattern(user, cid, k, PATTERN_DAYS, day)
              for k in ("cancel", "ghosted", "argument")}
    return {
        "day": day,
        "contact": contact,
        "status": meta,
        "timeline": tools.contact_timeline(user, cid, 5, day),
        "counts": counts,
        "fresh_argument": tools.pattern(user, cid, "argument", FRESH_DAYS + 1, day) > 0,
        "values": tools.values(user),
        "promises": tools.open_promises_to(user, cid, day),
        "past": tools.past_advice(user, cid, 5),
        "options": list(options),
        "reversibility": {o: REVERSIBLE[o] for o in options},
        "helpers": tools.mutual_friends(user, cid),
    }


# ---- principles: each triggered by a graph pattern ----------------------------------------

def _p(pid, why, lean, cite=()):
    return {"id": pid, "why": why, "lean": lean, "cite": list(cite)}


def fire(brief):
    """The principles that apply, each with the options it favours and why."""
    name = brief["contact"]["name"]
    opts = set(brief["options"])
    status = (brief["status"] or {}).get("value")
    source = (brief["status"] or {}).get("source")
    out = []

    arg_days = [e["day"] for e in brief["timeline"] if e["kind"] == "argument"]
    if brief["fresh_argument"] and arg_days:
        out.append(_p("fresh_anger", f"you and {name} argued on day {arg_days[0]}, so anger is "
                      "still fresh: a hard conversation can wait a day",
                      {"talk": -2.0, "wait": 3.0}, ["timeline"]))
    if "cut_off" in opts:
        out.append(_p("irreversible", "cutting someone off is very hard to undo, so it should "
                      "never be decided in one sitting", {"cut_off": -5.0, "wait": 5.0},
                      ["reversibility"]))
    for kind in ("cancel", "ghosted"):
        n = brief["counts"][kind]
        if n >= PATTERN_MIN:
            days = sorted(e["day"] for e in brief["timeline"] if e["kind"] == kind)[-3:]
            when = ("days " + ", ".join(str(d) for d in days[:-1]) + f" and {days[-1]}"
                    if len(days) > 1 else f"day {days[0]}")
            out.append(_p("repeated_pattern", f"{name} has {KIND_WORDS[kind]} {n} times in the "
                          f"last {PATTERN_DAYS} days (latest {when}): that is a pattern, not a "
                          "one-off", {"talk": 2.0, "let_it_go": -1.0}, ["counts", "timeline"]))
            break
    grudge = status == "strained" and source == "hearsay"
    if grudge:
        out.append(_p("grudge_check", f"what you know about {name} being upset came from someone "
                      "else: check the source before acting on it",
                      {"let_it_go": 1.0, "wait": 1.0, "talk": -1.0}, ["status"]))
    fired = {p["id"] for p in out}
    if status == "strained" and not grudge and "fresh_anger" not in fired and "talk" in opts:
        out.append(_p("cheap_repair", f"things with {name} are strained, and a check-in is cheap "
                      "and easy to follow up", {"talk": 1.0}, ["status", "reversibility"]))
    if brief["promises"]:
        p = brief["promises"][0]
        out.append(_p("honour_promise", f"you promised {name} something (\"{p['text']}\", day "
                      f"{p['made']}): keep that first", {}, ["promises"]))
    for v in brief["values"]:
        lean = {o: w * VALUE_BOOST for o, w in VALUE_LEAN[v["tag"]].items() if o in opts}
        if lean:
            out.append(_p(f"value:{v['tag']}", f"you said you value {VALUE_WORDS[v['tag']]}, and "
                          "that counts more than my own taste", lean, ["values"]))
    for past in brief["past"][:3]:
        if past["result"] in ("good", "bad") and past["pick"] in opts:
            lean = {past["pick"]: 1.0 if past["result"] == "good" else -2.0}
            out.append(_p("past_advice", f"last time you chose to {past['pick'].replace('_', ' ')} "
                          f"(day {past['day']}) it went {past['result']}", lean, ["past"]))
    fired = {p["id"] for p in out}
    if not fired & {"fresh_anger", "irreversible", "repeated_pattern", "grudge_check",
                    "cheap_repair"}:
        out.append(_p("no_pattern", f"nothing in your history with {name} makes this a problem "
                      "so far", {"let_it_go": 1.0}, ["timeline"]))
    return out


def score(brief, principles):
    scores = {o: TIE_ORDER.get(o, 0.0) for o in brief["options"]}
    for p in principles:
        for o, w in p["lean"].items():
            if o in scores:
                scores[o] += w
    return scores


def verdict_of(brief, scores):
    """(verdict, confidence). A small lead is humility: the choice is the user's."""
    ranked = sorted(scores, key=lambda o: -scores[o])
    margin = scores[ranked[0]] - scores[ranked[1]] if len(ranked) > 1 else 99.0
    confidence = "high" if margin >= 3 else "medium" if margin >= 1.5 else "low"
    if margin < HUMILITY_MARGIN and "cut_off" not in brief["options"]:
        return "your_call", "low"
    return ranked[0], confidence


# ---- wording: always available, no LLM ----------------------------------------------------

_HEAD = {"talk": "Talk to {name}.", "wait": "Wait a day before you do anything.",
         "let_it_go": "Let this one go.", "your_call": "This one is your call.",
         "cut_off": "Do not decide that today."}
_MIND = {
    "talk": "If {name} has a good reason this time, or things have already improved, I'd let it go.",
    "wait": "If {name} reaches out first, or you still feel the same tomorrow, talk to them.",
    "let_it_go": "If it happens again soon, or it keeps bothering you, it becomes a pattern worth "
                 "a conversation.",
    "your_call": "More history, or telling me what matters most to you here, would tip it.",
    "cut_off": "If you still feel the same after a few nights and have tried talking, "
               "it is a fair thing to revisit.",
}
_MESSAGE = {
    "cancel": "Hey {name}, plans have fallen through a few times lately. Can we pick a day that "
              "really works for both of us?",
    "ghosted": "Hey {name}, I've missed hearing from you. Is everything okay? No pressure to "
               "reply right away.",
    "argument": "I'd like to talk about what happened. No rush: today or tomorrow, whichever "
                "works for you.",
    None: "Hey {name}, I've been thinking about us. Can we talk when you have a minute?",
}


def _kind_of(brief, kind):
    if kind:
        return kind
    newest = next((e["kind"] for e in brief["timeline"]), None)
    return newest


def first_step(verdict, brief, kind):
    name = brief["contact"]["name"]
    steps = []
    if brief["promises"]:
        steps.append(f"First, keep your promise to {name}: {brief['promises'][0]['text']}.")
    if verdict == "talk":
        msg = _MESSAGE.get(_kind_of(brief, kind), _MESSAGE[None]).format(name=name)
        steps.append(f"Start with something short and warm, like: \"{msg}\"")
        if brief["helpers"]:
            steps.append(f"{brief['helpers'][0]['name']} knows {name} too, if you want a "
                         "friendly go-between.")
    elif verdict == "wait":
        steps.append("Sleep on it; if you still want to raise it tomorrow, do it then.")
    elif verdict == "let_it_go":
        steps.append("If it still bothers you in a week, that is worth raising.")
    elif verdict == "your_call":
        steps.append("Pick the option you could explain to yourself in a month.")
    return " ".join(steps)


def template(result, brief):
    name = brief["contact"]["name"]
    head = _HEAD[result["verdict"]].format(name=name)
    reasons = [r for r in result["reasons"][:2]]
    because = " ".join(f"{r[0].upper()}{r[1:]}." for r in reasons)
    return " ".join(x for x in (
        head, because,
        f"What would change my mind: {_MIND[result['verdict']].format(name=name)}",
        result["first_step"]) if x)


# ---- the checker: nothing in the text that is not in the brief ----------------------------

_EVENT_STEMS = {"cancel": "cancel", "ghost": "ghosted", "gone quiet": "ghosted",
                "argu": "argument", "fight": "argument", "apolog": "apology",
                "helped": "favor", "celebrat": "celebration"}
_STATUS_WORDS = ("strained", "estranged", "fighting", "angry", "upset", "furious")
_BANNED = re.compile(r"\b(narcissis\w*|toxic|manipulat\w*|gaslight\w*|bipolar|depress\w*|"
                     r"abusive|sociopath|psychopath|disorder|diagnos\w*|mentally ill)\b", re.I)
_VERDICT_MARK = {"talk": "talk to", "wait": "wait", "let_it_go": "let", "your_call": "your call",
                 "cut_off": "decide"}


def brief_days(brief):
    days = {brief["day"]}
    days |= {e["day"] for e in brief["timeline"]}
    days |= {p["made"] for p in brief["promises"]}
    days |= {p["day"] for p in brief["past"]}
    days |= {v["since"] for v in brief["values"]}
    if brief["status"]:
        days.add(brief["status"].get("since"))
    return days


def grounded(text, brief, verdict=None):
    """True only if every person, day, event and status in the text exists in the brief,
    nothing diagnoses anyone, and the verdict comes first."""
    low = text.lower()
    if _BANNED.search(low):
        return False
    if verdict and _VERDICT_MARK[verdict] not in low[:90]:
        return False
    allowed_days = brief_days(brief)
    for group in re.findall(r"\bdays? (\d+(?:(?:, | and |, and )\d+)*)", low):
        if any(int(d) not in allowed_days for d in re.findall(r"\d+", group)):
            return False
    kinds = {e["kind"] for e in brief["timeline"]} | {k for k, n in brief["counts"].items() if n}
    for stem, kind in _EVENT_STEMS.items():
        if stem in low and kind not in kinds:
            return False
    status = (brief["status"] or {}).get("value")
    recent_argument = brief["fresh_argument"] or "argument" in kinds
    for word in _STATUS_WORDS:
        if re.search(rf"\b{word}\b", low) and not (status == "strained" or recent_argument):
            return False
    own = brief["contact"]["name"].lower()
    for other in tools.list_contacts(brief.get("_user", "")) if brief.get("_user") else []:
        if other["name"].lower() != own and re.search(rf"\b{re.escape(other['name'].lower())}\b", low):
            return False
    return True


def _llm_text(result, brief, user):
    brief_json = json.dumps({k: v for k, v in brief.items() if k != "_user"}, default=str)
    base = ("You are a warm, direct friend giving advice. A decision has ALREADY been made by code; "
            "do not change it. Write 3 to 5 sentences. Start with the verdict. Give two reasons that "
            "cite items in the brief, then what would change your mind, then what to say or do "
            "first. Use ONLY facts in the brief: no new people, days, events or feelings. Never "
            "diagnose anyone or judge their character.\n"
            f"Verdict: {result['verdict']} ({_HEAD[result['verdict']].format(name=brief['contact']['name'])})\n"
            f"Reasons to use: {json.dumps(result['reasons'][:2])}\n"
            f"What would change my mind: {_MIND[result['verdict']].format(name=brief['contact']['name'])}\n"
            f"First step: {result['first_step']}\nBrief: {brief_json}")
    for attempt in range(2):  # regenerate once, then fall back
        try:
            text = llm.ask(base + ("" if attempt == 0 else "\nYour previous answer broke the rules; "
                                   "stick strictly to the brief.")).strip()
        except llm.LLMUnavailable:
            return None
        if text and grounded(text, {**brief, "_user": user}, result["verdict"]):
            return text
    return None


# ---- the whole thing ------------------------------------------------------------------------

def counsel(user, cid, day, kind=None, options=OPTIONS, use_llm=True, status=_UNSET, record=True):
    brief = build_brief(user, cid, day, options, status)
    principles = fire(brief)
    scores = score(brief, principles)
    verdict, confidence = verdict_of(brief, scores)
    reasons = [p["why"] for p in sorted(principles, key=_priority) if p["why"]]
    result = {
        "verdict": verdict, "confidence": confidence, "scores": scores,
        "principles": [p["id"] for p in principles], "reasons": reasons,
        "first_step": first_step(verdict, brief, kind),
        "change_my_mind": _MIND[verdict].format(name=brief["contact"]["name"]),
        "brief": brief, "source": "template",
    }
    text = None
    if use_llm and llm.mode() != "off":
        text = _llm_text(result, brief, user)
        if text:
            result["source"] = "llm"
    result["text"] = text or template(result, brief)
    if record:
        status_ids = [brief["status"]["id"]] if brief["status"] else []
        value_ids = [v["id"] for v in brief["values"]
                     if f"value:{v['tag']}" in result["principles"]]
        result["decision_id"] = tools.record_counsel(
            user, day, verdict, brief["options"], status_ids, cid, value_ids, scores,
            result["principles"])
    return result


_PRIORITY = ["irreversible", "fresh_anger", "repeated_pattern", "grudge_check", "cheap_repair",
             "honour_promise", "past_advice", "no_pattern"]


def _priority(p):
    pid = p["id"]
    return (_PRIORITY.index(pid) if pid in _PRIORITY else 4.5, pid)
