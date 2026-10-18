"""The memory engine: the write side of the graph. No LLM, no system clock.

Rules live here: supersede, retract, cascade. The read-side guard is in tools.py.
Time is an integer simulation day passed in by the caller. Nothing is ever deleted;
facts change status instead.
"""
import contextlib
import threading

from agent import schema
from agent.db import drop_graph, get_graph

_ensured = set()

# Concurrency. Reads never block. A write that reads first and then writes (set_fact, retract_fact,
# add_contact, add_value, a handoff claim) must not interleave with another writer to the same
# graph. Two layers: an in-process lock per user (LOCKING), and a repair step after every fact write
# (SETTLE) that makes the graph converge even when the other writer is a different process, such as
# a second MCP server. Both can be switched off so the stress test can show what each one prevents.
LOCKING = True
SETTLE = True
_locks, _locks_guard = {}, threading.Lock()


def user_lock(user):
    """A re-entrant lock for one person's graph (a no-op context if LOCKING is off)."""
    if not LOCKING:
        return contextlib.nullcontext()
    with _locks_guard:
        return _locks.setdefault(user, threading.RLock())


def reset(user):
    """Drop the user's graph. Every test starts from here."""
    drop_graph(user)
    _ensured.discard(user)


def ensure_user(user):
    if user in _ensured:
        return
    g = get_graph(user)
    g.query("MERGE (p:Person {id:$u}) ON CREATE SET p.n = 0", {"u": user})
    for stmt in schema.INDEXES:
        try:
            g.query(stmt)
        except Exception:
            pass  # index already exists
    _ensured.add(user)


def _next(user):
    """One counter per graph gives short ids (f12, e40) and a stable seq."""
    rows = get_graph(user).query(
        "MATCH (p:Person {id:$u}) SET p.n = p.n + 1 RETURN p.n", {"u": user}
    ).result_set
    return int(rows[0][0])


def _active_id(user, key):
    rows = get_graph(user).query(
        "MATCH (f:Fact {key:$k, status:'active'}) RETURN f.id, f.value ORDER BY f.seq DESC LIMIT 1",
        {"k": key},
    ).result_set
    return (rows[0][0], rows[0][1]) if rows else (None, None)


def _last_write_day(user, key):
    rows = get_graph(user).query(
        "MATCH (f:Fact {key:$k}) RETURN max(f.valid_from)", {"k": key}
    ).result_set
    return rows[0][0] if rows and rows[0][0] is not None else None


def last_write_day(user, key):
    """Day of the newest write to this slot, or None. Lets callers keep history append-only."""
    return _last_write_day(user, key)


def cascade(user, fact_id, status, day):
    """Follow DERIVED_FROM backwards (up to 6 hops); drop every still-active descendant.

    A derived fact with two parents is dropped when either parent goes: cautious on purpose.
    """
    q = (
        f"MATCH (f:Fact {{id:$id}})<-[:DERIVED_FROM*1..{schema.CASCADE_MAX_HOPS}]-(d:Fact) "
        "WHERE d.status='active' "
        "SET d.status=$st, d.valid_to=$day "
        "RETURN d.key"
    )
    rows = get_graph(user).query(q, {"id": fact_id, "st": status, "day": day}).result_set
    return sorted({r[0] for r in rows})


def settle(user, key, day):
    """Make sure exactly one fact is active for this slot.

    Two writers in different processes can both read "nothing active", both create a fact, and leave
    two active rows. The newest (highest seq) wins; every older active row is superseded in order,
    its cascade runs, and the SUPERSEDED_BY chain is kept linear. Idempotent and safe to run twice."""
    g = get_graph(user)
    rows = g.query("MATCH (f:Fact {key:$k, status:'active'}) RETURN f.id ORDER BY f.seq",
                   {"k": key}).result_set
    ids = [r[0] for r in rows]
    for older, newer in zip(ids, ids[1:]):
        g.query("MATCH (o:Fact {id:$o}) SET o.status='superseded', o.valid_to=$day",
                {"o": older, "day": day})
        g.query("MATCH (o:Fact {id:$o}), (n:Fact {id:$n}) MERGE (o)-[:SUPERSEDED_BY]->(n)",
                {"o": older, "n": newer})
        cascade(user, older, schema.INVALIDATED, day)
    return len(ids) - 1 if len(ids) > 1 else 0


