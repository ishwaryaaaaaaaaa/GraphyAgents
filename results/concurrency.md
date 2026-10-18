### Track 2 stress test: concurrency

48 generated lives, each in its own graph on one FalkorDB server (graph module 42201, Redis 8.10.2), replayed alone and then 16 at a time.

**Many people at once**

| Check | Result |
|---|---|
| Same answers when run in parallel as when run alone | 48 of 48 lives |
| Disagreements with the oracle (parallel run) | 0 of 879 questions |
| Stale facts used | 0 |
| Cross-person leaks (owner marker and graph contents checked at every question) | 0 |
| Cascades dropped wrongly | 0 |

| Run | Wall time | Operations / s | Queries / s | Read latency p50 / p95 / p99 (ms) | Write latency p50 / p95 / p99 (ms) |
|---|---|---|---|---|---|
| 1 worker | 111.9 s | 34 | 612 | 1.31 / 2.52 / 3.56 | 1.29 / 2.39 / 3.61 |
| 16 workers | 36.2 s | 104 | 1891 | 4.23 / 19.8 / 62.74 | 4.35 / 31.68 / 102.23 |

Speed-up from parallelism: 3.1x.

**Many agents on one person** (8 threads, same graph)

| Check | Safeguard on | Safeguard off |
|---|---|---|
| Event ids unique (320 written) | 320 unique | 320 unique |
| One contested slot: exactly one active fact, linear history, nothing lost | consistent (1 active of 200) | broken (111 active of 200) |
| Two-step update (lives_in then derived mess_meals_available) left consistent | 6 of 6 runs | 3 of 6 runs |

**Many processes on one slot** (4 separate OS processes, like two MCP servers)

| | settle on | settle off |
|---|---|---|
| Active facts in the slot | 1 | 69 |
| Facts that cannot reach the active one | 0 | 0 |
| Consistent | yes | no |
