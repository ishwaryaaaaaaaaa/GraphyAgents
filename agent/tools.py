"""Named, parameterised queries: the only door the brain uses to read the graph.

THE GUARD: every read of Fact nodes that the agent uses carries the status filter in
`_LIVE`. Nothing outside tools.py and store.py may match Fact nodes (tests enforce it).
"""
import json

from agent import schema, store
from agent.db import get_graph

# Active, and not expired. Only short-lived facts carry ttl_days; permanent ones never decay.
_LIVE = "f.status='active' AND (f.ttl_days IS NULL OR f.valid_from + f.ttl_days > $day)"


def get_facts(user, day):
    """key -> (value, id) for every fact that is true now."""
    rows = get_graph(user).query(
        f"MATCH (f:Fact) WHERE {_LIVE} RETURN f.key, f.value, f.id ORDER BY f.seq",
        {"day": day},
    ).result_set
    return {k: (v, i) for k, v, i in rows}


def get_fact(user, key, day):
    """One active fact as (value, id), or None."""
    rows = get_graph(user).query(
        f"MATCH (f:Fact {{key:$k}}) WHERE {_LIVE} RETURN f.value, f.id ORDER BY f.seq DESC LIMIT 1",
        {"k": key, "day": day},
    ).result_set
    return (rows[0][0], rows[0][1]) if rows else None


def get_fact_at(user, key, day):
    """Time travel: the value that was true on a past day (retracted facts never count)."""
    rows = get_graph(user).query(
        "MATCH (f:Fact {key:$k}) "
        "WHERE f.status <> 'retracted' AND f.valid_from <= $day "
        "AND (f.valid_to IS NULL OR f.valid_to > $day) "
        "RETURN f.value ORDER BY f.seq DESC LIMIT 1",
        {"k": key, "day": day},
    ).result_set
    return rows[0][0] if rows else None


def fact_history(user, key):
    """Every value this slot has held, oldest first, with how each one ended."""
    rows = get_graph(user).query(
        "MATCH (f:Fact {key:$k}) RETURN f.value, f.status, f.valid_from, f.valid_to, f.id "
        "ORDER BY f.seq",
        {"k": key},
    ).result_set
    cols = ("value", "status", "valid_from", "valid_to", "id")
    return [dict(zip(cols, r)) for r in rows]


def get_active_goals(user):
    rows = get_graph(user).query(
        "MATCH (g:Goal {status:'active'}) RETURN g.id, g.tag, g.since ORDER BY g.since"
    ).result_set
    return [{"id": i, "tag": t, "since": s} for i, t, s in rows]


def get_open_promises(user, tag, day, recent_days=3):
    """Promises for this tag that are open, or were broken within the last few days."""
    rows = get_graph(user).query(
        "MATCH (p:Promise {tag:$tag}) "
        "WHERE p.status='open' OR (p.status='broken' AND p.closed >= $since) "
        "RETURN p.id, p.text, p.status, p.closed ORDER BY p.made",
        {"tag": tag, "since": day - recent_days},
    ).result_set
    return [{"id": i, "text": t, "status": s, "closed": c} for i, t, s, c in rows]


def get_recent_events(user, tag, n, day):
    rows = get_graph(user).query(
        "MATCH (e:Event {tag:$tag}) WHERE e.day <= $day "
        "RETURN e.id, e.kind, e.what, e.day ORDER BY e.day DESC, e.id DESC LIMIT $n",
        {"tag": tag, "day": day, "n": n},
    ).result_set
    return [{"id": i, "kind": k, "what": w, "day": d} for i, k, w, d in rows]


def count_streak(user, tag, day):
    """Clean days since the last treat or slip with this tag (all clean days if none)."""
    g = get_graph(user)
    last = g.query(
        "MATCH (e:Event {tag:$tag}) WHERE e.kind IN $reset AND e.day <= $day RETURN max(e.day)",
        {"tag": tag, "day": day, "reset": list(schema.RESET_KINDS)},
    ).result_set[0][0]
    since = last if last is not None else -1
    return g.query(
        "MATCH (e:Event {tag:$tag, kind:'clean_day'}) WHERE e.day > $since AND e.day <= $day "
        "RETURN count(e)",
        {"tag": tag, "since": since, "day": day},
    ).result_set[0][0]


def rank_goals(user):
    """tag -> PageRank score over ADVANCES edges (goals you act on most rank highest).

    On a graph of a few dozen nodes this mostly counts events; it gets meaningful with
    60-90 days of data. Pass NULL as the label (a label gave flat scores) and filter after.
    """
    g = get_graph(user)
    try:
        rows = g.query(
            "CALL algo.pageRank(NULL,'ADVANCES') YIELD node, score "
            "WHERE node:Goal RETURN node.tag, score ORDER BY score DESC"
        ).result_set
    except Exception:
        rows = []  # no ADVANCES edges yet
    ranks = {}
    for tag, score in rows:
        ranks[tag] = max(ranks.get(tag, 0.0), score)
    return ranks


