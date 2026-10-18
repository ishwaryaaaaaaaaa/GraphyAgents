"""People grammar: sentences about friends -> memory operations, and routing for questions.

Works on the ORIGINAL-case text because names matter ("Priya cancelled"). A contact is created
only from an introduction ("my friend Priya ..."); an unknown capitalised name next to a social
verb is reported, never silently turned into a person.
"""
import re

from agent import schema

NAME = r"[A-Z][a-z]{1,20}"
RELATION = "|".join(schema.RELATIONS)
_VERBS = [
    ("cancel", r"cancell?ed|called off|bailed|flaked|cancels"),
    ("ghosted", r"ghosted|stopped replying|left me on read|ignored me|went quiet"),
    ("apology", r"apologi[sz]ed|said sorry"),
    ("favor", r"helped me|did me a favou?r|covered for me"),
    ("celebration", r"celebrated with me|threw me a party|remembered my birthday"),
]
_TONE = {"cancel": "neutral", "ghosted": "cold", "apology": "warm", "favor": "warm",
         "celebration": "warm", "argument": "tense", "made_up": "warm"}
_VERB_RE = "|".join(f"(?:{v})" for _, v in _VERBS)
_TIME = [(re.compile(r"\byesterday\b", re.I), 1), (re.compile(r"\blast week\b", re.I), 7),
         (re.compile(r"\b(\d{1,3}) days? ago\b", re.I), None)]
_VALUES = [("honesty", r"honest\w*|truth"), ("show_up", r"shows? up|showing up|reliable|dependable"),
           ("peace", r"peace\w*|calm"), ("self_respect", r"respect myself|self[- ]respect"),
           ("loyalty", r"loyal\w*")]
_QUESTION = re.compile(r"\?\s*$|\b(should i|what should i|do i|shall i|is it ok|is it okay)\b", re.I)
_CUT = re.compile(r"\b(cut (?:\w+ )?off|cut off|end (?:the|my|our) friendship|end it with|"
                  r"stop talking to|block (?:\w+)|cut ties|unfriend|never speak to)\b", re.I)


def find_contact(text, contacts):
    """The known contact named in the text (case-insensitive), or None."""
    for name in sorted(contacts, key=len, reverse=True):
        if re.search(rf"\b{re.escape(name)}\b", text, re.I):
            return name
    return None


def detect_kind(text):
    low = text.lower()
    if re.search(r"\b(made up|patched things up|good again|made peace)\b", low):
        return "made_up"
    if re.search(r"\b(argu\w+|fought|fight|fell out|row)\b", low):
        return "argument"
    for kind, verbs in _VERBS:
        if re.search(verbs, low):
            return kind
    return None


def strip_time(clause):
    for rx, fixed in _TIME:
        m = rx.search(clause)
        if m:
            return rx.sub("", clause).strip(), (fixed if fixed is not None else int(m[1]))
    return clause, 0


def _op(op, **kw):
    return {"op": op, "confidence": 1.0, **kw}


def _cid(name):
    return "".join(ch for ch in name.lower() if ch.isalnum())


def _status(name, value, source="typed"):
    return _op("set_fact", key=f"contact:{_cid(name)}:status", value=value, source=source)


