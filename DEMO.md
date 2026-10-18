# Demo video script (3 to 4 minutes) and submission checklist

Everything below was run for real; the on-screen lines are what the commands print. Record at 1080p,
speak slowly, rehearse once, record twice. **Do not show `.env`.**

## Before you record (5 minutes)

1. Docker Desktop running, then `docker start falkordb` (or the `docker run` line in the README).
   Check `docker ps` shows `falkordb` and open http://localhost:3000 once: Browser connects to
   `localhost:6379`.
2. In the project folder: `.venv\Scripts\activate`. Free at least 5 GB on C: first, or Docker may stop.
3. Leave `LLM_MODE=off` in `.env` (the whole demo works without a key).
4. Open three windows: a terminal, the FalkorDB Browser, and the README results tables.

## Timeline

### 0:00 to 0:25, the problem (talk over the title card or the README top)

> "An agent that remembers is not enough. When a fact changes, a memory that keeps everything keeps
> acting on the old version. This agent stores a person's life as a graph in FalkorDB, gives every
> fact a lifecycle, and reads memory through a guard that returns only what is true now."

### 0:25 to 1:35, one person's story, live (terminal)

Either type these, or run `Get-Content scripts\demo_session.txt | python cli.py --user demo --yes`
for a clean take. Say what each step proves:

| You type | What appears | What to say |
|---|---|---|
| `I eat meat again` / `I love fried chicken` / `I love paneer wrap` | `Done: diet_style = non_veg` ... | "It turns sentences into memory operations; a whitelist checks them first." |
| `fried chicken or chana chaat?` | `fried chicken. you like it.` | "No goals yet, so it follows taste." |
| `/day 10` then `I turned vegetarian` | `Done: diet_style = vegetarian.` | "A new value **supersedes** the old one." |
| `fried chicken or chana chaat?` | `chana chaat. you are vegetarian. (you said vegetarian on day 10; before that non veg)` | "The old fact is kept as history, never used." |
| `/why` | `graph path Person -> Decision: length 1` and `non_veg[superseded] -> vegetarian[active]` | "Every answer is auditable in the graph." |
| `/day 12`, `I hate paneer wrap`, `paneer wrap or chana chaat?` | `chana chaat. you dislike it.` | "Now it believes a mistaken dislike." |
| `/day 14`, `that was wrong about paneer wrap` | `retracted dislikes:paneer_wrap (also dropped: avoid_paneer_wrap_orders)` | "A **retraction** says it was never true, and the **cascade** drops everything derived from it." |
| `paneer wrap or chana chaat?` | `paneer wrap. you like it.` | "The answer flips back, because nothing stale can reach it." |
| `/history diet_style` and `/at diet_style 8` | `non_veg [superseded] day 1-10` ... `non_veg` | "Time travel: what was true on day 8?" |

**Prefer something to look at?** Run `python ui_server.py`, open http://127.0.0.1:8765 and click **See an example first** (or Menu, then **Play an example**)
(about 25 seconds; it opens a new blank memory, so nothing of yours is touched). Then, on the Memory tab, drag the **Rewind** slider back
before day 10 and point at the diet row changing. On the **How I decided** tab, click the decision that said "chana chaat":
everything not behind that answer dims, and the audit shows `non_veg -> vegetarian`. Open the **Your people** tab to
set up the 3:25 segment. Run `/day`-style steps in the chat box exactly as in the table.

### 1:35 to 2:10, the graph itself (FalkorDB Browser, http://localhost:3000)

Select the graph `user_demo` (the graph name is `user_` plus the name you passed to `--user`). Run:

```
MATCH (f:Fact)-[r:SUPERSEDED_BY]->(g:Fact) RETURN f, r, g
```
> "Here is the history chain: the old value points to the new one."

```
MATCH p=(:Person)-[:CHOSE]->(:Decision)-[:USED]->(:Fact) RETURN p
```
> "And here is why each answer was given: the decision points at exactly the facts it used."

### 2:10 to 2:50, the proof (README results tables)

Show the Meera table, then the generated-lives table.

> "Same questions, same rules, three memories. The guarded agent is right on 3,595 of 3,595
> held-out questions and uses no stale fact. A memory that keeps the first value gets 52 percent;
> last-write-wins gets 79 percent, because it fixes plain changes but not cascades or retractions."

Then the scorer table: *"A trained model on the same memory scores 99.6 percent; fed the stale memory
it falls to 52 percent. The memory matters more than the model."*

### 2:50 to 3:25, Track 2: agents sharing memory

Run `python scripts/handoff_demo.py` (10 seconds). Point at the output:

> "Two separate agent processes, each with its own MCP connection. They share nothing except this
> person's graph. Intake hears a correction, the advisor's next answer changes, and the handoff is
> linked to the decision it produced."

Then show the concurrency table:

> "Forty-eight lives at once, no leaks, the same answers as when run alone. And the stress test found
> a real race: with the safeguards off, one slot ended with about a hundred active facts out of two
> hundred. A lock, a repair step and atomic claims fix it."

### 3:25 to 3:50, people (terminal)

Type `my friend Priya cancelled again, should I say something?`, then later `Priya cancelled on me
again, should I say something?` with `/day 33` after three earlier cancellations.

> "Advice about friends uses the same memory. A single cancellation is nothing; the fourth in a month is a pattern,
> and it says why. It also says what would change its mind, and it leaves the choice to you."

### 3:50 to 4:00, honest close

> "All data is synthetic. The advice principles are my design and not validated by real users. The
> oracle shares the rule table with the engine, so agreement shows consistency, and the README says so.
> Thank you."

## Things you can say if asked

- **Why a graph?** Facts, goals, decisions and outcomes are connected; cascade, audit paths and PageRank
  are graph queries, not code.
- **Is the LLM deciding?** No. It only reads a sentence and words an answer, and only when switched on.
  The evaluation runs with it off.
- **What did testing find?** A weak oracle (fixed three times, found by injecting known bugs), a
  learning rule that made things worse (fixed), a checker that was too loose, and a real concurrency race.

## Submission checklist (deadline 23:59 IST on 18 Oct 2026; aim to submit by 20:00)

- [ ] Repo is public and opens without login; default branch has the final code.
- [ ] You committed everything yourself. No co-author lines anywhere (`git log --format=%B | grep -i co-authored`
      should print nothing).
- [ ] No keys or `.env` in the history (`git log -p | grep -i api_key` prints nothing).
- [ ] Run `pytest -q` and `python run_eval.py --set meera` once more on the final commit; if you changed
      anything, `python scripts/update_readme.py`.
- [ ] README "Related work" section filled in with the papers **you** read (it is a placeholder).
- [ ] Video uploaded; the link opens in a private window.
- [ ] The form names **both tracks** (Track 01 and Track 02), the repo link, the video link and the AI-use note
      (`AI_USE.md`).
- [ ] Re-read the official rules page once more for required fields.
- [ ] Screenshot of the submission confirmation saved.
