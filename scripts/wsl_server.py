"""Run an embedded FalkorDB (falkordblite) and expose it on a TCP port.

Run inside WSL:  ~/falkor/.venv/bin/python scripts/wsl_server.py
Windows then connects with FALKORDB_HOST=localhost FALKORDB_PORT=6379.
"""
import os
import sys
import time

from redislite.falkordb_client import FalkorDB

port = os.getenv("FALKORDB_PORT", "6379")
db_file = os.path.expanduser("~/falkor/falkor.rdb")
db = FalkorDB(db_file, serverconfig={"port": port, "bind": "127.0.0.1"})
print(f"FalkorDB listening on 127.0.0.1:{port} (db file {db_file})", flush=True)
try:
    while True:
        time.sleep(3600)
except KeyboardInterrupt:
    sys.exit(0)
