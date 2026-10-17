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

from agent import decide, explain, extract, learn, store, tools

HELP = """tell me things, or ask a fork:  'dessert or skip?'  'can I have ice cream?'
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
    msg = f"I don't know {raw!r}: it is not in my food/activity list."
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


class Session:
    def __init__(self, user="you", day=1, auto=False):
        self.user, self.day, self.auto = user, day, auto
        self.pending = []
        self.last_decision = None
        store.ensure_user(user)

    # -- helpers --
    def _apply(self, ops):
        return "Done: " + "; ".join(extract.apply_ops(self.user, ops, self.day)) + "."

    def _ask(self, names, add_skip):
        res = decide.decide(self.user, self.day, names, add_skip=add_skip)
        self.last_decision = res
        return explain.explain(self.user, res) + f"   [{res['decision_id']}: /why]"

    def _pending_note(self):
        pending = tools.pending_outcomes(self.user, self.day)
        if not pending:
            return ""
        d = pending[-1]
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

    def _tell(self, line):
        got = extract.extract(line, self.day)
        msgs = [f"(couldn't use: {e})" for e in got["errors"]]
        if not got["ops"]:
            return "\n".join(msgs + ["I didn't find anything to remember in that."])
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
            return f"Day {self.day}." + self._pending_note()
        if cmd == "/day" and args and args[0].isdigit():
            self.day = int(args[0])
            return f"Day {self.day}." + self._pending_note()
        if cmd == "/outcome":
            return self._outcome(args)
        if cmd == "/weights":
            return self._weights(args[0] if args else None)
        if cmd == "/user" and args:
            self.__init__(args[0], self.day, self.auto)
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
            if not audit["used"]:
                lines.append("used no stored facts")
            return "\n".join(lines)
        return "Unknown command. /help"

    def handle(self, line):
        line = line.strip()
        if not line:
            return ""
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
        try:
            fork = parse_fork(line)
        except ValueError as e:
            return str(e)
        if fork:
            return self._ask(*fork)
        return self._tell(line)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--user", default="you")
    ap.add_argument("--day", type=int, default=1)
    ap.add_argument("--yes", action="store_true", help="apply confident changes without asking")
    args = ap.parse_args(argv)
    s = Session(args.user, args.day, args.yes)
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
