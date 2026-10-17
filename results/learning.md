### Learning from outcomes (simulated users)

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
