"""MCP server over agent/tools.py: any MCP client (Claude Desktop, an agent framework) can
read the graph memory, record changes and ask for guarded decisions.

Run:  python mcp_server.py            (stdio)
      python mcp_server.py --http     (streamable HTTP on localhost)

Every read goes through the same guarded tools the agent uses, so a client can never
fetch a fact that has stopped being true. One graph per `user`, selected per call.
"""
import sys

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from agent import decide, store, tools

mcp = MCPServer(
    "decisive-agent",
    instructions=(
        "Graph memory for a personal decision agent. Facts can be superseded, retracted or "
        "invalidated; reads only return what is true on the given simulation day. Call "
        "get_facts or decide before answering; call remember/forget when the user changes "
        "or corrects something; call explain_decision to show why an answer was given."
    ),
)

READ = ToolAnnotations(readOnlyHint=True)
WRITE = ToolAnnotations(readOnlyHint=False, destructiveHint=False)


@mcp.tool(annotations=READ)
def get_facts(user: str, day: int) -> dict:
    """Every fact that is true now for this user, as key -> [value, fact_id]."""
    return tools.get_facts(user, day)


@mcp.tool(annotations=READ)
def get_fact_at(user: str, key: str, day: int) -> dict:
    """Time travel: the value this slot held on a past day (null if none; retracted never counts)."""
    return {"key": key, "day": day, "value": tools.get_fact_at(user, key, day)}


@mcp.tool(annotations=READ)
def fact_history(user: str, key: str) -> list:
    """Every value this slot has held, oldest first, with how each one ended."""
    return tools.fact_history(user, key)


@mcp.tool(annotations=READ)
def rank_goals(user: str) -> dict:
    """PageRank over goal events: tag -> score. Goals the user acts on most rank highest."""
    return tools.rank_goals(user)


@mcp.tool(annotations=READ)
def get_active_goals(user: str) -> list:
    """Goals that are currently active."""
    return tools.get_active_goals(user)


@mcp.tool(annotations=READ)
def count_streak(user: str, tag: str, day: int) -> int:
    """Clean days since the last treat or slip for this tag."""
    return tools.count_streak(user, tag, day)


@mcp.tool(annotations=READ)
def related_facts(user: str, key: str, hops: int = 2, day: int = 0) -> dict:
    """Active facts within `hops` derived-from links of this key (multi-hop context)."""
    return tools.related_facts(user, key, min(max(hops, 1), 6), day)


@mcp.tool(annotations=READ)
def explain_decision(user: str, decision_id: str) -> dict:
    """The audit trail of one decision: facts it used, each fact's history, graph path length."""
    return tools.explain_decision(user, decision_id) or {"error": f"no decision {decision_id}"}


@mcp.tool(annotations=WRITE)
def decide_between(user: str, day: int, options: list[str], add_skip: bool = False) -> dict:
    """Pick among catalogue options using only currently-true facts. Logs the decision and
    grants an earned treat. Returns pick, reasons, rejected options and the facts used."""
    return decide.decide(user, day, options, add_skip=add_skip)


@mcp.tool(annotations=WRITE)
def remember(user: str, key: str, value: str, day: int, derived_from: list[str] | None = None) -> dict:
    """Record a belief. A changed value supersedes the old one and cascades to facts derived
    from it. Returns the new fact id and the keys the cascade dropped."""
    fid, dropped = store.set_fact(user, key, value, day, derived_from=derived_from or [])
    return {"fact_id": fid, "dropped": dropped}


@mcp.tool(annotations=WRITE)
def forget(user: str, key: str, day: int, reason: str = "") -> dict:
    """Retract a fact that was never true (bad extraction, a correction). Cascades."""
    return {"dropped": store.retract_fact(user, key, day, reason)}


@mcp.tool(annotations=WRITE)
def log_event(user: str, kind: str, what: str, tag: str, day: int) -> dict:
    """Record something that happened (clean_day, slip, treat, study_done)."""
    return {"event_id": tools.log_event(user, kind, what, tag, day)}


# ---- coordination between agents: handoffs live in the graph ---------------------------------

@mcp.tool(annotations=WRITE)
def handoff_create(user: str, from_agent: str, to_agent: str, task: str, day: int,
                   payload: dict | None = None) -> dict:
    """Ask another agent (or "any") to do something for this person. The request is a Handoff node
    in the person's graph, so every agent connected to the same graph can see it."""
    return {"handoff_id": store.create_handoff(user, from_agent, to_agent, task, payload, day)}


@mcp.tool(annotations=READ)
def handoff_pending(user: str, agent: str) -> dict:
    """Open handoffs addressed to this agent (or to "any"), oldest first, as {"pending": [...]}.
    (A dict, not a bare list: MCP returns a list as one content block per item, so a one-item
    list would look like a plain object to a client.)"""
    return {"pending": tools.pending_handoffs(user, agent)}


@mcp.tool(annotations=WRITE)
def handoff_claim(user: str, handoff_id: str, agent: str, day: int) -> dict:
    """Take an open handoff. Atomic: if several agents race for it, exactly one gets claimed=true."""
    return {"claimed": store.claim_handoff(user, handoff_id, agent, day)}


@mcp.tool(annotations=WRITE)
def handoff_complete(user: str, handoff_id: str, agent: str, result: dict, day: int,
                     decision_id: str | None = None) -> dict:
    """Finish a handoff you claimed and link it to the decision it produced (false if it is not
    yours to complete)."""
    return {"completed": store.complete_handoff(user, handoff_id, agent, result, day, decision_id)}


@mcp.tool(annotations=READ)
def handoff_status(user: str, handoff_id: str) -> dict:
    """Status, owner, result and linked decision of one handoff."""
    return tools.get_handoff(user, handoff_id) or {"error": f"no handoff {handoff_id}"}


if __name__ == "__main__":
    mcp.run("streamable-http" if "--http" in sys.argv else "stdio")