def related_facts(user, key, hops=2, day=0):
    """Active facts within `hops` DERIVED_FROM links of this key, in either direction."""
    rows = get_graph(user).query(
        f"MATCH (f:Fact {{key:$k}}) WHERE {_LIVE} "
        f"MATCH (f)-[:DERIVED_FROM*1..{int(hops)}]-(r:Fact) WHERE r.status='active' "
        "RETURN DISTINCT r.key, r.value, r.id",
        {"k": key, "day": day},
    ).result_set
    return {k: (v, i) for k, v, i in rows}


def recent_decisions(user, n=40):
    """The last n decisions, oldest first, each with the ids of the facts it USED (for the UI)."""
    rows = get_graph(user).query(
        "MATCH (d:Decision) OPTIONAL MATCH (d)-[:USED]->(f:Fact) "
        "RETURN d.id, d.day, d.pick, d.mode, d.options, d.contact, collect(f.id) "
        "ORDER BY d.day DESC, d.id DESC LIMIT $n", {"n": n},
    ).result_set
    out = [{"id": i, "day": day, "pick": pick, "mode": mode, "options": json.loads(opts or "[]"),
            "contact": contact, "used": [u for u in used if u is not None]}
           for i, day, pick, mode, opts, contact, used in rows]
    return out[::-1]


def explain_decision(user, decision_id):
    """The audit trail: what the answer rested on, each fact's history, and the graph path."""
    g = get_graph(user)
    rows = g.query(
        "MATCH (d:Decision {id:$d}) RETURN d.pick, d.day, d.mode, d.options, d.rules, d.contact",
        {"d": decision_id}
    ).result_set
    if not rows:
        return None
    pick, day, mode, options, rules, contact = rows[0]
    used = g.query(
        "MATCH (d:Decision {id:$d})-[:USED]->(f:Fact) RETURN f.key, f.value, f.id ORDER BY f.seq",
        {"d": decision_id},
    ).result_set
    plen = g.query(
        "MATCH (p:Person), (d:Decision {id:$d}) "
        "WITH shortestPath((p)-[*..4]->(d)) AS x RETURN length(x)",
        {"d": decision_id},
    ).result_set
    values_applied = g.query(
        "MATCH (d:Decision {id:$d})-[:APPLIED]->(v:Value) RETURN v.tag ORDER BY v.id",
        {"d": decision_id}).result_set
    return {
        "decision_id": decision_id, "pick": pick, "day": day, "mode": mode, "options": options,
        "rules": json.loads(rules or "[]"), "contact": contact,
        "values_applied": [r[0] for r in values_applied],
        "used": [{"key": k, "value": v, "id": i, "history": fact_history(user, k)}
                 for k, v, i in used],
        "path_length": plen[0][0] if plen and plen[0][0] is not None else None,
    }


# ---- people ----------------------------------------------------------------------------

def list_contacts(user):
    rows = get_graph(user).query(
        "MATCH (c:Contact) RETURN c.id, c.name, c.relation, c.closeness ORDER BY c.since, c.id"
    ).result_set
    return [{"id": i, "name": n, "relation": r, "closeness": k} for i, n, r, k in rows]


def get_contact(user, cid):
    return next((c for c in list_contacts(user) if c["id"] == cid), None)


def get_fact_meta(user, key, day):
    """The active fact for a key with where it came from, or None. Same guard as get_fact."""
    rows = get_graph(user).query(
        f"MATCH (f:Fact {{key:$k}}) WHERE {_LIVE} "
        "RETURN f.value, f.id, f.source, f.valid_from ORDER BY f.seq DESC LIMIT 1",
        {"k": key, "day": day},
    ).result_set
    if not rows:
        return None
    v, i, src, since = rows[0]
    return {"value": v, "id": i, "source": src, "since": since}


def contact_timeline(user, cid, n, day):
    """The last n things that happened with this person, newest first."""
    rows = get_graph(user).query(
        "MATCH (e:Event {contact:$c}) WHERE e.day <= $day "
        "RETURN e.id, e.kind, e.tone, e.day, e.what ORDER BY e.day DESC, e.id DESC LIMIT $n",
        {"c": cid, "day": day, "n": n},
    ).result_set
    return [{"id": i, "kind": k, "tone": t, "day": d, "what": w} for i, k, t, d, w in rows]


def pattern(user, cid, kind, days, day):
    """How many times `kind` happened with this person in the last `days` days (one count query)."""
    return get_graph(user).query(
        "MATCH (e:Event {contact:$c, kind:$k}) WHERE e.day <= $day AND e.day > $since "
        "RETURN count(e)", {"c": cid, "k": kind, "day": day, "since": day - days},
    ).result_set[0][0]


