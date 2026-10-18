"""Two agents, two processes, one graph.

    python scripts/handoff_demo.py

An INTAKE agent listens to a person and keeps their memory up to date. An ADVISOR agent answers
their food questions. They are separate OS processes, each with its own MCP connection to its own
MCP server process, and they share NOTHING except the person's graph in FalkorDB:

  * intake writes what it hears (remember / forget), then hands a question to the advisor by
    creating a Handoff node;
  * advisor sees the handoff in the graph, claims it (atomically), answers from guarded memory,
    and completes the handoff, linking it to the decision it made;
  * intake reads the answer back from the graph.

The story has a correction in the middle, so the advisor's third answer proves it is not working
from anything stale: a mistaken dislike is retracted by intake and the advisor's next answer changes
with no message passed between them except the handoff itself.
"""
import argparse
import asyncio
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

USER = "handoff_demo"
T0 = time.time()


def say(role, text):
    print(f"[{time.time() - T0:5.1f}s {role:7}] {text}", flush=True)


class Agent:
    """One agent: its own MCP client talking to its own MCP server process."""

    def __init__(self, name):
        self.name = name

    async def __aenter__(self):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
        # The MCP SDK starts the server with a restricted environment. Pass ours on explicitly, or the
        # server would not see FALKORDB_HOST (e.g. under docker compose, where there is no .env) and
        # would quietly use a private embedded database, so the two agents would never share a graph.
        params = StdioServerParameters(command=sys.executable, args=[str(ROOT / "mcp_server.py")],
                                       cwd=str(ROOT), env=dict(os.environ))
        self._stdio = stdio_client(params)
        read, write = await self._stdio.__aenter__()
        self._session = ClientSession(read, write)
        await self._session.__aenter__()
        await self._session.initialize()
        return self

    async def __aexit__(self, *exc):
        await self._session.__aexit__(*exc)
        await self._stdio.__aexit__(*exc)

    async def call(self, tool, **args):
        r = await self._session.call_tool(tool, args)
        structured = getattr(r, "structured_content", None) or getattr(r, "structuredContent", None)
        if structured is not None:
            return structured.get("result", structured) if isinstance(structured, dict) else structured
        return json.loads(r.content[0].text)


# ---- the intake agent ---------------------------------------------------------------------------

async def intake():
    async with Agent("intake") as a:
        say("intake", f"started (pid {os.getpid()}), connected to its own MCP server")

        async def ask(question, options, day):
            h = (await a.call("handoff_create", user=USER, from_agent="intake", to_agent="advisor",
                              task=question, day=day, payload={"options": options, "day": day}))
            hid = h["handoff_id"]
            say("intake", f"handed {hid} to the advisor: {question!r}")
            for _ in range(240):
                st = await a.call("handoff_status", user=USER, handoff_id=hid)
                if st.get("status") == "done":
                    pick = st["result"]["pick"]
                    say("intake", f"{hid} answered by {st['claimed_by']}: {pick.replace('_', ' ')} "
                                  f"(decision {st['decision_id']})")
                    return pick
                await asyncio.sleep(0.25)
            raise TimeoutError(f"nobody answered {hid}")

        say("intake", "hears: 'I used to eat meat, I love fried chicken and paneer wrap'")
        await a.call("remember", user=USER, key="diet_style", value="non_veg", day=1)
        await a.call("remember", user=USER, key="likes:fried_chicken", value="yes", day=1)
        await a.call("remember", user=USER, key="likes:paneer_wrap", value="yes", day=1)
        say("intake", "hears (day 10): 'I turned vegetarian'")
        await a.call("remember", user=USER, key="diet_style", value="vegetarian", day=10)
        await ask("fried chicken or chana chaat?", ["fried_chicken", "chana_chaat"], 10)

        say("intake", "hears (day 12): 'I hate paneer wrap'  (a mistake: it was a friend's message)")
        await a.call("remember", user=USER, key="dislikes:paneer_wrap", value="yes", day=12)
        await a.call("remember", user=USER, key="avoid_paneer_wrap_orders", value="yes", day=12,
                     derived_from=["dislikes:paneer_wrap"])
        await ask("paneer wrap or chana chaat?", ["paneer_wrap", "chana_chaat"], 12)

        say("intake", "hears (day 14): 'that was wrong about paneer wrap'  -> retracts it")
        out = await a.call("forget", user=USER, key="dislikes:paneer_wrap", day=14,
                           reason="a friend's message, misread")
        say("intake", f"retraction also dropped: {out['dropped']}")
        await ask("paneer wrap or chana chaat?", ["paneer_wrap", "chana_chaat"], 14)
        say("intake", "done")


