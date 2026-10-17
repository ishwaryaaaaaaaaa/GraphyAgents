#!/usr/bin/env bash
# One-time setup for running FalkorDB inside WSL (no Docker, no sudo).
# falkordblite does not build on native Windows, so we host it in WSL and
# reach it from Windows over localhost:6379.
set -euo pipefail
mkdir -p "$HOME/falkor"
cd "$HOME/falkor"
[ -d .venv ] || python3 -m venv .venv
. .venv/bin/activate
pip install --quiet --upgrade pip
pip install --quiet falkordblite
python - <<'PY'
import redislite, inspect
from redislite.falkordb_client import FalkorDB
print("falkordblite ok:", getattr(redislite, "__version__", "?"))
print(inspect.signature(FalkorDB.__init__))
PY
