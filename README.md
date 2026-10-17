# Decisive agent

**An agent whose memory is a FalkorDB graph, and whose answers never rest on a fact that has stopped being true.**

Agents that remember are not enough: when a fact changes ("I turned vegetarian", "I moved out of the hostel", "that was wrong about paneer"), a memory that merely keeps everything will keep acting on the old version. This project stores a person's goals, promises, tastes and facts as a graph, gives every fact a lifecycle (active, superseded, retracted, invalidated), and routes every read through a guard that returns only what is true now. Then it measures how often an agent uses something that is no longer true.

Fictional data only. Runs from the command line and from tests; the proof is a table of numbers.

## Tracks

- **Track 01, agents that act on connected data.** Named, parameterised query tools (`agent/tools.py`) exposed over MCP (`mcp_server.py`), multi-hop lookups (`related_facts`, cascade), PageRank over goal events, an explainable `shortestPath` audit trail from person to decision, and logged actions (treats, events, decisions).
- **Track 02, agent memory and coordination.** Memory that corrects itself: supersede, retract and cascade, a read guard, time travel (`get_fact_at`), persistent per-user graphs (one graph per user, isolated), and an audit trail. Many readers can share one store; the MCP server exposes it to any client.

## Results

All numbers are produced by `python run_eval.py` and pasted here from `results/*.md` by `scripts/update_readme.py`.

**How to read them.** Three readers answer the same questions against the same live graph with the same rules; only the read rule differs.

- *guarded (agent)*: only facts with status `active`.
- *last-write-wins*: reads every row ever stored, takes the newest per key. Fixes supersede but ignores cascade and retraction. What many simple memories do.
- *first-write*: takes the first value ever written per key. A deliberately simple baseline, not a state-of-the-art claim.

Both baselines also read goals without their status (an ended goal still counts). "Stale-use" counts only facts, not goals.

### Hand-written life (Meera, 55 days)

<!-- RESULTS:meera:start -->
15 questions. 95% Wilson interval in brackets.

| Reader | Task success | Stale-use | Wrongful-keep |
|---|---|---|---|
| first-write (no guard) | 9 of 15 (60.0%) [35.7-80.2] | 5 of 15 (33.3%) [15.2-58.3] | 2 of 15 (13.3%) |
| guarded (agent) | 15 of 15 (100.0%) [79.6-100.0] | 0 of 15 (0.0%) [0.0-20.4] | 0 of 15 (0.0%) |
| last-write-wins (no guard) | 12 of 15 (80.0%) [54.8-93.0] | 2 of 15 (13.3%) [3.7-37.9] | 2 of 15 (13.3%) |

Task success by trap type (correct answers out of n):

| Trap | n | first-write (no guard) | guarded (agent) | last-write-wins (no guard) |
|---|---|---|---|---|
| cascade | 1 | 0 | 1 | 0 |
| control | 1 | 1 | 1 | 1 |
| diet_change | 1 | 0 | 1 | 1 |
| dislike | 1 | 1 | 1 | 1 |
| double_change | 1 | 0 | 1 | 1 |
| goal_ended | 1 | 0 | 1 | 0 |
| promise | 3 | 3 | 3 | 3 |
| retraction | 1 | 0 | 1 | 0 |
| streak | 4 | 4 | 4 | 4 |
| taste_flip | 1 | 0 | 1 | 1 |

Guarded agent only:

| Metric | Result |
|---|---|
| Wrongful-drop (active fact hidden) | 0 of 15 (0.0%) |
| Cascade completeness | 2 of 2 (100.0%) |
| Time-travel accuracy | 10 of 10 (100.0%) |
| Audit coverage | 15 of 15 (100.0%) |
<!-- RESULTS:meera:end -->

### Generated lives (test split: seeds 300-499, never used to tune anything)

<!-- RESULTS:generated:start -->
3595 questions. 95% Wilson interval in brackets.

