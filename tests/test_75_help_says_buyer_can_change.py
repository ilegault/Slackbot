"""Tests for ticket 75 — App Home says the buyer can be changed until Processed.

Acceptance criteria:
- blocks.get_help_message() contains 'until it is *Processed*' and does not contain
  '@Purchasing assign @themselves'.
- The JSON of blocks.build_app_home_view("U_ANY") contains 'until it is *Processed*'
  and does not contain '@Purchasing assign @themselves'.
"""
import json

import blocks


def test_get_help_message_buyer_can_change_until_processed():
    msg = blocks.get_help_message()
    assert "until it is *Processed*" in msg
    assert "@Purchasing assign @themselves" not in msg


def test_build_app_home_view_buyer_can_change_until_processed():
    view_json = json.dumps(blocks.build_app_home_view("U_ANY"))
    assert "until it is *Processed*" in view_json
    assert "@Purchasing assign @themselves" not in view_json
