"""Baseline readers: same data, same rules, a different read rule.

Both read every Fact row ever stored through the raw (unguarded) door, and read goals
without their status, i.e. a memory that keeps everything and has no notion of old.

  first_write        per key, the first value ever written. Deliberately simple.
  last_write_wins    per key, the newest row. What many simple memories do: it fixes
                     supersede but ignores cascade and retraction.
"""
from agent import store


def _facts(user, pick_row):
    by_key = {}
    for row in store.raw_facts(user):
        by_key.setdefault(row["key"], []).append(row)
    return {k: (r["value"], r["id"]) for k, rows in by_key.items()
            for r in [pick_row(rows)]}


def first_write_facts(user):
    return _facts(user, lambda rows: rows[0])


def last_write_wins_facts(user):
    return _facts(user, lambda rows: rows[-1])


def all_goal_tags(user):
    """Every goal ever started, ended or not."""
    return [g["tag"] for g in store.raw_goals(user)]


ARMS = {
    "guarded": None,  # the real agent: tools.get_facts + active goals
    "last_write_wins": last_write_wins_facts,
    "first_write": first_write_facts,
}
