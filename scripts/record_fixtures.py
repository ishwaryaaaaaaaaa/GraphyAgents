"""Replace the hand-written extraction fixtures with REAL model responses (needs a key).

    LLM_MODE=on GEMINI_API_KEY=... python scripts/record_fixtures.py

Run it once, then run pytest: the expectations in the fixture file must still hold. Any case
that now fails shows where the real model disagrees with our assumptions.
"""
import json
import os
import sys
from pathlib import Path

os.environ["LLM_MODE"] = "on"
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agent import extract, llm  # noqa: E402

PATH = ROOT / "tests" / "fixtures" / "extract_llm.json"
data = json.loads(PATH.read_text(encoding="utf-8"))
for case in data["cases"]:
    raw = llm.ask(extract._prompt(case["text"], case["day"]), schema=extract._SCHEMA)
    case["response"] = json.loads(raw)
    print(f"recorded: {case['name']}")
data["_note"] = f"Recorded from {llm.model()} by scripts/record_fixtures.py."
PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
