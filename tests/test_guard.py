"""The guard: no code outside tools.py / store.py may match Fact nodes directly."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# schema.py only holds CREATE INDEX statements (DDL), never a read of facts.
ALLOWED = {"tools.py", "store.py", "schema.py"}
FACT_MATCH = re.compile(r"\(\s*\w*\s*:\s*Fact\b")


def test_fact_nodes_are_only_matched_in_tools_and_store():
    offenders = []
    for path in ROOT.rglob("*.py"):
        if ".venv" in path.parts or path.name in ALLOWED or path.parent.name == "tests":
            continue
        if FACT_MATCH.search(path.read_text(encoding="utf-8")):
            offenders.append(str(path.relative_to(ROOT)))
    assert offenders == [], f"Fact queried outside tools.py/store.py: {offenders}"


def test_every_tools_read_of_facts_carries_a_status_filter():
    src = (ROOT / "agent" / "tools.py").read_text(encoding="utf-8")
    for fn in ("get_facts", "get_fact"):
        body = src.split(f"def {fn}(")[1].split("\ndef ")[0]
        assert "_LIVE" in body, f"{fn} must use the active-status guard"