| Reader | Task success | Stale-use | Wrongful-keep |
|---|---|---|---|
| first-write (no guard) | 1857 of 3595 (51.7%) [50.0-53.3] | 1910 of 3595 (53.1%) [51.5-54.8] | 582 of 3595 (16.2%) |
| guarded (agent) | 3595 of 3595 (100.0%) [99.9-100.0] | 0 of 3595 (0.0%) [0.0-0.1] | 0 of 3595 (0.0%) |
| last-write-wins (no guard) | 2828 of 3595 (78.7%) [77.3-80.0] | 648 of 3595 (18.0%) [16.8-19.3] | 529 of 3595 (14.7%) |

Task success by trap type (correct answers out of n):

| Trap | n | first-write (no guard) | guarded (agent) | last-write-wins (no guard) |
|---|---|---|---|---|
| cascade | 170 | 0 | 170 | 0 |
| combined | 20 | 0 | 20 | 20 |
| diet_change | 539 | 0 | 539 | 511 |
| goal_ended | 235 | 0 | 235 | 0 |
| none | 1858 | 1857 | 1858 | 1858 |
| retraction | 323 | 0 | 323 | 0 |
| taste_flip | 450 | 0 | 450 | 439 |

Guarded agent only:

| Metric | Result |
|---|---|
| Wrongful-drop (active fact hidden) | 0 of 3595 (0.0%) |
| Cascade completeness | 494 of 494 (100.0%) |
| Time-travel accuracy | 1262 of 1262 (100.0%) |
| Audit coverage | 3595 of 3595 (100.0%) |
<!-- RESULTS:generated:end -->

### Learning from outcomes (simulated users)

Each simulated user has hidden preference weights. The agent starts with the defaults, sees only good, mixed or bad feedback on its picks, and learns from the bad ones. Rule and learning rate were chosen on development seeds 0-99; this table is seeds 1000+.

<!-- RESULTS:learning:start -->
100 simulated users per population, 60 trade-off decisions each. Each user has hidden preference weights; the agent only sees good / mixed / bad feedback and learns from bad outcomes. 'Agrees' = picks the option the user's hidden weights rank first.

| Users | Decisions | Fixed weights agree | Learned weights agree | Fixed regret | Learned regret |
|---|---|---|---|---|---|
| mild (0.6-1.6) | 1-20 | 1956 of 2000 (97.8%) | 1957 of 2000 (97.8%) | 0.01 | 0.01 |
| mild (0.6-1.6) | 21-40 | 1959 of 2000 (98.0%) | 1968 of 2000 (98.4%) | 0.02 | 0.01 |
| mild (0.6-1.6) | 41-60 | 1957 of 2000 (97.8%) | 1973 of 2000 (98.7%) | 0.02 | 0.01 |
| moderate (0.3-2.2) | 1-20 | 1872 of 2000 (93.6%) | 1881 of 2000 (94.0%) | 0.06 | 0.05 |
| moderate (0.3-2.2) | 21-40 | 1862 of 2000 (93.1%) | 1884 of 2000 (94.2%) | 0.06 | 0.04 |
| moderate (0.3-2.2) | 41-60 | 1867 of 2000 (93.3%) | 1899 of 2000 (95.0%) | 0.06 | 0.04 |
| strong (0.05-3.0) | 1-20 | 1833 of 2000 (91.7%) | 1873 of 2000 (93.7%) | 0.13 | 0.08 |
| strong (0.05-3.0) | 21-40 | 1826 of 2000 (91.3%) | 1891 of 2000 (94.5%) | 0.14 | 0.06 |
| strong (0.05-3.0) | 41-60 | 1833 of 2000 (91.7%) | 1902 of 2000 (95.1%) | 0.14 | 0.05 |

Regret is the hidden-score gap between the user's best option and the agent's pick (0 when it agrees). The multiplier range in brackets is how far the hidden user's weights stray from the defaults (1.0).
<!-- RESULTS:learning:end -->