# ---- the advisor agent --------------------------------------------------------------------------

async def advisor(expect):
    async with Agent("advisor") as a:
        say("advisor", f"started (pid {os.getpid()}), connected to its own MCP server")
        done, deadline = 0, time.time() + 120
        while done < expect and time.time() < deadline:
            for h in (await a.call("handoff_pending", user=USER, agent="advisor"))["pending"]:
                claim = await a.call("handoff_claim", user=USER, handoff_id=h["id"],
                                     agent="advisor", day=h["payload"]["day"])
                if not claim["claimed"]:
                    continue  # another advisor got it first
                say("advisor", f"claimed {h['id']} from {h['from']}: {h['task']!r}")
                res = await a.call("decide_between", user=USER, day=h["payload"]["day"],
                                   options=h["payload"]["options"])
                say("advisor", f"answers {res['pick'].replace('_', ' ')}  "
                               f"(reasons: {', '.join(res['reasons']) or 'none'}; "
                               f"rejected: {res['rejected'] or 'none'})")
                await a.call("handoff_complete", user=USER, handoff_id=h["id"], agent="advisor",
                             result={"pick": res["pick"], "reasons": res["reasons"],
                                     "used_fact_ids": res["used_fact_ids"]},
                             day=h["payload"]["day"], decision_id=res["decision_id"])
                done += 1
            await asyncio.sleep(0.25)
        say("advisor", f"done ({done} handoffs)")


# ---- the coordinator: starts both, then audits what is in the graph --------------------------------

def run_demo(print_output=True):
    from agent import store, tools
    store.reset(USER)
    store.ensure_user(USER)
    env = {**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"}
    cmd = [sys.executable, str(Path(__file__).resolve())]
    lines, procs = [], {}
    for role in ("advisor", "intake"):   # advisor first, so it is already listening
        procs[role] = subprocess.Popen(cmd + ["--role", role, "--expect", "3"], env=env,
                                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                       encoding="utf-8", cwd=str(ROOT))
        time.sleep(1.5)
    import threading

    def pump(name, proc):
        for line in proc.stdout:
            lines.append(line.rstrip())
            if print_output:
                print(line.rstrip(), flush=True)

    pumps = [threading.Thread(target=pump, args=(n, p)) for n, p in procs.items()]
    [t.start() for t in pumps]
    codes = {}
    try:
        for n, p in procs.items():
            codes[n] = p.wait(timeout=150)
    except subprocess.TimeoutExpired:
        for p in procs.values():   # never leave agent processes behind
            p.kill()
        raise
    finally:
        [t.join(timeout=5) for t in pumps]

    handoffs = [tools.get_handoff(USER, h["id"]) for h in tools.list_handoffs(USER)]
    audits = [tools.explain_decision(USER, h["decision_id"]) for h in handoffs]
    other = {"facts": tools.get_facts("handoff_other_tenant", 99),
             "handoffs": tools.pending_handoffs("handoff_other_tenant", "advisor")}
    result = {"exit_codes": codes, "answers": [h["result"]["pick"] for h in handoffs],
              "handoffs": handoffs, "audits": audits, "other_tenant": other,
              "transcript": lines}
    if print_output:
        print("\n--- audit, read from the graph ---")
        for h, au in zip(handoffs, audits):
            used = ", ".join(f"{u['key']}={u['value']}" for u in au["used"]) or "no stored facts"
            print(f"{h['id']}: {h['from']} -> {h['claimed_by']}  [{h['status']}]  picked "
                  f"{h['result']['pick']}  from {used}  (decision {h['decision_id']}, "
                  f"path length {au['path_length']})")
        print(f"another person's graph sees: {other}")
    return result


def write_transcript(result):
    out = ROOT / "results" / "handoff_demo.md"
    out.parent.mkdir(exist_ok=True)
    body = "\n".join(result["transcript"])
    out.write_text("### Handoff demo transcript\n\n```\n" + body + "\n```\n", encoding="utf-8")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--role", choices=["intake", "advisor"])
    ap.add_argument("--expect", type=int, default=3)
    args = ap.parse_args()
    if args.role:
        try:
            asyncio.run(intake() if args.role == "intake" else advisor(args.expect))
        except BaseException as e:  # noqa: BLE001 - say what broke and leave at once, never hang
            say(args.role, f"FAILED: {type(e).__name__}: {e}")
            os._exit(1)
    else:
        res = run_demo()
        write_transcript(res)
        sys.exit(0 if all(c == 0 for c in res["exit_codes"].values()) else 1)
