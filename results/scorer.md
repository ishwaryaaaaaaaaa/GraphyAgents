### Trained scorer vs rules, by memory read

Model for arms B and C: **pairwise**, chosen on a validation split inside the training seeds (896 validation questions: pairwise 99.7%, logistic 93.0%, boosting 92.3%). Trained on seeds 0-299 (5243 questions, 10694 option rows). Evaluated on seeds 300-499 (3595 questions), never used for any choice.

| Arm | Task success (95% interval) |
|---|---|
| A: guarded memory, rules | 3595 of 3595 (100.0%) [99.9-100.0] |
| B: guarded memory, scorer | 3580 of 3595 (99.6%) [99.3-99.7] |
| C: first-write read, scorer | 1861 of 3595 (51.8%) [50.1-53.4] |
| D: first-write read, rules | 1857 of 3595 (51.7%) [50.0-53.3] |
| last-write-wins read, scorer | 2820 of 3595 (78.4%) [77.1-79.8] |
| last-write-wins read, rules | 2828 of 3595 (78.7%) [77.3-80.0] |

By kind of question (task success):

| Slice | A: guarded, rules | B: guarded, scorer | C: first-write, scorer |
|---|---|---|---|
| all questions | 3595 of 3595 (100.0%) | 3580 of 3595 (99.6%) | 1861 of 3595 (51.8%) |
| stale-memory traps | 1737 of 1737 (100.0%) | 1729 of 1737 (99.5%) | 9 of 1737 (0.5%) |
| no trap | 1858 of 1858 (100.0%) | 1851 of 1858 (99.6%) | 1852 of 1858 (99.7%) |
| involve a held-out food | 1790 of 1790 (100.0%) | 1778 of 1790 (99.3%) | 872 of 1790 (48.7%) |
| only foods seen in training | 1805 of 1805 (100.0%) | 1802 of 1805 (99.8%) | 989 of 1805 (54.8%) |

With guarded memory the scorer and the rules picked different options on 15 questions: the scorer was right and the rules wrong on 0, the rules right and the scorer wrong on 15, and both wrong in different ways on 0.

All three model types on the same test questions (guarded memory). The first version of this experiment had only the pointwise models; the pairwise ranking model was added after seeing that they cannot express "better than the alternatives", and the choice between all three is made on the validation seeds only:

| Model | Task success (95% interval) |
|---|---|
| pairwise (chosen on validation) | 3580 of 3595 (99.6%) [99.3-99.7] |
| logistic | 3311 of 3595 (92.1%) [91.2-92.9] |
| boosting | 3289 of 3595 (91.5%) [90.5-92.4] |

Largest weights of the pairwise model (what it learned to like; a positive weight pushes an option up):

| Feature | Weight |
|---|---|
| rule_promise | +12.44 |
| rule_sugar_earned | +10.93 |
| rule_fried_goal | -10.66 |
| rule_likes | +10.65 |
| fried_goal_x_rank | -7.41 |
| sugar_streak | +7.25 |
| list_position | -6.52 |
| goal_rank | +3.58 |