What this shows and does not show: for people who differ strongly from the default weights the agent removes about two thirds of its regret; for people close to the defaults there is little to learn and it never gets worse. The gain in plain accuracy is modest (about 4 points for the strong population), because most forks have an obvious winner whatever the weights are. The hidden user shares the agent's scoring structure with different multipliers, so this tests the learning, not the scoring.

### Does the evaluation catch real bugs?

`python scripts/mutation_check.py 300 329` injects known faults into the engine and counts disagreements with the oracle. A mutation with 0 disagreements would be a bug the evaluation cannot see. On seeds 300-329: the unmodified engine has 0, and each of the 7 injected faults (streak threshold, like bonus, healthy bonus, promise bonus, promise window, cascade disabled, guard removed) is detected. The first version of the question generator missed three of them (the like bonus, promise bonus and promise window); the generator now aims questions at close calls and at promises past their window, which is why they are caught.

## Architecture

The database decides what is true; the LLM only reads what the database hands it. Four layers, each calling only the one below.

| Layer | Job | Files |
|---|---|---|
| Interface | Chat loop, MCP server, evaluation runner | `cli.py`, `mcp_server.py`, `run_eval.py` |
| Brain | Sentence to updates, pick an answer, explain it | `agent/extract.py`, `agent/decide.py`, `agent/explain.py`, `agent/llm.py` |
| Tools | Named, parameterised Cypher: the read door | `agent/tools.py` |
| Memory | Schema, supersede, retract, cascade, time travel | `agent/store.py`, `agent/schema.py`, `agent/db.py` |

`store.py` never imports the LLM, so it is tested with no key. Time is an integer simulation day passed in everywhere; the engine never reads the clock. Nothing is ever deleted: facts change status instead. Every public function takes the user and a day, so each person has their own graph (`user_<id>`) and any life can be replayed exactly.

## Graph data model

One graph per person. A node's label is its type; edges point as shown.

| Node | Properties |
|---|---|
| `Person` | `id`, `n` (id counter) |
| `Fact` | `id`, `key`, `value`, `status`, `valid_from`, `valid_to`, `source`, `seq`, `confidence`, optional `ttl_days`, `reason` |
| `Goal` | `id`, `tag`, `status` (active/ended), `since`, `until` |
| `Promise` | `id`, `text`, `tag`, `made`, `status` (open/kept/broken), `closed` |
| `Event` | `id`, `kind` (clean_day, slip, treat, study_done), `what`, `tag`, `day` |
| `Decision` | `id`, `day`, `pick`, `options`, `mode`, plus a snapshot of the features and scores the agent saw |
| `Outcome` | `id`, `result` (good/mixed/bad), `day`, `note`: how a decision turned out |
| `Weight` | `rule`, `mult`: this person's learned multiplier for a soft rule (procedural memory) |

| Edge | Meaning |
|---|---|
| `Person -[HAS_FACT]-> Fact` | ownership |
| `Fact -[SUPERSEDED_BY]-> Fact` | the history chain, old to new |
| `Fact -[DERIVED_FROM]-> Fact` | this fact exists only because of that one; cascade follows it |
| `Event -[ADVANCES]-> Goal` | the event counts toward the goal; PageRank runs over this |
| `Promise -[CONCERNS]-> Goal` | optional |
| `Decision -[USED]-> Fact` | the facts the answer relied on: the audit trail |
| `Person -[CHOSE]-> Decision` | makes a directed path from the person to every answer |
| `Decision -[LED_TO]-> Outcome` | how the advice turned out |
| `Person -[HAS_WEIGHT]-> Weight` | the person's learned rule weights |
| `Outcome -[ADJUSTED {delta, mult}]-> Weight` | why a weight is what it is: every outcome that moved it |

The food and activity catalogue is `data/foods.json` (45 items with tags), not graph nodes.

**Fact lifecycle.** `active` is true now and the only status a normal read returns. `superseded`: was true, replaced by a newer value. `retracted`: was never true. `invalidated`: was true only because of a parent fact that has since changed.

## The four memory rules