def set_fact(user, key, value, day, source="typed", confidence=1.0,
             derived_from=(), ttl_days=None):
    """Write a belief. Returns (fact_id, keys_dropped_by_cascade)."""
    with user_lock(user):
        out = _set_fact(user, key, value, day, source, confidence, derived_from, ttl_days)
        if SETTLE:
            settle(user, key, day)
        return out


def _set_fact(user, key, value, day, source, confidence, derived_from, ttl_days):
    ensure_user(user)
    g = get_graph(user)

    old_id, old_value = _active_id(user, key)
    if old_id is not None and old_value == value:
        return old_id, []  # same value already active: no-op, repeated input is safe

    last = _last_write_day(user, key)
    if last is not None and day < last:
        raise ValueError(
            f"history is append-only: {key!r} was last written on day {last}, got day {day}"
        )

    # Resolve parents before writing anything, so a bad call leaves no partial state.
    parents = []
    for pk in derived_from:
        pid, _ = _active_id(user, pk)
        if pid is None:
            raise ValueError(f"derived fact {key!r} has no active parent {pk!r}")
        parents.append(pid)

    n = _next(user)
    new_id = f"f{n}"
    g.query(
        "MATCH (p:Person {id:$u}) "
        "CREATE (n:Fact {id:$id, key:$key, value:$v, status:'active', valid_from:$day, "
        "source:$src, seq:$seq, confidence:$c}) "
        "CREATE (p)-[:HAS_FACT]->(n)",
        {"u": user, "id": new_id, "key": key, "v": value, "day": day,
         "src": source, "seq": n, "c": confidence},
    )
    if ttl_days is not None:
        g.query("MATCH (n:Fact {id:$id}) SET n.ttl_days=$t", {"id": new_id, "t": ttl_days})
    for pid in parents:
        g.query(
            "MATCH (n:Fact {id:$n}), (p:Fact {id:$p}) CREATE (n)-[:DERIVED_FROM]->(p)",
            {"n": new_id, "p": pid},
        )

    dropped = []
    if old_id is not None:
        g.query(
            "MATCH (o:Fact {id:$o}) SET o.status='superseded', o.valid_to=$day",
            {"o": old_id, "day": day},
        )
        g.query(
            "MATCH (o:Fact {id:$o}), (n:Fact {id:$n}) CREATE (o)-[:SUPERSEDED_BY]->(n)",
            {"o": old_id, "n": new_id},
        )
        dropped = cascade(user, old_id, schema.INVALIDATED, day)
    return new_id, dropped


def retract_fact(user, key, day, reason=""):
    """The fact was never true. Returns keys dropped by the cascade ([] if nothing active)."""
    with user_lock(user):
        ensure_user(user)
        fid, _ = _active_id(user, key)
        if fid is None:
            return []
        get_graph(user).query(
            "MATCH (f:Fact {id:$id, status:'active'}) SET f.status='retracted', f.valid_to=$day, "
            "f.reason=$r", {"id": fid, "day": day, "r": reason},
        )
        return cascade(user, fid, schema.RETRACTED, day)


# ---- plain writes: goals, promises, events ------------------------------------------

def start_goal(user, tag, day):
    ensure_user(user)
    gid = f"g{_next(user)}"
    get_graph(user).query(
        "CREATE (:Goal {id:$id, tag:$tag, status:'active', since:$day})",
        {"id": gid, "tag": tag, "day": day},
    )
    return gid


def end_goal(user, tag, day):
    """Stop every active goal with this tag; later forks ignore it."""
    ensure_user(user)
    rows = get_graph(user).query(
        "MATCH (g:Goal {tag:$tag, status:'active'}) SET g.status='ended', g.until=$day RETURN g.id",
        {"tag": tag, "day": day},
    ).result_set
    return [r[0] for r in rows]


