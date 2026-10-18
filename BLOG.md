# My AI agent kept recommending chicken to a vegetarian. So I gave its memory a graph.

I told an agent in March that I eat meat. In May I became vegetarian. I asked it what to order, and it said chicken.

It did not forget. That was the problem. It remembered both things, and it had no way to know that one of them stopped being true. Most "memory" for agents works like this: it only adds. New facts pile on top of old ones, and yesterday's version of you keeps voting on today's decisions.

So I built **Decisive**, an agent whose memory is a FalkorDB graph where every fact has a life. This is how I did it, what broke, and what I learned.

## The idea in one rule

> Nothing is ever deleted. But only what is true *now* is allowed to touch an answer.

A fact is a node. It is `active`, `superseded`, `retracted` or `invalidated`. When you say "I turned vegetarian", the old fact is not erased. It gets a `SUPERSEDED_BY` edge to the new one and stops being active. When you say "that was wrong", the fact is retracted, and so is everything that was built on it.

A graph is the right tool for this because the interesting part is not the facts. It is the links between them: what replaced what, what was built on what, and which decision used which fact.

## Where FalkorDB does the real work

**1. The read guard.** The agent can only read facts through one condition:

```cypher
MATCH (f:Fact)
WHERE f.status = 'active'
  AND (f.ttl_days IS NULL OR f.valid_from + f.ttl_days > $day)
RETURN f.key, f.value, f.id
```

Only three files are allowed to write a `MATCH (f:Fact)` at all, and a test fails if a fourth file does. That is how a stale fact can never reach an answer by accident.

**2. Cascade by traversal.** Some facts only exist because of another one. "Avoid paneer wrap orders" exists because of "I hate paneer wrap". If the dislike was a mistake, the avoidance has to go too:

```cypher
MATCH (f:Fact {id:$id})<-[:DERIVED_FROM*1..6]-(d:Fact)
WHERE d.status = 'active'
SET d.status = $st, d.valid_to = $day
RETURN d.key
```

One variable-length traversal. No loops in my code, no list of "things to clean up" to keep in sync.

**3. Time travel.** Every fact has `valid_from` and `valid_to`, so "what did the agent believe on day 8?" is one query:

```cypher
MATCH (f:Fact {key:$k})
WHERE f.status <> 'retracted' AND f.valid_from <= $day
  AND (f.valid_to IS NULL OR f.valid_to > $day)
RETURN f.value ORDER BY f.seq DESC LIMIT 1
```

Retracted facts never count, because they were never true.

**4. A receipt for every decision.** Each decision is a node linked to the facts it used. A `shortestPath` from the person to the decision is the audit trail, and the website draws it as a graph you can click.

**5. PageRank for goals.** Goals are ranked with `algo.pageRank` over the goal events, so a goal you keep working on counts for more than one you mentioned once.

**6. One graph per person.** Each person gets their own graph, so two people can never see each other's memory. I tested this with 16 people at once.

## What I got wrong first

**My tests were too easy.** My first question generator passed everything, which scared me more than failing. So I broke the engine on purpose: 7 injected bugs, like a wrong threshold or a disabled cascade. My first version of the tests caught only 4 of them. I rebuilt the generator to aim at close calls, and now it catches all 7.

**Two agents, one memory.** When 8 threads wrote to the same slot, I ended up with 111 "active" facts in a slot that should have one. A graph does not stop you from making a mess. I fixed it with a per-person lock, a repair step that keeps the `SUPERSEDED_BY` chain a straight line, and an atomic claim so two agents never take the same job.

**It only broke on Linux.** A multiprocessing deadlock, an MCP server that could not find the database, and output that looked frozen. Running everything in Docker found all three.

## Did it work?

I measured it against a checker that is separate code from the engine, on 3,595 generated questions the engine never saw while I built it. All of it is synthetic data.

| | Decisive | "Newest write wins" memory |
|---|---|---|
| Questions answered correctly | **3,595 / 3,595** | 2,828 (78.7%) |
| Stale facts used | **0** | 648 |

On 1,417 questions about friends, Decisive matched the checker every time. The simple memory matched 79.4%. With 16 memories running at once on one database, there were zero leaks between people.

I want to be honest about the limit: I wrote both the engine and the checker, so zero disagreements means they agree, not that my rules are the right rules.

## What I learned

1. **Memory that never forgets is not the goal. Memory that knows what is still true is.** Keeping history is easy. Keeping history *out of the answer* is the hard part, and it needs a rule you enforce, not a prompt you hope for.
2. **A graph earns its place when the links are the product.** Replaced-by, built-on and used-by are edges. Once they are edges, cascade, time travel and audit are short queries instead of code.
3. **Prove it against something that can disagree with you.** The most useful thing I built was not a feature. It was a way to be told I was wrong.
4. **Make the answer checkable.** Showing the facts behind a decision changed how I used it. I corrected the agent more, because I could see what it was relying on.

You can try it, see the graph behind every answer, and read the evaluation in the repo: https://github.com/ishwaryaaaaaaaaa/GraphyAgents

*I used an AI coding assistant to write much of the code and tests. I made the design decisions, reviewed everything, and made every commit myself. The product does not need an LLM: decisions come from readable rules and graph queries.*