1. **Supersede.** A new value for a slot closes the old fact (`valid_to`), links `old -SUPERSEDED_BY-> new`, and the same value written twice is a no-op. History is append-only: writing a day earlier than the last write is rejected.
   *Example:* diet `non_veg` on day 1, `vegetarian` on day 10. On day 8 the answer is `non_veg`; from day 10 it is `vegetarian`.
2. **Retract.** A fact that was never true is marked `retracted`; it never answers any time-travel question.
   *Example:* a friend's message is misread as "she dislikes paneer wrap"; on day 41 it is retracted, and the agent may suggest paneer wrap again.
3. **Cascade.** One variable-length query (`DERIVED_FROM*1..6`) drops every still-active descendant of a fact that changed or was retracted. A fact with two parents is dropped when *either* goes: deliberately cautious, because it is safer to ask again than to keep acting on something half-true.
   *Example:* `lives_in` hostel to flat invalidates `mess_meals_available`, so the mess thali is no longer offered.
4. **Guard.** Every read the agent uses goes through `tools.py`, and every Fact query there filters `status = 'active'` (and hides expired short-lived facts). A test greps the repo and fails if any other code matches Fact nodes. Marking a fact old is not enough if retrieval can still return it.

### Memory types

| Type | What it holds | In the graph |
|---|---|---|
| Semantic | what is true about the person | `Fact` nodes and their lifecycle |
| Episodic | what happened and what was decided | `Event`, `Decision`, `Outcome` |
| Procedural | how this person decides | `Weight` nodes, changed only by outcomes |

### Learning from outcomes

After a decision the user can say how it went (`/outcome good|mixed|bad`; the CLI asks the next day). On a **bad** outcome the agent compares what it picked with the runner-up using the feature snapshot saved on the `Decision`, and moves that person's multiplier for each soft rule toward what the runner-up had. Hard rules (diet, dislikes, availability, sugar streak) are safety checks and are never learned: a learned weight cannot make a vegetarian eat meat. Good and mixed outcomes are recorded but change nothing: reinforcing good outcomes was tried and made accuracy worse, because easy correct picks keep inflating whichever rules favoured them (`scripts/learning_sweep.py` keeps the evidence). Nothing is fine-tuned, and each person's weights live in their own graph.

Other behaviour: only short-lived facts decay (`ttl_days`); permanent facts never do. Time travel is `get_fact_at(key, day)`. Low-confidence extractions (under 0.6) are never written until the user confirms.

## Decision rules

Hard rules reject an option, soft rules score it, the highest score wins (ties: better goal rank, then first listed). Weights live in `agent/rules.json`.

| Rule | Effect |
|---|---|
| meat item and `diet_style = vegetarian` | reject |
| `dislikes:<item> = yes` | reject |
| option requires a fact that is not `yes` (mess thali needs `mess_meals_available`) | reject |
| sugar item, sugar goal active, fewer than 5 clean days since the last treat or slip | reject |
| sugar item, goal active, 5+ clean days | +5 (an earned treat; granting it resets the streak) |
| `likes:<item> = yes` | +2 |
| tagged healthy | +1 |
| fried item, fried goal active | -3 x goal rank (PageRank, scaled 1.0 to 1.5) |
| open promise, or one broken in the last 3 days, matches the option | +3 |

The agent follows goals the user set and can be overridden; it gives no medical advice. Reasons only quote the user's own goals, promises and tastes.

## Graph work, by tool

| Tool (`agent/tools.py` / `store.py`) | Cypher shape |
|---|---|
| `get_facts`, `get_fact` | `MATCH (f:Fact) WHERE f.status='active' AND (expired check)` |
| `get_fact_at` | `valid_from <= day AND (valid_to IS NULL OR valid_to > day) AND status <> 'retracted'` |
| `fact_history` | all rows for a key ordered by `seq` |
| `store.cascade` | `MATCH (f:Fact {id})<-[:DERIVED_FROM*1..6]-(d:Fact) WHERE d.status='active' SET ...` |
| `related_facts` | `(f)-[:DERIVED_FROM*1..n]-(r:Fact)` undirected multi-hop |
| `count_streak` | max day of treat/slip, then count of clean days after it |
| `rank_goals` | `CALL algo.pageRank(NULL,'ADVANCES') YIELD node, score WHERE node:Goal` |
| `explain_decision` | `USED` edges plus `WITH shortestPath((p)-[*..4]->(d))` (directed; undirected is refused) |
| `record_decision` | creates `Decision`, `CHOSE` and `USED` edges |

