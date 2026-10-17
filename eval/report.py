"""Print the result tables and save results/results.json and results/results.md."""
import json
from pathlib import Path

RESULTS = Path(__file__).resolve().parent.parent / "results"
LABELS = {"guarded": "guarded (agent)", "last_write_wins": "last-write-wins (no guard)",
          "first_write": "first-write (no guard)"}


def _cell(r):
    return f"{r['k']} of {r['n']} ({r['pct']}%)"


def to_markdown(title, s):
    lines = [f"### {title}", "", f"{s['questions']} questions. 95% Wilson interval in brackets.", "",
             "| Reader | Task success | Stale-use | Wrongful-keep |", "|---|---|---|---|"]
    for arm, m in s["arms"].items():
        lines.append("| {} | {} [{}-{}] | {} [{}-{}] | {} |".format(
            LABELS.get(arm, arm),
            _cell(m["task_success"]), *m["task_success"]["ci"],
            _cell(m["stale_use"]), *m["stale_use"]["ci"],
            _cell(m["wrongful_keep"])))
    lines += ["", "Task success by trap type (correct answers out of n):", "",
              "| Trap | n | " + " | ".join(LABELS.get(a, a) for a in s["arms"]) + " |",
              "|---|---|" + "---|" * len(s["arms"])]
    for trap, row in s["by_trap"].items():
        lines.append(f"| {trap} | {row['n']} | " + " | ".join(str(row[a]) for a in s["arms"]) + " |")
    g = s["guarded_only"]
    lines += ["", "Guarded agent only:", "", "| Metric | Result |", "|---|---|",
              f"| Wrongful-drop (active fact hidden) | {_cell(g['wrongful_drop'])} |",
              f"| Cascade completeness | {_cell(g['cascade_completeness'])} |",
              f"| Time-travel accuracy | {_cell(g['time_travel'])} |",
              f"| Audit coverage | {_cell(g['audit_coverage'])} |", ""]
    return "\n".join(lines)


def save(name, title, summary, runs):
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / f"{name}.json").write_text(
        json.dumps({"summary": summary, "runs": runs}, indent=2, default=str), encoding="utf-8")
    md = to_markdown(title, summary)
    (RESULTS / f"{name}.md").write_text(md, encoding="utf-8")
    return md