def values(user):
    """The principles the user holds now (ended ones are not returned)."""
    rows = get_graph(user).query(
        "MATCH (v:Value {status:'active'}) RETURN v.id, v.tag, v.text, v.since ORDER BY v.since, v.id"
    ).result_set
    return [{"id": i, "tag": t, "text": x, "since": s} for i, t, x, s in rows]


def open_promises_to(user, cid, day):
    rows = get_graph(user).query(
        "MATCH (p:Promise {contact:$c, status:'open'}) WHERE p.made <= $day "
        "RETURN p.id, p.text, p.made ORDER BY p.made", {"c": cid, "day": day},
    ).result_set
    return [{"id": i, "text": t, "made": m} for i, t, m in rows]


def past_advice(user, cid, n):
    """Earlier advice about this person and how it turned out (outcome is None if unrated)."""
    rows = get_graph(user).query(
        "MATCH (d:Decision {contact:$c}) OPTIONAL MATCH (d)-[:LED_TO]->(o:Outcome) "
        "RETURN d.id, d.pick, d.day, o.result ORDER BY d.day DESC, d.id DESC LIMIT $n",
        {"c": cid, "n": n},
    ).result_set
    return [{"id": i, "pick": p, "day": d, "result": r} for i, p, d, r in rows]


def mutual_friends(user, cid):
    """Contacts who also know this person: who could help repair things (two hops, directed)."""
    rows = get_graph(user).query(
        "MATCH (:Person {id:$u})-[:KNOWS]->(h:Contact)-[:FRIEND_OF]->(t:Contact {id:$c}) "
        "RETURN h.id, h.name ORDER BY h.id", {"u": user, "c": cid},
    ).result_set
    return [{"id": i, "name": n} for i, n in rows]


def rank_contacts(user):
    """PageRank over INVOLVES edges: who has the most shared history with the user.
    A supporting signal only; on a small graph it mostly counts interactions."""
    try:
        rows = get_graph(user).query(
            "CALL algo.pageRank(NULL,'INVOLVES') YIELD node, score "
            "WHERE node:Contact RETURN node.id, score ORDER BY score DESC").result_set
    except Exception:
        return {}
    return {i: s for i, s in rows}


def pending_handoffs(user, agent):
    """Open handoffs addressed to this agent (or to "any"), oldest first."""
    rows = get_graph(user).query(
        "MATCH (h:Handoff {status:'open'}) WHERE h.to_agent=$a OR h.to_agent='any' "
        "RETURN h.id, h.from_agent, h.task, h.payload, h.created ORDER BY h.created, h.id",
        {"a": agent},
    ).result_set
    return [{"id": i, "from": f, "task": t, "payload": json.loads(p or "{}"), "created": c}
            for i, f, t, p, c in rows]


def list_handoffs(user):
    """Every handoff for this person with its status, oldest first."""
    rows = get_graph(user).query(
        "MATCH (h:Handoff) RETURN h.id, h.from_agent, h.to_agent, h.task, h.status, h.claimed_by "
        "ORDER BY h.created, h.id").result_set
    return [{"id": i, "from": f, "to": t, "task": task, "status": s, "claimed_by": c}
            for i, f, t, task, s, c in rows]


def get_handoff(user, hid):
    """Everything about one handoff, including the decision it led to, or None."""
    g = get_graph(user)
    rows = g.query(
        "MATCH (h:Handoff {id:$h}) OPTIONAL MATCH (h)-[:RESULTED_IN]->(d:Decision) "
        "RETURN h.from_agent, h.to_agent, h.task, h.payload, h.status, h.claimed_by, h.result, "
        "h.created, h.completed, d.id", {"h": hid},
    ).result_set
    if not rows:
        return None
    f, t, task, pl, st, by, res, created, done, did = rows[0]
    return {"id": hid, "from": f, "to": t, "task": task, "payload": json.loads(pl or "{}"),
            "status": st, "claimed_by": by, "result": json.loads(res) if res else None,
            "created": created, "completed": done, "decision_id": did}


def get_weights(user):
    """Procedural memory: rule -> this user's learned multiplier (absent means 1.0)."""
    rows = get_graph(user).query("MATCH (w:Weight) RETURN w.rule, w.mult").result_set
    return {rule: mult for rule, mult in rows}


def weight_history(user, rule):
    """Why a multiplier is what it is: every outcome that moved it, oldest first."""
    rows = get_graph(user).query(
        "MATCH (o:Outcome)-[a:ADJUSTED]->(w:Weight {rule:$r}) "
        "RETURN o.id, o.day, o.result, a.delta, a.mult ORDER BY o.day, o.id",
        {"r": rule},
    ).result_set
    return [{"outcome": i, "day": d, "result": r, "delta": dl, "mult": m}
            for i, d, r, dl, m in rows]