def make_promise(user, text, tag, day, goal_tag=None, contact=None):
    ensure_user(user)
    pid = f"p{_next(user)}"
    g = get_graph(user)
    g.query(
        "CREATE (:Promise {id:$id, text:$text, tag:$tag, made:$day, status:'open'})",
        {"id": pid, "text": text, "tag": tag, "day": day},
    )
    if contact:  # a promise TO someone
        g.query("MATCH (p:Promise {id:$p}), (c:Contact {id:$c}) CREATE (p)-[:TO]->(c) "
                "SET p.contact=$c", {"p": pid, "c": contact})
    if goal_tag:
        g.query(
            "MATCH (p:Promise {id:$p}), (g:Goal {tag:$t, status:'active'}) "
            "CREATE (p)-[:CONCERNS]->(g)",
            {"p": pid, "t": goal_tag},
        )
    return pid


def mark_promise(user, promise_id, status, day):
    if status not in ("kept", "broken"):
        raise ValueError("promise status must be 'kept' or 'broken'")
    ensure_user(user)
    get_graph(user).query(
        "MATCH (p:Promise {id:$id}) SET p.status=$st, p.closed=$day",
        {"id": promise_id, "st": status, "day": day},
    )


def new_id(user, prefix):
    """Next short id for a node that tools.py creates (decisions)."""
    return f"{prefix}{_next(user)}"


def log_event(user, kind, what, tag, day):
    """Record something that happened. Positive events advance every active goal with the
    same tag; a treat or slip is recorded but does not count toward the goal."""
    ensure_user(user)
    eid = f"e{_next(user)}"
    g = get_graph(user)
    g.query(
        "CREATE (:Event {id:$id, kind:$kind, what:$what, tag:$tag, day:$day})",
        {"id": eid, "kind": kind, "what": what, "tag": tag, "day": day},
    )
    if kind in schema.ADVANCING_KINDS:
        g.query(
            "MATCH (e:Event {id:$id}), (g:Goal {tag:$tag, status:'active'}) "
            "CREATE (e)-[:ADVANCES]->(g)",
            {"id": eid, "tag": tag},
        )
    return eid


# ---- people ----------------------------------------------------------------------------

def contact_id(name):
    """A contact's id is its lowercase name, so ids stay readable (priya, rhea)."""
    return "".join(ch for ch in name.lower() if ch.isalnum())


def add_contact(user, name, relation, day, closeness=3):
    """Add a person to this user's life. Adding the same name again changes nothing."""
    ensure_user(user)
    cid = contact_id(name)
    if not cid:
        raise ValueError("a contact needs a name")
    g = get_graph(user)
    with user_lock(user):
        if g.query("MATCH (c:Contact {id:$c}) RETURN c.id", {"c": cid}).result_set:
            return cid
        g.query(
            "MATCH (p:Person {id:$u}) "
            "MERGE (c:Contact {id:$c}) "
            "ON CREATE SET c.name=$n, c.relation=$r, c.closeness=$k, c.since=$day "
            "MERGE (p)-[:KNOWS]->(c)",
            {"u": user, "c": cid, "n": name.strip().title(), "r": relation, "k": closeness,
             "day": day},
        )
    return cid


def log_interaction(user, cid, kind, tone, what, day):
    """Something that happened between the user and a contact (a cancelled plan, an argument)."""
    if kind not in schema.SOCIAL_KINDS:
        raise ValueError(f"interaction kind must be one of {schema.SOCIAL_KINDS}")
    ensure_user(user)
    g = get_graph(user)
    if not g.query("MATCH (c:Contact {id:$c}) RETURN c.id", {"c": cid}).result_set:
        raise KeyError(f"no contact {cid!r}")
    eid = f"e{_next(user)}"
    g.query(
        "MATCH (c:Contact {id:$c}) "
        "CREATE (e:Event {id:$id, kind:$kind, what:$what, tag:'social', day:$day, tone:$tone, "
        "contact:$c}) CREATE (e)-[:INVOLVES]->(c)",
        {"c": cid, "id": eid, "kind": kind, "what": what, "day": day, "tone": tone},
    )
    return eid


