"""Paste results/*.md into README.md between <!-- RESULTS:name:start/end --> markers.

    python scripts/update_readme.py

The README quotes the saved result files, never numbers typed by hand.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
README = ROOT / "README.md"
SOURCES = {"meera": "meera.md", "generated": "generated_300-499.md", "learning": "learning.md",
           "social": "social.md", "scorer": "scorer.md", "concurrency": "concurrency.md",
           "handoff": "handoff_demo.md"}

text = README.read_text(encoding="utf-8")
for name, file in SOURCES.items():
    path = ROOT / "results" / file
    if not path.exists():
        sys.exit(f"missing {path}: run run_eval.py first")
    body = re.sub(r"^### .*\n", "", path.read_text(encoding="utf-8"), count=1).strip()
    pattern = re.compile(rf"(<!-- RESULTS:{name}:start -->).*?(<!-- RESULTS:{name}:end -->)", re.S)
    if not pattern.search(text):
        sys.exit(f"README has no RESULTS:{name} markers")
    text = pattern.sub(lambda m: f"{m[1]}\n{body}\n{m[2]}", text)
README.write_text(text, encoding="utf-8")
print("README results updated from", ", ".join(SOURCES.values()))
