import asyncio
import json

import mcp_server


def call(name, args):
    result = asyncio.run(mcp_server.mcp.call_tool(name, args))
    if isinstance(result, tuple):  # (content blocks, structured)
        return result[1] if result[1] is not None else json.loads(result[0][0].text)
    structured = getattr(result, "structured_content", None)
    if structured is not None:
        return structured.get("result", structured)
    return json.loads(result.content[0].text)


def test_tools_are_listed():
    names = {t.name for t in asyncio.run(mcp_server.mcp.list_tools())}
    assert {"get_facts", "get_fact_at", "fact_history", "rank_goals", "explain_decision",
            "decide_between", "remember", "forget", "count_streak", "related_facts"} <= names


def test_remember_then_decide_then_explain_over_mcp(user):
    call("remember", {"user": user, "key": "diet_style", "value": "non_veg", "day": 1})
    call("remember", {"user": user, "key": "diet_style", "value": "vegetarian", "day": 10})
    facts = call("get_facts", {"user": user, "day": 10})
    assert facts["diet_style"][0] == "vegetarian"

    d = call("decide_between", {"user": user, "day": 10,
                                "options": ["fried_chicken", "chana_chaat"]})
    assert d["pick"] == "chana_chaat" and d["rejected"] == {"fried_chicken": "you are vegetarian"}

    audit = call("explain_decision", {"user": user, "decision_id": d["decision_id"]})
    assert audit["path_length"] == 1 and audit["used"][0]["key"] == "diet_style"
    assert call("get_fact_at", {"user": user, "key": "diet_style", "day": 5})["value"] == "non_veg"


def test_forget_cascades_over_mcp(user):
    call("remember", {"user": user, "key": "dislikes:paneer_wrap", "value": "yes", "day": 3})
    call("remember", {"user": user, "key": "avoid_paneer_wrap_orders", "value": "yes", "day": 3,
                      "derived_from": ["dislikes:paneer_wrap"]})
    out = call("forget", {"user": user, "key": "dislikes:paneer_wrap", "day": 9, "reason": "misread"})
    assert out["dropped"] == ["avoid_paneer_wrap_orders"]
    assert call("get_facts", {"user": user, "day": 9}) == {}