def link_contacts(user, a, b):
    """Two of the user's contacts know each other (both directions, so directed paths work)."""
    ensure_user(user)
    get_graph(user).query(
        "MATCH (x:Contact {id:$a}), (y:Contact {id:$b}) "
        "MERGE (x)-[:FRIEND_OF]->(y) MERGE (y)-[:FRIEND_OF]->(x)", {"a": a, "b": b})


def add_value(user, tag, text, day):
    """A principle the user stated about themselves ('I want to be someone who shows up')."""
    if tag not in schema.VALUE_TAGS:
        raise ValueError(f"value tag must be one of {schema.VALUE_TAGS}")
    ensure_user(user)
    g = get_graph(user)
    with user_lock(user):
        if g.query("MATCH (v:Value {tag:$t, status:'active'}) RETURN v.id", {"t": tag}).result_set:
            return None  # already held
        vid = f"v{_next(user)}"
        g.query("MATCH (p:Person {id:$u}) CREATE (v:Value {id:$id, tag:$t, text:$x, since:$d, "
                "status:'active'}) CREATE (p)-[:HOLDS]->(v)",
                {"u": user, "id": vid, "t": tag, "x": text[:120], "d": day})
    return vid


# ---- handoffs between agents ----------------------------------------------------------------

def create_handoff(user, from_agent, to_agent, task, payload, day):
    """One agent asks another to do something, through the graph: a `Handoff` node that anyone with
    access to this person's graph can see. `to_agent` may be "any"."""
    import json
    ensure_user(user)
    hid = f"h{_next(user)}"
    get_graph(user).query(
        "MATCH (p:Person {id:$u}) "
        "CREATE (h:Handoff {id:$id, from_agent:$f, to_agent:$t, task:$task, payload:$pl, "
        "status:'open', created:$day}) CREATE (p)-[:HAS_HANDOFF]->(h)",
        {"u": user, "id": hid, "f": from_agent, "t": to_agent, "task": task,
         "pl": json.dumps(payload or {}), "day": day},
    )
    return hid


def claim_handoff(user, hid, agent, day):
    """Take an open handoff. ONE query that both checks the status and changes it, so when several
    agents race for the same handoff exactly one gets True (FalkorDB runs write queries on a graph
    one at a time)."""
    rows = get_graph(user).query(
        "MATCH (h:Handoff {id:$h, status:'open'}) WHERE h.to_agent=$a OR h.to_agent='any' "
        "SET h.status='claimed', h.claimed_by=$a, h.claimed=$day RETURN h.id",
        {"h": hid, "a": agent, "day": day},
    ).result_set
    return bool(rows)


def complete_handoff(user, hid, agent, result, day, decision_id=None):
    """Finish a handoff you claimed, and link it to the decision it produced. False if it is not
    yours to complete."""
    import json
    g = get_graph(user)
    rows = g.query(
        "MATCH (h:Handoff {id:$h, status:'claimed', claimed_by:$a}) "
        "SET h.status='done', h.result=$r, h.completed=$day RETURN h.id",
        {"h": hid, "a": agent, "r": json.dumps(result, default=str), "day": day},
    ).result_set
    if rows and decision_id:
        g.query("MATCH (h:Handoff {id:$h}), (d:Decision {id:$d}) MERGE (h)-[:RESULTED_IN]->(d)",
                {"h": hid, "d": decision_id})
    return bool(rows)


def end_value(user, tag, day):
    ensure_user(user)
    rows = get_graph(user).query(
        "MATCH (v:Value {tag:$t, status:'active'}) SET v.status='ended', v.until=$d RETURN v.id",
        {"t": tag, "d": day}).result_set
    return [r[0] for r in rows]


def set_weight(user, rule, mult, outcome_id, delta):
    """Move one rule's learned multiplier, and keep the audit edge Outcome -[ADJUSTED]-> Weight."""
    ensure_user(user)
    get_graph(user).query(
        "MATCH (p:Person {id:$u}), (o:Outcome {id:$o}) "
        "MERGE (p)-[:HAS_WEIGHT]->(w:Weight {rule:$r}) "
        "SET w.mult=$m "
        "CREATE (o)-[:ADJUSTED {delta:$d, mult:$m}]->(w)",
        {"u": user, "o": outcome_id, "r": rule, "m": mult, "d": delta},
    )


