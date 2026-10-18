"""Command-line chat with the decision agent.

    python cli.py --user meera           interactive
    python cli.py --user meera --yes     apply confident changes without asking

Tell it things ("I turned vegetarian last week and I'm off sugar from today"), ask it
forks ("gulab jamun or chana chaat?", "can I have ice cream?"), and ask why (/why).
Time is a simulation day you move yourself with /next or /day N.
"""
import argparse
import difflib
import re
import sys

from agent import counsel, decide, explain, extract, learn, social, store, tools

HELP = """tell me things, or ask a fork:  'dessert or skip?'  'can I have ice cream?'
people:  'my friend Priya cancelled again, should I say something?'  'Priya and I made up'
         'I want to be someone who shows up'   /people   /values
         I weigh your history, your values and how earlier advice went; the choice stays yours.
/outcome good|mixed|bad [id]   how my advice went: I learn what matters to YOU from bad ones
/weights [rule]  what I have learned about you   /next  next day      /day N  jump to day N
/facts           what is true now             /history K  every value a slot has held
/at K DAY        what was true on that day    /why [id]   audit trail of a decision
/goals           active goals, ranked         /streak T   clean days for a tag (e.g. sugar)
/clean           log a clean sugar day        /reset      wipe this user's memory
/user NAME       switch person                /quit"""

_FORK_PREFIX = re.compile(r"^(?:/ask\s+|should i (?:eat|have|do|pick)\s+|what should i (?:eat|do)[:,]?\s*"
                          r"|can i (?:have|eat)\s+|may i have\s+|what about\s+|pick between\s+)", re.I)


def _unknown_option(raw, key):
    """Never invent an option; point at real ones instead."""
    by_tag = [n for n, i in decide.CATALOGUE.items() if key in i["tags"]]
    close = difflib.get_close_matches(key, decide.CATALOGUE, n=3, cutoff=0.6)
    hint = by_tag[:5] or close
    msg = f"Okay, I haven't learned {raw!r} yet, so I can't weigh it."
    return msg + (f" Try: {', '.join(h.replace('_', ' ') for h in hint)}." if hint else "")


def parse_fork(line):
    """Return (option_names, add_skip) if the line is a fork over known items, else None.
    Raises ValueError naming an unknown item so the agent never invents options."""
    text = line.strip().rstrip("?").strip()
    if not (line.strip().endswith("?") or text.lower().startswith("/ask")):
        return None
    single = bool(re.match(r"^(?:can i|may i|should i)\b", text, re.I)) \
        and " or " not in text.lower()
    body = _FORK_PREFIX.sub("", text, count=1)
    parts = [p.strip() for p in re.split(r"\s+or\s+|\s+vs\.?\s+|,", body, flags=re.I) if p.strip()]
    if not parts:
        return None
    names = []
    for p in parts:
        key = re.sub(r"\s+", "_", re.sub(r"[^a-z ]", " ", p.lower()).strip())
        if key == "skip" or key in decide.CATALOGUE:
            names.append(key)
        elif key.rstrip("s") in decide.CATALOGUE:
            names.append(key.rstrip("s"))
        else:
            raise ValueError(_unknown_option(p, key))
    if len(names) == 1 and not single:
        return None
    return names, single or len(names) == 1


REMEMBER_GUIDE = (
    "Here is what I'm good at remembering. Say it in your own words, for example:\n"
    "  - food: \"I eat meat\", \"I'm vegetarian\", \"I love samosa\", \"I hate pasta\"\n"
    "  - goals: \"I want to cut sugar\", \"I stayed off sugar today\"\n"
    "  - promises: \"I promise to study tonight\"\n"
    "  - people: \"my friend Sam cancelled again, should I say something?\"\n"
    "I know foods like pasta, samosa, ice cream, paneer wrap, masala dosa, fried chicken, sprouts, "
    "salad bowl and chana chaat (44 in all). Then ask me to choose, like \"pasta or sprouts?\"")


