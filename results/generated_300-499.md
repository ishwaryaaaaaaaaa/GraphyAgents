### Generated lives, seeds 300-499 (test split)

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
