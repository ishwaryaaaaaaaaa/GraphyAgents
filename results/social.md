### Advice about people, seeds 2000-2199

1417 questions about friends. 95% Wilson interval in brackets.

| Reader | Same principles as the oracle | Same verdict as the oracle | Stale-use |
|---|---|---|---|
| guarded (agent) | 1417 of 1417 (100.0%) [99.7-100.0] | 1417 of 1417 (100.0%) | 0 of 1417 (0.0%) |
| last-write-wins (no guard) | 1125 of 1417 (79.4%) [77.2-81.4] | 1227 of 1417 (86.6%) | 292 of 1417 (20.6%) |
| first-write (no guard) | 746 of 1417 (52.6%) [50.0-55.2] | 962 of 1417 (67.9%) | 698 of 1417 (49.3%) |

Principle consistency by stale-memory trap (questions where the principles were exactly right):

| Trap | n | guarded (agent) | last-write-wins (no guard) | first-write (no guard) |
|---|---|---|---|---|
| made_up | 337 | 337 | 337 | 0 |
| none | 746 | 746 | 746 | 746 |
| other_status | 79 | 79 | 42 | 0 |
| rumour_retracted | 255 | 255 | 0 | 0 |

Guarded agent only:

| Check | Result |
|---|---|
| Decision records the principles and a graph path | 1417 of 1417 (100.0%) |
| Advice text passes the grounding checker | 1417 of 1417 (100.0%) |
| Corrupted text caught: diagnosis | 1417 of 1417 (100.0%) |
| Corrupted text caught: invented argument | 795 of 795 (100.0%) |
| Corrupted text caught: invented day | 1417 of 1417 (100.0%) |
| Corrupted text caught: invented event | 1353 of 1353 (100.0%) |
| Corrupted text caught: stale status | 614 of 614 (100.0%) |
| Corrupted text caught: wrong person | 1350 of 1350 (100.0%) |