def get_decision(user, decision_id):
    rows = get_graph(user).query(
        "MATCH (d:Decision {id:$d}) RETURN d.pick, d.day, d.options, d.features, d.scores, d.rules, "
        "d.mode, d.contact",
        {"d": decision_id},
    ).result_set
    if not rows:
        return None
    pick, day, options, features, scores, rules, mode, contact = rows[0]
    return {"id": decision_id, "pick": pick, "day": day, "mode": mode, "contact": contact,
            "options": json.loads(options or "[]"), "features": json.loads(features or "{}"),
            "scores": json.loads(scores or "{}"), "rules": json.loads(rules or "[]")}


def pending_outcomes(user, day):
    """Decisions from an earlier day that nobody has said how they turned out."""
    rows = get_graph(user).query(
        "MATCH (d:Decision) WHERE d.day < $day AND NOT (d)-[:LED_TO]->(:Outcome) "
        "RETURN d.id, d.pick, d.day ORDER BY d.day, d.id",
        {"day": day},
    ).result_set
    return [{"id": i, "pick": p, "day": d} for i, p, d in rows]


def record_outcome(user, decision_id, result, day, note=""):
    """How a decision turned out: good, mixed or bad. One outcome per decision."""
    if result not in ("good", "mixed", "bad"):
        raise ValueError("result must be good, mixed or bad")
    g = get_graph(user)
    with store.user_lock(user):  # check-then-create: two raters must not both succeed
        if get_decision(user, decision_id) is None:
            raise KeyError(f"no decision {decision_id}")
        if g.query("MATCH (d:Decision {id:$d})-[:LED_TO]->(o:Outcome) RETURN o.id",
                   {"d": decision_id}).result_set:
            raise ValueError(f"{decision_id} already has an outcome")
        oid = store.new_id(user, "o")
        g.query(
            "MATCH (d:Decision {id:$d}) "
            "CREATE (o:Outcome {id:$o, result:$r, day:$day, note:$n}) CREATE (d)-[:LED_TO]->(o)",
            {"d": decision_id, "o": oid, "r": result, "day": day, "n": note},
        )
    return oid


# ---- action tools: these change the world ------------------------------------------------

def log_event(user, kind, what, tag, day):
    return store.log_event(user, kind, what, tag, day)


def grant_treat(user, tag, day):
    """Record a treat, which resets that tag's streak."""
    return store.log_event(user, "treat", f"earned {tag} treat", tag, day)


def mark_promise(user, promise_id, status, day):
    store.mark_promise(user, promise_id, status, day)


def end_goal(user, tag, day):
    return store.end_goal(user, tag, day)


def record_counsel(user, day, pick, options, used_fact_ids, contact, value_ids, scores,
                   principles):
    """A decision about a person: the usual Decision plus ABOUT (the contact) and APPLIED (the
    values that shaped it). Outcomes are rated with the same /outcome as any other decision."""
    did = record_decision(user, day, pick, options, used_fact_ids, mode="counsel",
                          scores=scores, rules=principles)
    g = get_graph(user)
    g.query("MATCH (d:Decision {id:$d}), (c:Contact {id:$c}) SET d.contact=$c "
            "CREATE (d)-[:ABOUT]->(c)", {"d": did, "c": contact})
    for vid in value_ids:
        g.query("MATCH (d:Decision {id:$d}), (v:Value {id:$v}) CREATE (d)-[:APPLIED]->(v)",
                {"d": did, "v": vid})
    return did


def record_decision(user, day, pick, options, used_fact_ids, mode="rules",
                    features=None, scores=None, rules=None):
    """Write the Decision node, CHOSE edge from the person, and USED edges to its facts.

    `features` and `scores` are a snapshot of what the agent saw, so a later outcome can
    teach it from exactly that moment; `rules` are the soft rules that favoured the pick."""
    store.ensure_user(user)
    g = get_graph(user)
    did = store.new_id(user, "d")
    g.query(
        "MATCH (p:Person {id:$u}) "
        "CREATE (d:Decision {id:$id, day:$day, pick:$pick, options:$opts, mode:$mode, "
        "features:$feat, scores:$sc, rules:$rules}) "
        "CREATE (p)-[:CHOSE]->(d)",
        {"u": user, "id": did, "day": day, "pick": pick,
         "opts": json.dumps(list(options)), "mode": mode,
         "feat": json.dumps(features or {}), "sc": json.dumps(scores or {}),
         "rules": json.dumps(list(rules or []))},
    )
    for fid in used_fact_ids:
        g.query(
            "MATCH (d:Decision {id:$d}), (f:Fact {id:$f}) CREATE (d)-[:USED]->(f)",
            {"d": did, "f": fid},
        )
    return did
