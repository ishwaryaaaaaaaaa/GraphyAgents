# Submission answers (copy and paste)

Fill the three links when you have them: repo, live demo, video.

- **Repo:** https://github.com/ishwaryaaaaaaaaa/GraphyAgents
- **Live demo:** (your Render link)
- **Video:** (your video link)

## Project name
Decisive

## One line
An agent that never gives advice based on something that stopped being true.

## Tracks
Track 01 (agents that act on connected data) and Track 02 (agent memory and coordination).

## What does it do?
You tell it about your life in plain words: what you eat, what you love or hate, your goals, a friend who keeps cancelling. Then you ask it to choose, like "what should I order?" or "should I say something to my friend?". It answers, and it shows you why.

The main thing is this: when something changes, it changes too. If you say "I turned vegetarian", it keeps the old fact as history, but it never uses it again. If you say "that was wrong", it drops that fact and everything built on it. Every answer shows the exact facts it used, and you can rewind to any day to see what it believed then.

## What problem does it solve?
Most agents with memory only add things. They never let go. So after you change, they keep giving you advice for the old you. That is worse than no memory, because it sounds confident and it is wrong. I wanted memory that stays correct as your life changes.

## How do you use FalkorDB? Why is it central?
The whole memory is a FalkorDB graph, one graph for each person. Nothing works without it.

- Every fact is a node with a life: active, superseded, retracted or invalidated. Nothing is deleted.
- Facts point to the facts that replaced them, and to the facts they were built on. When I retract one, a graph traversal drops everything that depended on it.
- Every decision is a node linked to the facts it used. A `shortestPath` query gives the audit trail from the person to the decision.
- Goals are ranked with PageRank over the goal events.
- A read guard means the agent can only read facts that are true now. Only three files are allowed to touch facts, and a test enforces it.
- Many agents can share one person's memory over MCP, with locks and an atomic claim so they never double-act.

I tried to use the graph for what a graph is good at: following links and tracing why.

## Why both tracks?
Track 01: the agent acts through named, parameterised graph queries exposed as MCP tools, with multi-hop lookups, PageRank and an explainable path for every decision.

Track 02: the memory corrects itself (replace, retract, cascade, time travel), stays separate for each person, and several agents can work on the same person's memory without breaking it. I tested this with 16 people at once and with separate processes acting on one memory.

## How did you build it?
- FalkorDB (official server) with Python. The decisions come from readable rules and graph queries, not from an LLM.
- An optional LLM (Gemini) only turns a sentence into memory operations and rewords the answer. It never decides what is true. Everything it produces is checked before anything is written. The whole thing runs with the LLM off.
- A small trained scorer (scikit-learn) that ranks food options, compared against the rules.
- A friends layer that gives advice using patterns, promises and your own values, and not just flattery.
- An MCP server so other agents can use the memory and hand work to each other.
- A website with a landing page, chat, memory timeline with time travel, a graph view and a people page. It is plain HTML and Python standard library, no framework.

## How do you know it works?
I tested it against an independent checker, on a held-out set of 3,595 generated questions it never saw while I built it. All numbers are on synthetic data.

- Decisive answered 3,595 of 3,595 correctly and used 0 stale facts. A "newest write wins" memory got 78.7% and used 648 stale facts.
- On 1,417 questions about friends, Decisive matched the checker on all 1,417. The simple memory matched 79.4%.
- 16 memories running at the same time on one database: 0 leaks between people, 0 stale reads.
- I injected 7 known bugs on purpose. The tests caught all 7. The first version missed 3, so I fixed my question generator.
- 299 tests pass on the real FalkorDB server, also inside Docker on Linux.

## What was hard?
- Proving it, not just claiming it. My first questions were too easy and missed real bugs, so I rebuilt them to aim at close calls.
- Two agents working on one memory at once. I saw 111 active facts in a slot that should have one. I fixed it with a lock, a repair step and an atomic claim.
- Many small things that only broke on Linux: a deadlock with multiprocessing, a server that could not find the database, and hidden output buffering. Running it in Docker found all of them.
- Making the website feel like a product and not a developer console.

## What is honest about the limits?
- All data is made up. There are no real users yet.
- My checker is separate code, but I wrote both the checker and the engine, so zero disagreements means they agree, not that the rules are the right rules.
- The advice principles are my design choices. A psychologist has not checked them.
- Today it helps with food choices and friendships only.
- The live demo uses a FalkorDB inside the container, so memories reset when the free server restarts.

## What is next?
- More areas than food and friends: work, money, health.
- Real users and real data, to test the rules.
- Let the agent ask "is this still true?" when a fact gets old.
- A memory that survives restarts on the live demo.

## Did you use AI to build this?
Yes. I used Claude Code, an AI coding assistant, to write and refactor code, tests and docs. I made the design decisions: the graph model, the four memory rules, the test plan, and which results to report. I reviewed what it produced and I can explain all of it. I made every commit myself. The product itself does not depend on an LLM: decisions come from rules and graph queries, and the evaluation runs with the LLM off. Details are in `AI_USE.md`.

## Was this built during the event?
Yes. The project and its FalkorDB work were built during the hackathon. The commit history is in the repo.

## Short blog intro (optional side prize)
Your assistant remembers everything about you. That is the problem.

I told an agent in March that I eat meat. In May I became vegetarian. It still recommended chicken. Not because it forgot, but because it never let go. So I built Decisive: an agent whose memory is a FalkorDB graph where every fact has a life. Facts get replaced, retracted and rewound, never deleted, and only what is true now is allowed to touch an answer. Every decision shows the facts it used and the path through the graph that led there. It got 3,595 of 3,595 held-out questions right, while a "newest wins" memory used 648 stale facts. Here is how it works.
