# AI use disclosure

Plain account of where AI was used in this project.

## AI tools used to build it

- **Claude Code** (an AI coding assistant) was used during the hackathon to write and refactor
  code, tests and documentation, and to run commands in the repository. The author directed the
  design (graph data model, the four memory rules, the evaluation plan), reviewed what was
  produced, and is responsible for all of it. Every commit was made by the author.
- Things generated with AI assistance: most of `agent/`, `data/generator.py`, `data/oracle.py`,
  `eval/`, `tests/`, `mcp_server.py`, `cli.py` and the first draft of this documentation.
- Things written by hand or decided by the author: the project idea and scope, the rule table
  and weights (`agent/rules.json`), the story and expected answers in `data/meera.py`, the
  food catalogue's tags, and which results to report.

## AI inside the product

- **Gemini** (optional, `LLM_MODE=on`) does two jobs only: turn a sentence into memory
  operations (`agent/extract.py`) and reword a decision (`agent/explain.py`).
- It never decides what is true and never reads the graph. Its output is checked against a
  whitelist before anything is written, and its explanation is checked against the decision
  object; on any failure the template or the regex grammar is used instead.
- **Decisions come from rules and graph queries**, not from an LLM. The evaluation runs with
  the LLM off.

## What is NOT real

- All data is fictional and synthetic. No real person's data is used anywhere.
- `tests/fixtures/extract_llm.json` holds hand-written stand-ins for model output unless it
  says it was recorded (see `scripts/record_fixtures.py`).
