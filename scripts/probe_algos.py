"""Check the exact FalkorDB procedure names and query shapes before relying on them."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent import store, tools  # noqa: E402
from agent.db import get_graph  # noqa: E402

u = "probe"
store.reset(u)
store.start_goal(u, "sugar", 1)
store.start_goal(u, "fried", 1)
for d in range(2, 8):
    store.log_event(u, "clean_day", "no sugar", "sugar", d)
store.log_event(u, "clean_day", "no fried", "fried", 8)
g = get_graph(u)

print("procedures:")
for r in g.query("CALL dbms.procedures() YIELD name RETURN name ORDER BY name").result_set:
    print("  ", r[0])

print("pagerank over ADVANCES, goals only:")
print(g.query("CALL algo.pageRank(NULL,'ADVANCES') YIELD node, score "
              "WHERE node:Goal RETURN node.tag, score ORDER BY score DESC").result_set)

fid, _ = store.set_fact(u, "diet_style", "vegetarian", 1)
did = tools.record_decision(u, 1, "chana_chaat", ["fried_chicken", "chana_chaat"], [fid])
print("shortestPath Person->Decision (directed, inside WITH):")
print(g.query("MATCH (p:Person {id:$u}), (d:Decision {id:$d}) "
              "WITH shortestPath((p)-[*..4]->(d)) AS x RETURN length(x)",
              {"u": u, "d": did}).result_set)
store.reset(u)
