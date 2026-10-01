"""Global pytest fixtures for test suite isolation.

WHY THIS EXISTS:
----------------
Per Section 8 of AGENTS.md:
"Nothing in the suite may touch the real Purchasing-Log.xlsx, the real roster.json, or the network."

Per Ticket 76 / ADR 0011:
Now that lifecycle operations persist requests to requests.json via store,
every test in the suite must run with store.STORE_PATH isolated to a temporary
directory so tests running in parallel do not collide on the real requests.json file.
"""
import pytest

from src import store


@pytest.fixture(autouse=True)
def isolate_store_path(tmp_path, monkeypatch):
    """Isolate store.STORE_PATH to a temporary path for every test."""
    store_file = str(tmp_path / "requests.json")
    monkeypatch.setattr(store, "STORE_PATH", store_file)
    yield store_file
