import json
import os
import sys
import tempfile
import pytest

# Determine project root and src directory
_CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(_CURRENT_DIR) if os.path.basename(_CURRENT_DIR) == "tests" else _CURRENT_DIR
SRC_DIR = os.path.join(PROJECT_ROOT, "src")
for p in (PROJECT_ROOT, SRC_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

from src import store


@pytest.fixture(autouse=True)
def temp_store_file(tmp_path, monkeypatch):
    test_store_path = str(tmp_path / "requests.json")
    monkeypatch.setattr(store, "STORE_PATH", test_store_path)
    return test_store_path


def test_store_initial_load(temp_store_file):
    assert not os.path.exists(temp_store_file)
    data = store.load_store()
    assert data == {}


def test_store_create_and_get(temp_store_file):
    req_id = store.create(
        channel="C12345",
        thread_ts="1757979000.000100",
        requester="Isaac",
        requester_id="U0A7YBJHDA8",
        rows=[18, 19],
        items=[
            {"row": 18, "description": "Lens", "vendor": "Commonlands", "price": 349.0},
            {"row": 19, "description": "Camera", "vendor": "ZWO", "price": 411.0},
        ],
    )
    assert req_id.startswith("req_")
    assert len(req_id) == 8  # "req_" (4) + 4 hex chars (4) = 8 chars

    rec = store.get(req_id)
    assert rec is not None
    assert rec["channel"] == "C12345"
    assert rec["thread_ts"] == "1757979000.000100"
    assert rec["requester"] == "Isaac"
    assert rec["rows"] == [18, 19]
    assert len(rec["items"]) == 2


def test_store_get_by_thread(temp_store_file):
    req_id = store.create(
        channel="C_MAIN",
        thread_ts="100.200",
        requester="Dylan",
        rows=[25],
    )

    found = store.get_by_thread("C_MAIN", "100.200")
    assert found is not None
    assert found["request_id"] == req_id
    assert found["requester"] == "Dylan"

    # Non-existent thread
    assert store.get_by_thread("C_MAIN", "999.999") is None


def test_store_update_and_append_history(temp_store_file):
    req_id = store.create(
        channel="C_MAIN",
        thread_ts="100.300",
        requester="Charlie",
        rows=[30],
    )

    # Update buyer
    updated = store.update(req_id, buyer="Dylan", buyer_id="U_DYLAN")
    assert updated["buyer"] == "Dylan"
    assert updated["buyer_id"] == "U_DYLAN"

    # Append history
    store.append_history(req_id, "Claimed by Dylan on 09/15/26 15:00")
    rec = store.get(req_id)
    assert len(rec["history"]) == 1
    assert "Claimed by Dylan" in rec["history"][0]


def test_store_delete(temp_store_file):
    req_id = store.create(
        channel="C_MAIN",
        thread_ts="100.400",
        requester="Isaac",
        rows=[35],
    )
    assert store.get(req_id) is not None

    deleted = store.delete(req_id)
    assert deleted is True
    assert store.get(req_id) is None
    assert store.delete(req_id) is False


def test_store_corrupted_file_recovery(temp_store_file):
    # Write invalid JSON to store file
    with open(temp_store_file, "w") as f:
        f.write("{invalid json content ...")

    alert_called = False
    alert_msg = ""

    def mock_alert(msg):
        nonlocal alert_called, alert_msg
        alert_called = True
        alert_msg = msg

    data = store.load_store(alert_callback=mock_alert)
    assert data == {}
    assert alert_called is True
    assert "corrupted and moved" in alert_msg

    # Verify .bad copy exists
    bad_file = temp_store_file + ".bad"
    assert os.path.exists(bad_file)
    with open(bad_file, "r") as f:
        assert "{invalid json content" in f.read()
