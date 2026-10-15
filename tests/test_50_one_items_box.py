"""Ticket 50: one items box everywhere. Real builders, real parser; only inputs are faked."""


from src import blocks


def _views():
    return {
        "items": blocks.build_items_view("C1", "T1", "CT1"),
        "workday": blocks.build_workday_details_view("C1", "T1", "CT1", ["Grainger"]),
    }


def _box(view):
    found = [b for b in view["blocks"] if b.get("block_id") == "block_line_items"]
    assert len(found) == 1
    return found[0]


