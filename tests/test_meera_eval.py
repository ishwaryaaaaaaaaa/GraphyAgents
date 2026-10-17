"""The submit-gate numbers, as tests."""
import pytest

from agent import store
from data import meera
from eval import metrics, replay


@pytest.fixture(scope="module")
def summary():
    user = "meera_test"
    run = replay.replay(user, meera.STEPS)
    store.reset(user)
    return metrics.summarise([run])


def test_guarded_agent_answers_every_question_with_zero_stale_uses(summary):
    g = summary["arms"]["guarded"]
    assert g["task_success"]["k"] == g["task_success"]["n"] == 15
    assert g["stale_use"]["k"] == 0 and g["wrongful_keep"]["k"] == 0


def test_baselines_are_worse_and_fail_where_the_theory_says(summary):
    fw, lww = summary["arms"]["first_write"], summary["arms"]["last_write_wins"]
    assert fw["task_success"]["k"] < lww["task_success"]["k"] < 15
    by = summary["by_trap"]
    # last-write-wins fixes supersede but not cascade, retraction or ended goals
    for trap in ("diet_change", "taste_flip", "double_change"):
        assert by[trap]["last_write_wins"] == by[trap]["n"]
    for trap in ("cascade", "retraction", "goal_ended"):
        assert by[trap]["last_write_wins"] == 0
        assert by[trap]["guarded"] == by[trap]["n"]


def test_guarded_only_metrics_are_perfect(summary):
    g = summary["guarded_only"]
    assert g["wrongful_drop"]["k"] == 0
    for m in ("cascade_completeness", "time_travel", "audit_coverage"):
        assert g[m]["k"] == g[m]["n"] and g[m]["n"] > 0


def test_wilson_interval_sanity():
    lo, hi = metrics.wilson(15, 15)
    assert hi == 1.0 and 0.75 < lo < 0.85
    assert metrics.wilson(0, 0) == (0.0, 0.0)
