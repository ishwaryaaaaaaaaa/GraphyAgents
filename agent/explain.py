"""Decision -> a short plain-language why.

The LLM may only reword what the decision object already says. Its sentence is checked
afterwards: any food, fact word, number or medical-sounding claim that is not in the
decision throws the text away and the template sentence is used instead. The template is
always available, so the agent still explains itself with the LLM off.
"""
import json
import re

from agent import decide, llm, tools

FACT_WORDS = ("vegetarian", "non_veg", "non-veg", "hostel", "flat", "sugar", "fried", "meat",
              "vegan")
MEDICAL = re.compile(r"\b(unsafe|dangerous|diabet\w*|disease|cholesterol|doctor|medical|"
                     r"medicine|cure|allerg\w*|toxic|harmful)\b")


def pretty(name):
    return name.replace("_", " ")


def history_notes(user, decision):
    """'you said vegetarian on day 10; before that non_veg' for each consulted fact that changed."""
    did = decision.get("decision_id")
    audit = tools.explain_decision(user, did) if did else None
    notes = []
    for used in (audit or {}).get("used", []):
        hist = [h for h in used["history"] if h["status"] != "retracted"]
        if len(hist) > 1 and hist[-1]["id"] == used["id"]:
            notes.append(f"you said {pretty(str(used['value']))} on day {hist[-1]['valid_from']}; "
                         f"before that {pretty(str(hist[-2]['value']))}")
    return notes


def template(decision, notes=()):
    """Verdict first, then at most two reasons, then (if relevant) the history."""
    if decision["pick"] == "none":
        rej = "; ".join(f"{pretty(k)}: {v}" for k, v in decision["rejected"].items())
        return f"None of those work right now ({rej}). What else is available?"
    text = f"{pretty(decision['pick'])}."
    if decision["reasons"]:
        text += " " + "; ".join(decision["reasons"][:2]) + "."
    if notes:
        text += f" ({notes[0]})"
    return text


def _blob(decision, notes):
    parts = [decision["pick"], *decision["reasons"], *notes,
             *decision["rejected"].keys(), *decision["rejected"].values(),
             *decision.get("scores", {}).keys()]
    return " ".join(pretty(str(p)).lower() for p in parts)


def grounded(text, decision, notes=()):
    """True only if the text mentions nothing that is not in the decision object."""
    low = text.lower()
    blob = _blob(decision, notes)
    if MEDICAL.search(low):
        return False
    known = {pretty(n) for n in [decision["pick"], *decision["rejected"],
                                 *decision.get("scores", {})]}
    for name in decide.CATALOGUE:
        phrase = pretty(name)
        if re.search(rf"\b{re.escape(phrase)}\b", low) and phrase not in known:
            return False
    for word in FACT_WORDS:
        w = pretty(word).replace("non-veg", "non veg")
        if re.search(rf"\b{re.escape(w)}\b", low) and w not in blob.replace("non-veg", "non veg"):
            return False
    return all(n in re.findall(r"\d+", blob) for n in re.findall(r"\d+", low))


def explain(user, decision, use_llm=True):
    notes = history_notes(user, decision)
    fallback = template(decision, notes)
    if not use_llm or llm.mode() == "off" or decision["pick"] == "none":
        return fallback
    facts = {"pick": decision["pick"], "reasons": decision["reasons"],
             "rejected": decision["rejected"], "history": notes}
    prompt = ("Write at most two sentences. Say the verdict first. Use only the reasons and "
              "values given. Do not add any fact, food, number or health claim.\n"
              f"Decision: {json.dumps(facts)}")
    try:
        text = llm.ask(prompt).strip()
    except llm.LLMUnavailable:
        return fallback
    return text if text and grounded(text, decision, notes) else fallback