def _say(op, line):
    """One friendly sentence for one memory update. `line` is the engine's plain result for it."""
    m = re.match(r"I don't know (\w+) yet", line)
    if m:
        return f"I haven't met {m[1]} yet, so I skipped that."
    if line.startswith(("no open", "no active")):
        return "There was nothing like that open, so I left it alone."
    k = op["op"]
    if k == "set_fact":
        key, value = op["key"], op["value"]
        if key == "diet_style":
            return {"non_veg": "Got it, you eat meat.",
                    "vegetarian": "Got it, you're vegetarian now."}.get(
                        value, f"Got it, you're {value.replace('_', ' ')}.")
        if key.startswith("likes:"):
            food = key.split(":", 1)[1].replace("_", " ")
            return f"Nice, I'll remember you love {food}." if value == "yes" else \
                f"Okay, noted that you're not into {food} anymore."
        if key.startswith("dislikes:"):
            return f"Understood, you don't like {key.split(':', 1)[1].replace('_', ' ')}."
        if key == "lives_in":
            return f"Got it, you're living in the {value} now."
        if key.startswith("contact:") and key.endswith(":status"):
            return f"Okay, things with {key.split(':')[1].title()} are {value} right now."
        if key.startswith("contact:") and key.endswith(":city"):
            return f"Okay, {key.split(':')[1].title()} lives in {value}."
        return f"Got it, your {key.replace('_', ' ')} is {value}."
    if k == "retract_fact":
        return "No problem, I've taken that back and I won't use it any more."
    if k == "start_goal":
        return f"Good call. I'll keep your {op['tag']} goal in mind."
    if k == "end_goal":
        return f"Okay, I've closed your {op['tag']} goal."
    if k == "log_event":
        return {"clean_day": "Nice work, that's a good day to have on record.",
                "slip": "That's okay, everyone slips. I've noted it."}.get(
                    op["kind"], "Okay, I've noted that.")
    if k == "make_promise":
        return f"Okay, I'll remember you promised to {op['text']}."
    if k == "mark_promise":
        return "Well done for keeping your promise." if op["status"] == "kept" else \
            "Thanks for being honest about that. I've noted it."
    if k == "add_contact":
        return f"Nice, I'll remember {op['name'].title()} is your {op['relation']}."
    if k == "log_interaction":
        return f"Thanks for telling me. I've noted that {line}."
    if k in ("add_value", "end_value"):
        return "That says a lot about you. I'll keep it in mind." if k == "add_value" else \
            "Okay, I'll stop treating that as one of your values."
    return "Got it."


def _friendly(ops, lines):
    """Talk back like a person: what was understood, in plain sentences, then the exact details saved."""
    said = [_say(o, ln) for o, ln in zip(ops, lines)] if len(ops) == len(lines) else ["Got it."]
    if any("no longer true" in ln for ln in lines):
        said.append("I've set aside the older version, so I won't use it for decisions.")
    return " ".join(said) + " (saved: " + "; ".join(lines) + ".)"


_FEELING = (r"i(?: am|'m| feel| am feeling|'m feeling)(?: so| really| very| a bit| kind of| just)? "
            r"(sad|anxious|stressed|tired|overwhelmed|nervous|worried|lonely|upset|angry|scared|"
            r"confused|low|exhausted|down|burnt out|burned out)")
_WHAT_I_DO = ("I'm Decisive, a decision partner with a memory. Tell me about your life in plain words "
              "(what you eat, your goals, your friends). When you ask me to choose, I only use what is "
              "true today, and I show you the facts I used. Try \"I turned vegetarian\", then "
              "\"what should I eat?\".")


