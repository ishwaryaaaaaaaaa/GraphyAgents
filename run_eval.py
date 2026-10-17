"""Evaluation runner.

    python run_eval.py --set meera                      hand-written 55-day life
    python run_eval.py --set generated --seeds 300-499  held-out generated lives (test split)

Writes results/<set>.json and results/<set>.md. Exit code is 0 only if the guarded agent used
no stale fact. Disagreements with the oracle are saved for a person to triage.
"""
import argparse
import json
import sys
import time

from agent import store
from data import generator, meera
from eval import metrics, report, replay


def run_meera():
    user = "meera"
    try:
        run = replay.replay(user, meera.STEPS)
    finally:
        store.reset(user)
    summary = metrics.summarise([run])
    return report.save("meera", "Meera: hand-written 55-day life", summary, [run]), summary


def run_learning():
    from eval import learning
    results = learning.run_all()
    md = "### Learning from outcomes (simulated users)\n\n" + learning.to_markdown(results) + "\n"
    report.RESULTS.mkdir(exist_ok=True)
    (report.RESULTS / "learning.md").write_text(md, encoding="utf-8")
    (report.RESULTS / "learning.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    return md, results


def parse_seeds(text):
    lo, _, hi = text.partition("-")
    return range(int(lo), int(hi or lo) + 1)


def run_generated(seeds, quiet=False):
    runs, disagreements, start = [], [], time.time()
    for i, seed in enumerate(seeds):
        life = generator.generate(seed)
        user = f"gen{seed}"
        try:
            run = replay.replay(user, life["steps"])
        finally:
            store.reset(user)
        run["seed"] = seed
        runs.append(run)
        for a in run["asks"]:
            if not a["arms"]["guarded"]["ok"]:
                disagreements.append({"seed": seed, "id": a["id"], "day": a["day"],
                                      "options": a["options"], "trap": a["trap"],
                                      "oracle": a["expect"], "agent": a["arms"]["guarded"]["pick"],
                                      "reasons": a["reasons"]})
        for k in ("cascade", "time_travel"):
            for item in run[k]:
                if not item["ok"]:
                    disagreements.append({"seed": seed, "kind": k, **item})
        if not quiet and (i + 1) % 20 == 0:
            print(f"  {i + 1}/{len(seeds)} lives, {time.time() - start:.0f}s", file=sys.stderr)
    name = f"generated_{seeds.start}-{seeds[-1]}"
    summary = metrics.summarise(runs)
    title = f"Generated lives, seeds {seeds.start}-{seeds[-1]} ({generator.split_of(seeds.start)} split)"
    md = report.save(name, title, summary, [{k: v for k, v in r.items()} for r in runs])
    (report.RESULTS / f"{name}_disagreements.json").write_text(
        json.dumps(disagreements, indent=2), encoding="utf-8")
    return md + f"\nDisagreements with the oracle: {len(disagreements)} (see results/{name}_disagreements.json)\n", summary


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", choices=["meera", "generated", "learning"], default="meera")
    ap.add_argument("--seeds", default="300-499", help="range for --set generated, e.g. 300-499")
    args = ap.parse_args(argv)
    if args.set == "meera":
        md, summary = run_meera()
    elif args.set == "learning":
        md, summary = run_learning()
    else:
        md, summary = run_generated(parse_seeds(args.seeds))
    print(md)
    return summary


if __name__ == "__main__":
    s = main()
    ok = isinstance(s, list) or s["arms"]["guarded"]["stale_use"]["k"] == 0
    sys.exit(0 if ok else 1)