def clause_ops(clause, contacts):
    """(ops, errors, handled) for one clause. handled=True stops the food grammar from
    misreading a sentence about a person."""
    text, days_ago = strip_time(clause.strip(" .!?"))
    ops, errors = [], []

    # values need no contact
    m = re.search(r"\bI (?:value|care about|believe in)\b|\bI want to be (?:someone|a person|the kind of "
                  r"(?:person|friend)) who\b", text)
    if m:
        for tag, words in _VALUES:
            if re.search(words, text, re.I):
                ops.append(_op("add_value", tag=tag, text=text[:100]))
                return ops, errors, True
        return [], ["I couldn't tell which value that is (honesty, showing up, peace, self-respect, "
                    "loyalty)"], True

    intro = re.search(rf"\bmy (?P<rel>{RELATION}) (?P<name>{NAME})\b", text)
    name = None
    if intro:
        name = intro["name"]
        ops.append(_op("add_contact", name=name, relation=intro["rel"]))
    else:
        known = find_contact(text, contacts)
        name = known
    if name is None:
        unknown = re.match(rf"^(?P<name>{NAME})\b (?:{_VERB_RE}|moved to\b)", text) or \
            re.match(rf"^(?:I (?:had|got into) (?:an? )?(?:argument|fight) with|I fell out with) "
                     rf"(?P<name>{NAME})\b", text)
        if unknown:
            return [], [f"Who is {unknown['name']}? Tell me with 'my friend {unknown['name']} ...' "
                        "so I know who they are"], True
        return [], [], False
    cid = _cid(name)

    def add(*new):
        for o in new:
            ops.append({**o, "days_ago": days_ago})

    if re.search(r"\bthat was wrong about\b", text, re.I):
        add(_op("retract_fact", key=f"contact:{cid}:status", reason="user said it was wrong"))
    elif detect_kind(text) == "made_up" and re.search(r"\b(made up|patched|good again|made peace)\b", text, re.I):
        add(_op("log_interaction", contact=cid, kind="made_up", tone="warm", what="made up"),
            _status(name, "fine"))
    elif re.search(rf"\bI heard {name} is (?:angry|upset|mad|annoyed|cross)\b", text, re.I) or \
            re.search(rf"\b{name} (?:is|seems|might be) (?:angry|upset|mad|annoyed) (?:at|with) me\b", text,
                      re.I) and re.search(r"\b(heard|told me|someone said)\b", text, re.I):
        add(_status(name, "strained", "hearsay"))
    elif detect_kind(text) == "argument":
        add(_op("log_interaction", contact=cid, kind="argument", tone="tense", what="argued"),
            _status(name, "strained"))
    elif re.search(rf"\b{name} moved to ([A-Z][A-Za-z ]{{1,29}})$", text):
        city = re.search(rf"\b{name} moved to ([A-Z][A-Za-z ]{{1,29}})$", text)[1].strip()
        add(_op("set_fact", key=f"contact:{cid}:city", value=city))
    elif re.search(rf"\bI promised {name}\b", text):
        what = re.sub(rf"^.*?\bI promised {name}\s*(?:to\s+)?", "", text).strip()
        if what:
            add(_op("make_promise", text=what, tag="social", contact=cid))
        else:
            errors.append("what did you promise?")
    else:
        kind = detect_kind(text)
        if kind:
            add(_op("log_interaction", contact=cid, kind=kind, tone=_TONE[kind], what=text[:80]))
        elif not ops:
            return [], [], False  # a known name, but nothing we understand: let other readers try
    return ops, errors, True


def unknown_person(text, contacts):
    """'Bob cancelled again, should I...?' where nobody has told us who Bob is: his name, else None."""
    m = re.match(rf"^(?P<name>{NAME})\b (?:{_VERB_RE}|moved to\b)", text)
    if m and find_contact(text, contacts) is None and _QUESTION.search(text):
        return m["name"]
    return None


def situation(text, contacts):
    """Is this a question about a person? Returns {"contact", "kind", "options"} or None.
    Needs a known contact and a question; 'cut off' style asks add the irreversible option."""
    name = find_contact(text, contacts)
    intro = re.search(rf"\bmy (?P<rel>{RELATION}) (?P<name>{NAME})\b", text)
    if not _QUESTION.search(text) or (name is None and intro is None):
        return None
    options = ["talk", "wait", "let_it_go"]
    if _CUT.search(text):
        options.append("cut_off")
    return {"contact": name or intro["name"], "kind": detect_kind(text), "options": options,
            "intro": (intro["name"], intro["rel"]) if intro and name is None else None}