class Session:
    def __init__(self, user="you", day=1, auto=False, mode="rules"):
        self.user, self.day, self.auto, self.mode = user, day, auto, mode
        self.pending = []
        self.asked = set()
        self.last_decision = None
        store.ensure_user(user)

    # -- helpers --
    def _apply(self, ops):
        return _friendly(ops, extract.apply_ops(self.user, ops, self.day))

    def _ask(self, names, add_skip):
        res = decide.decide(self.user, self.day, names, add_skip=add_skip, mode=self.mode)
        self.last_decision = res
        return explain.explain(self.user, res) + f"   [{res['decision_id']}: /why]"

    def _pending_note(self):
        """Ask how a decision went, once per decision (not on every day jump)."""
        pending = [d for d in tools.pending_outcomes(self.user, self.day)
                   if d["id"] not in self.asked]
        if not pending:
            return ""
        d = pending[-1]
        self.asked.update(p["id"] for p in pending)
        more = f" (+{len(pending) - 1} earlier)" if len(pending) > 1 else ""
        return (f"\nHow did {d['id']} go ({d['pick'].replace('_', ' ')}, day {d['day']})?{more} "
                f"/outcome good|mixed|bad {d['id']}")

    def _outcome(self, args):
        if not args or args[0] not in ("good", "mixed", "bad"):
            return "Usage: /outcome good|mixed|bad [decision id]"
        did = args[1] if len(args) > 1 else (self.last_decision or {}).get("decision_id")
        if not did:
            pending = tools.pending_outcomes(self.user, self.day + 1)
            did = pending[-1]["id"] if pending else None
        if not did:
            return "No decision to rate yet."
        try:
            res = learn.apply_outcome(self.user, did, args[0], self.day)
        except (KeyError, ValueError) as e:
            return f"Can't record that: {e.args[0]}"
        dec = tools.get_decision(self.user, did)
        if dec and dec["mode"] == "counsel":
            return (f"Noted {did} as {args[0]} ({res['outcome_id']}). I'll remember how this went "
                    f"with {dec['contact'].title()} next time.")
        if not res["changes"]:
            why = "nothing to change" if args[0] != "bad" else "no rule separated my pick from the other option"
            return f"Noted {did} as {args[0]} ({res['outcome_id']}): {why}."
        moved = "; ".join(f"{c['rule']} {c['old']:.2f} -> {c['new']:.2f}" for c in res["changes"])
        return (f"Noted {did} as bad ({res['outcome_id']}). I'll weigh things differently for you "
                f"(compared with {res['against'].replace('_', ' ')}): {moved}.")

    def _weights(self, rule=None):
        w = tools.get_weights(self.user)
        if rule:
            hist = tools.weight_history(self.user, rule)
            if not hist:
                return f"{rule}: x1.00, never adjusted."
            return f"{rule}: x{w.get(rule, 1.0):.2f}\n" + "\n".join(
                f"  {h['outcome']} (day {h['day']}, {h['result']}): {h['delta']:+.2f} -> x{h['mult']:.2f}"
                for h in hist)
        return "\n".join(f"{r:13} x{w.get(r, 1.0):.2f}" + ("" if r in w else "  (default)")
                         for r in decide.LEARNABLE)

    def _contact_names(self):
        return [c["name"] for c in tools.list_contacts(self.user)]

    def _counsel(self, sit):
        """Advice about a person. Facts stated in the same sentence ('Priya cancelled again')
        are recorded first, because the user told us them while asking."""
        notes = []
        if sit["intro"]:
            name, rel = sit["intro"]
            notes += extract.apply_ops(self.user, [
                {"op": "add_contact", "name": name, "relation": rel, "confidence": 1.0,
                 "days_ago": 0}], self.day)
        got = extract.extract(sit["text"], self.day, contacts=self._contact_names())
        stated = [o for o in got["ops"] if o["op"] in ("log_interaction", "set_fact")
                  and (o["op"] == "log_interaction" or o["key"].startswith("contact:"))]
        notes += extract.apply_ops(self.user, stated, self.day)
        cid = store.contact_id(sit["contact"])
        if not tools.get_contact(self.user, cid):
            return f"Okay, I haven't met {sit['contact']} yet. Tell me who they are first, like 'my friend {sit['contact']} ...'"
        res = counsel.counsel(self.user, cid, self.day, kind=sit["kind"], options=sit["options"])
        self.last_decision = {"decision_id": res["decision_id"], "pick": res["verdict"]}
        head = f"Thanks for telling me. I've noted: {'; '.join(notes)}.\n" if notes else ""
        head = head.replace("noted: noted", "noted")
        return (f"{head}{res['text']}\n[{res['decision_id']}: confidence {res['confidence']}; "
                f"/why, then /outcome good|mixed|bad later]")

    def _people(self):
        contacts = tools.list_contacts(self.user)
        if not contacts:
            return "(nobody yet: tell me about someone, e.g. 'my friend Priya cancelled again')"
        ranks = tools.rank_contacts(self.user)
        lines = []
        for c in contacts:
            st = tools.get_fact_meta(self.user, f"contact:{c['id']}:status", self.day)
            last = tools.contact_timeline(self.user, c["id"], 1, self.day)
            city = tools.get_fact_meta(self.user, f"contact:{c['id']}:city", self.day)
            lines.append(f"{c['name']} ({c['relation']})"
                         + (f", status {st['value']}" if st else "")
                         + (f", lives in {city['value']}" if city else "")
                         + (f", last: {last[0]['kind'].replace('_', ' ')} on day {last[0]['day']}"
                            if last else "")
                         + (f", centrality {ranks[c['id']]:.2f}" if c["id"] in ranks else ""))
        return "\n".join(lines)

    def _converse(self, line):
        """Talk like a person when the message is not something to remember: greetings, thanks, what can
        you do, an open "what should I eat?" (answered from memory), feelings, other questions. Returns
        None when nothing fits, and the caller falls back to the guide."""
        t = re.sub(r"\s+", " ", line.lower().strip(" .!?"))
        facts = tools.get_facts(self.user, self.day)
        diet = (facts.get("diet_style") or (None,))[0]
        known = {"non_veg": " I remember you eat meat.", "vegetarian": " I remember you're vegetarian."}.get(diet, "")
        if re.fullmatch(r"(?:hi+|hello+|hey+|hiya|yo|hey there|hi there|hello there|good (?:morning|afternoon|evening|night))", t):
            return "Hey! Good to see you." + (known or " Tell me one thing about yourself, or ask me to choose between two things.")
        if re.fullmatch(r"(?:thanks|thank you|thx|ty|thanks a lot|thank you so much|thanks so much)", t):
            return "Anytime! If a choice turns out well or badly, tell me, and I'll learn from it."
        if re.fullmatch(r"(?:how are you|how are you doing|how's it going|what's up|sup|how do you do)", t):
            return "I'm doing well, thanks for asking! Mostly I'm waiting to hear how your day is going. What's on your mind?"
        if re.search(r"\b(?:who|what) (?:are|is) (?:you|this)\b|what can you do|what do you do|how does (?:this|it) work|"
                     r"^help(?: me)?$|tell me about yourself|can you help", t):
            return _WHAT_I_DO
        if re.search(r"\b(?:what|which)\b.*\b(?:should|shall|can|could)\b.*\b(?:i|we)\b.*\b(?:eat|have|order|cook|get|snack)\b|"
                     r"\bwhat to (?:eat|order|have|cook)\b|\b(?:i am|i'm) (?:so |very |really )?(?:hungry|starving)\b|"
                     r"\bsuggest\b.*\b(?:food|meal|snack|dinner|lunch|breakfast|dessert)\b|\b(?:dinner|lunch|snack) ideas\b|"
                     r"\bi want (?:to eat )?something\b", t):
            tag = "dessert" if re.search(r"dessert|sweet", t) else "snack" if "snack" in t else "meal"
            names = [n for n, i in decide.CATALOGUE.items() if tag in i["tags"] and "requires" not in i]
            intro = "" if facts else "I don't know much about you yet, so this is a general pick. "
            return intro + self._ask(names, False)
        m = re.search(_FEELING, t)
        if m:
            return (f"That sounds heavy, and I'm glad you told me. I can't help with feeling {m[1]} the way a good "
                    "friend can, but I'm listening. If something happened with someone, tell me about them "
                    "(\"my friend Sam ...\") and I'll help you think it through.")
        if line.strip().endswith("?") or re.match(r"(?:should|could|would|can|is|am|do|does|will|why|how|when|where|who)\b", t):
            notes = [v[0] for k, v in facts.items() if k.startswith("note:")][-5:]
            ctx = (" What I know about you so far: " + "; ".join(notes) + ". I can't weigh that against it yet, "
                   "but tell me more and I'll keep it all in mind.") if notes else ""
            return ("Good question. I can't answer that one, because I only weigh food choices and friendships. "
                    "If you're choosing between two things I know, ask like \"pasta or sprouts?\". If it's about "
                    "a friend, tell me what happened." + ctx)
        if re.match(r"(?:i am|i'm|i have|i work|i study|i live|i go|i was|i got|i like|i love|i prefer|i usually|i always|"
                    r"i never|i need|i want|my name is|my )", t):
            # Not something the decision rules use, but still part of who you are: keep it as a note.
            text = line.strip().rstrip(".!")[:100]
            slug = re.sub(r"[^a-z0-9]+", "_", t).strip("_")[:40]
            store.set_fact(self.user, f"note:{slug}", text, self.day, source="typed", confidence=1.0)
            return (f"Got it, I'll remember that: \"{text}\". I can't use it to make food or friend decisions "
                    "yet, but it is saved in your memory (see the Memory page).")
        return None

    def _tell(self, line):
        got = extract.extract(line, self.day, contacts=self._contact_names())
        msgs = [f"(skipped: {e})" for e in got["errors"]]
        if not got["ops"]:
            if got["errors"] and any("haven't learned" in e for e in got["errors"]) and re.match(
                    r"i (?:really )?(?:like|love|enjoy|hate|dislike|prefer)", line.lower().strip()):
                text = line.strip().rstrip(".!")[:100]       # a food I cannot weigh: keep it as a note
                slug = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")[:40]
                store.set_fact(self.user, f"note:{slug}", text, self.day, source="typed", confidence=1.0)
                return (f"Got it, I'll remember that: \"{text}\". It isn't one of the 44 foods I can weigh yet, so I "
                        "won't use it to choose, but it is saved in your memory.")
            said = None if got["errors"] else self._converse(line)
            if said:
                return said
            return "\n".join(msgs + ["Okay, fair enough! I can't turn that into something I remember yet, but I'm happy to listen.", REMEMBER_GUIDE])
        sure, unsure = extract.split_by_confidence(got["ops"])
        if unsure:
            self.pending = unsure + ([] if self.auto else sure)
            what = " and ".join(extract.describe(o) for o in self.pending)
            msgs.append(f"Did you mean: {what}? Nothing written yet. (y/n)")
            if self.auto and sure:
                msgs.append(self._apply(sure))
            return "\n".join(msgs)
        if self.auto:
            return "\n".join(msgs + [self._apply(sure)])
        self.pending = sure
        what = " and ".join(extract.describe(o) for o in sure)
        return "\n".join(msgs + [f"I'll {what}. OK? (y/n)"])

    # -- commands --
    def _command(self, line):
        cmd, *args = line.split()
        if cmd == "/help":
            return HELP
        if cmd == "/next":
            self.day += 1
            return f"Okay, it's day {self.day} now." + self._pending_note()
        if cmd == "/day" and args and args[0].isdigit():
            self.day = int(args[0])
            return f"Okay, it's day {self.day} now." + self._pending_note()
        if cmd == "/people":
            return self._people()
        if cmd == "/values":
            vals = tools.values(self.user)
            return "\n".join(f"{v['tag'].replace('_', ' ')} (since day {v['since']})"
                             for v in vals) or "(none yet: say 'I value honesty')"
        if cmd == "/outcome":
            return self._outcome(args)
        if cmd == "/weights":
            return self._weights(args[0] if args else None)
        if cmd == "/user" and args:
            self.__init__(args[0], self.day, self.auto, self.mode)
            return f"Switched to {self.user}."
        if cmd == "/reset":
            store.reset(self.user)
            store.ensure_user(self.user)
            return "Memory wiped."
        if cmd == "/facts":
            facts = tools.get_facts(self.user, self.day)
            return "\n".join(f"{k} = {v}  ({i})" for k, (v, i) in facts.items()) or "(nothing yet)"
        if cmd == "/history" and args:
            rows = tools.fact_history(self.user, args[0])
            return "\n".join(f"{h['value']}  [{h['status']}]  day {h['valid_from']}"
                             f"{'-' + str(h['valid_to']) if h['valid_to'] is not None else '-now'}"
                             for h in rows) or "(never set)"
        if cmd == "/at" and len(args) == 2 and args[1].isdigit():
            return f"{args[0]} on day {args[1]}: {tools.get_fact_at(self.user, args[0], int(args[1]))}"
        if cmd == "/goals":
            ranks = tools.rank_goals(self.user)
            goals = tools.get_active_goals(self.user)
            return "\n".join(f"{g['tag']} since day {g['since']}  rank {ranks.get(g['tag'], 0):.2f}"
                             for g in goals) or "(no active goals)"
        if cmd == "/streak" and args:
            return f"{args[0]}: {tools.count_streak(self.user, args[0], self.day)} clean days"
        if cmd == "/clean":
            store.log_event(self.user, "clean_day", "stayed off sugar", "sugar", self.day)
            return f"Logged a clean sugar day for day {self.day}."
        if cmd == "/why":
            did = args[0] if args else (self.last_decision or {}).get("decision_id")
            audit = tools.explain_decision(self.user, did) if did else None
            if not audit:
                return "No decision to explain yet."
            lines = [f"{audit['decision_id']} (day {audit['day']}): picked {audit['pick']} "
                     f"from {audit['options']}",
                     f"graph path Person -> Decision: length {audit['path_length']}"]
            for u in audit["used"]:
                chain = " -> ".join(f"{h['value']}[{h['status']}]" for h in u["history"])
                lines.append(f"used {u['key']} = {u['value']}   history: {chain}")
            if audit["mode"] == "counsel":
                lines.append(f"advice about {audit['contact']}; principles that fired: "
                             f"{', '.join(audit['rules']) or 'none'}"
                             + (f"; your values applied: {', '.join(audit['values_applied'])}"
                                if audit["values_applied"] else ""))
            if not audit["used"]:
                lines.append("used no stored facts")
            return "\n".join(lines)
        return "Unknown command. /help"

    def handle(self, line):
        line = line.strip().lstrip("﻿")
        if not line:
            return ""
        if counsel.crisis_check(line):  # danger stops the normal flow, before anything else
            self.pending = []
            return counsel.CRISIS_MESSAGE
        if self.pending:
            ops, self.pending = self.pending, []
            if line.lower() in ("y", "yes"):
                return self._apply(ops)
            if line.lower() in ("n", "no"):
                return "OK, nothing written."
            reply = self.handle(line)  # anything else moves on, but say what was dropped
            return "(I did not write: " + " and ".join(extract.describe(o) for o in ops) + ")\n" + reply
        if line.startswith("/") and not line.lower().startswith("/ask"):
            return self._command(line)
        stranger = social.unknown_person(line, self._contact_names())
        if stranger:
            return (f"Who is {stranger}? Tell me with 'my friend {stranger} ...' so I know who "
                    "they are.")
        sit = social.situation(line, self._contact_names())  # people before food: a question
        if sit:                                              # about Priya is not a fork of items
            return self._counsel({**sit, "text": line})
        try:
            fork = parse_fork(line)
        except ValueError as e:
            if " or " not in line.lower():           # "should I quit my job?" is a question, not a food fork
                said = self._converse(line)
                if said:
                    return said
            return str(e)
        if fork:
            return self._ask(*fork)
        return self._tell(line)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--user", default="you")
    ap.add_argument("--day", type=int, default=1)
    ap.add_argument("--yes", action="store_true", help="apply confident changes without asking")
    ap.add_argument("--mode", choices=["rules", "scorer"], default="rules",
                    help="rank food options with the rule table or the trained scorer "
                         "(needs models/scorer.joblib: python run_eval.py --set scorer)")
    args = ap.parse_args(argv)
    s = Session(args.user, args.day, args.yes, args.mode)
    print(f"Decisive agent. User {s.user}, day {s.day}. /help for commands, /quit to leave.")
    while True:
        try:
            line = input(f"[{s.user} d{s.day}] ")
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if line.strip() in ("/quit", "/exit"):
            return 0
        out = s.handle(line)
        if out:
            print(out)


if __name__ == "__main__":
    sys.exit(main())