def raw_facts(user):
    """EVAL ONLY: every Fact row ever written, any status, oldest first.

    This is the unguarded door. The agent never calls it; eval/baseline.py does, to model
    a memory that keeps everything and has no notion of old.
    """
    ensure_user(user)
    rows = get_graph(user).query(
        "MATCH (f:Fact) RETURN f.id, f.key, f.value, f.status, f.valid_from, f.valid_to, f.seq, "
        "f.source ORDER BY f.seq"
    ).result_set
    cols = ("id", "key", "value", "status", "valid_from", "valid_to", "seq", "source")
    return [dict(zip(cols, r)) for r in rows]


def raw_slot_report(user, key):
    """EVAL ONLY: the structure of one slot's history, for the concurrency stress test. How many
    facts, how many active, the SUPERSEDED_BY edges and degrees, and how many old facts cannot reach
    the active one."""
    g = get_graph(user)
    rows = g.query("MATCH (f:Fact {key:$k}) RETURN f.id, f.status", {"k": key}).result_set
    edges = g.query("MATCH (a:Fact {key:$k})-[:SUPERSEDED_BY]->(b:Fact) RETURN a.id, b.id",
                    {"k": key}).result_set
    out, inn = {}, {}
    for a, b in edges:
        out[a] = out.get(a, 0) + 1
        inn[b] = inn.get(b, 0) + 1
    unreachable = g.query(
        "MATCH (f:Fact {key:$k}) WHERE f.status <> 'active' AND NOT "
        "(f)-[:SUPERSEDED_BY*1..400]->(:Fact {key:$k, status:'active'}) RETURN count(f)",
        {"k": key}).result_set[0][0]
    return {"facts": len(rows), "active": sum(r[1] == "active" for r in rows), "edges": len(edges),
            "max_out": max(out.values(), default=0), "max_in": max(inn.values(), default=0),
            "unreachable": unreachable}


def raw_edges(user):
    """INSPECTION ONLY (the web UI's graph view): the SUPERSEDED_BY and DERIVED_FROM links between
    facts of every status, as {"superseded": [[old, new]], "derived": [[child, parent]]}."""
    g = get_graph(user)
    sup = g.query("MATCH (a:Fact)-[:SUPERSEDED_BY]->(b:Fact) RETURN a.id, b.id").result_set
    der = g.query("MATCH (c:Fact)-[:DERIVED_FROM]->(p:Fact) RETURN c.id, p.id").result_set
    return {"superseded": [list(r) for r in sup], "derived": [list(r) for r in der]}


def raw_parent_status(user, key):
    """EVAL ONLY: (id, status) of the fact the ACTIVE fact `key` was derived from, or None."""
    rows = get_graph(user).query(
        "MATCH (m:Fact {key:$k, status:'active'}) OPTIONAL MATCH (m)-[:DERIVED_FROM]->(p:Fact) "
        "RETURN p.id, p.status", {"k": key}).result_set
    return (rows[0][0], rows[0][1]) if rows else None


def raw_goals(user):
    """EVAL ONLY: every goal ever started, including ended ones."""
    ensure_user(user)
    rows = get_graph(user).query(
        "MATCH (g:Goal) RETURN g.id, g.tag, g.status, g.since, g.until ORDER BY g.since"
    ).result_set
    return [dict(zip(("id", "tag", "status", "since", "until"), r)) for r in rows]


def snapshot(user, day=None):
    """Every fact with status and validity, for tests and the audit view."""
    ensure_user(user)
    rows = get_graph(user).query(
        "MATCH (f:Fact) RETURN f.id, f.key, f.value, f.status, f.valid_from, f.valid_to "
        "ORDER BY f.seq"
    ).result_set
    cols = ("id", "key", "value", "status", "valid_from", "valid_to")
    out = [dict(zip(cols, r)) for r in rows]
    if day is not None:
        out = [f for f in out if f["valid_from"] <= day]
    return out
