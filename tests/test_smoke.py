from agent.db import drop_graph, get_graph


def test_connect_write_read_delete():
    user = "smoke"
    drop_graph(user)
    g = get_graph(user)
    g.query("CREATE (:Person {id:$i})", {"i": "x"})
    rows = g.query("MATCH (p:Person {id:$i}) RETURN p.id", {"i": "x"}).result_set
    assert rows == [["x"]]
    drop_graph(user)