## How to run

You need a FalkorDB server on `localhost:6379`. Python 3.11+.

```bash
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                                   # keep LLM_MODE=off unless you have a Gemini key
```

**Option A: Docker (one command).** Starts FalkorDB (Browser on http://localhost:3000) and runs the tests and both evaluations:

```bash
docker compose up --build --abort-on-container-exit
```

**Option B: a local server.** `docker run -p 6379:6379 -p 3000:3000 falkordb/falkordb`, then:

```bash
python run_eval.py --set meera                          # hand-written life
python run_eval.py --set generated --seeds 300-499      # generated, held-out
pytest -q                                               # all tests, LLM off
python cli.py --user meera                              # chat with the agent
python mcp_server.py                                    # MCP server over stdio
```

**Windows without Docker.** `falkordblite` does not build on native Windows. Run FalkorDB inside WSL: `wsl bash scripts/wsl_setup.sh` once, then start `scripts/wsl_server.py` with the WSL Python, and keep `FALKORDB_HOST=localhost` in `.env`.

Chat examples: `I turned vegetarian last week and I'm off sugar from today`, `fried chicken or chana chaat?`, `can I have ice cream?`, `/why`, `/outcome bad`, `/weights`, `/history diet_style`, `/at diet_style 8`, `/next`, `/help`. Anyone can use it: `python cli.py --user <your name>` gives you your own private graph.

Optional LLM: set `LLM_MODE=on`, `GEMINI_API_KEY` and `LLM_MODEL` in `.env`. Without it, a regex grammar handles about a dozen sentence shapes and templates write the explanations. All tests and the evaluation run with the LLM off.

## Limits and honesty

- **Everything is synthetic.** Meera and every generated life are fictional.
- **The oracle is not fully independent.** `data/oracle.py` is separate code that never imports the agent and reads the generator's true world, but it implements the same written rule table, and the author of both is the same. Zero disagreements shows the engine and the oracle agree, not that the rules are the right rules. We reduce this with held-out lives, items and change patterns, and with the mutation check above. The goal rank is not reimplemented: questions whose answer depends on the exact PageRank are detected over a grid of ranks and never asked.
- **The baselines are simple on purpose.** They show what a read rule without a notion of "old" gets wrong. They are not the state of the art.
- **PageRank is weak on small graphs.** Over a few dozen nodes it mostly counts events.
- **Cascade is cautious on purpose.** It can drop a fact that was still true; the agent then asks again.
- **Retraction does not reinstate the predecessor.** If a retracted fact had superseded an older one, the older value is not restored; time travel reports nothing for those days. The generator avoids that case.
- **Stale-use counts facts only**, not goals or promises.
- **The extractor fixtures are hand-written** unless `tests/fixtures/extract_llm.json` says they were recorded from a real model.
- **Learning is only tested on simulated users.** Their hidden weights use the agent's own scoring structure, and a "bad" outcome blames the runner-up, which is a heuristic when there are three or more options. No real person has used it.
- **Not built:** a trained ML scorer, the friends and judgment layer, the "pending" fact status, external benchmarks.
- No medical advice; the "healthy" tag is a label the user's own goals use.

## Related work

*To be completed by the author:* list the memory and staleness papers you read and say exactly what this adds. Do not claim to be first.

## AI use

See [AI_USE.md](AI_USE.md).

## Team and license

Built for the WeMakeDevs x FalkorDB Graph Hacks. Code under the MIT license (see `LICENSE`); FalkorDB is SSPL.
