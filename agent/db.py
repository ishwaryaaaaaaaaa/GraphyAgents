"""Connect to FalkorDB: a server (FALKORDB_HOST set) or the embedded falkordblite."""
import os
import sys
import threading

from dotenv import load_dotenv

load_dotenv()

_client = None
_client_lock = threading.Lock()


def _connect():
    host = os.getenv("FALKORDB_HOST")
    if host:
        from falkordb import FalkorDB

        return FalkorDB(host=host, port=int(os.getenv("FALKORDB_PORT", "6379")))
    try:
        from redislite.falkordb_client import FalkorDB
    except ImportError as e:  # falkordblite is not available on native Windows
        raise RuntimeError(
            "No FalkorDB found. Set FALKORDB_HOST (and FALKORDB_PORT) to a running "
            "server, or install falkordblite on Linux/macOS/WSL."
        ) from e
    # Loud on purpose: a process that falls back here has its OWN private database, so it will never
    # see data written by another process (a second MCP server, the chat, an evaluation run).
    print("agent.db: FALKORDB_HOST is not set, so this process is using a private embedded FalkorDB; "
          "its data is not shared with any other process.", file=sys.stderr, flush=True)
    return FalkorDB()


def get_client():
    """One shared client (its connection pool is thread-safe). Created once, even if many threads
    ask at the same moment."""
    global _client
    if _client is not None:
        return _client
    with _client_lock:
        if _client is None:
            _client = _connect()
    return _client


def graph_name(user):
    return f"user_{user}"


def get_graph(user):
    return get_client().select_graph(graph_name(user))


def drop_graph(user):
    try:
        get_graph(user).delete()
    except Exception:
        pass  # graph did not exist
