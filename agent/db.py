"""Connect to FalkorDB: a server (FALKORDB_HOST set) or the embedded falkordblite."""
import os

from dotenv import load_dotenv

load_dotenv()

_client = None


def get_client():
    global _client
    if _client is not None:
        return _client
    host = os.getenv("FALKORDB_HOST")
    if host:
        from falkordb import FalkorDB

        _client = FalkorDB(host=host, port=int(os.getenv("FALKORDB_PORT", "6379")))
    else:
        try:
            from redislite.falkordb_client import FalkorDB
        except ImportError as e:  # falkordblite is not available on native Windows
            raise RuntimeError(
                "No FalkorDB found. Set FALKORDB_HOST (and FALKORDB_PORT) to a running "
                "server, or install falkordblite on Linux/macOS/WSL."
            ) from e
        _client = FalkorDB()
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
