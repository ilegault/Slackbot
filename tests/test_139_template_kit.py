"""Ticket 139: /blank-template sends the template kit privately.

The kit (guide + blank EPIF + BOM template) is one DM to the asker. Where they typed the
command they get a note only they can see; nothing is ever posted publicly. The Slack
client, ack and respond are faked; ops.send_template_kit, the handler, slack_io, text_rules
and the committed BOM template are real.
"""
from unittest.mock import MagicMock

import pytest

from src import app, blocks, config, ops, text_rules

EPIF_NAME = "EPIF_TEMPLATE_HIRST.pdf"
BOM_NAME = "HIRST_LAB_BOM_TEMPLATE.xlsx"
BOM_MISSING_LINE = "⚠️ The BOM template could not be attached. An admin has been told."
EPIF_MISSING_LINE = "⚠️ The blank EPIF template could not be attached. An admin has been told."


@pytest.fixture
def client():
    c = MagicMock()
    c.conversations_open.return_value = {"channel": {"id": "D_ASKER"}}
    return c


@pytest.fixture(autouse=True)
def _config(tmp_path, monkeypatch):
    epif = tmp_path / "epif.pdf"
    epif.write_bytes(b"%PDF-1.4 fake")
    monkeypatch.setattr(config, "EPIF_TEMPLATE_PATH", str(epif))
    monkeypatch.setattr(config, "ADMIN_ALERT_CHANNEL", "C_ADMIN")


def _channels(client):
    return [
        c.kwargs.get("channel")
        for c in client.chat_postMessage.call_args_list + client.files_upload_v2.call_args_list
    ]


def _run(client, channel_id, respond=None):
    respond = respond or MagicMock()
    ack = MagicMock()
    app.handle_blank_template_command(ack, {"channel_id": channel_id, "user_id": "U1"}, respond, client)
    ack.assert_called_once()
    return respond


def test_kit_is_one_dm_with_both_files(client):
    assert ops.send_template_kit(client, "U1") == "D_ASKER"
    client.files_upload_v2.assert_called_once()
    kw = client.files_upload_v2.call_args.kwargs
    assert kw["channel"] == "D_ASKER"
    assert [u["filename"] for u in kw["file_uploads"]] == [EPIF_NAME, BOM_NAME]
    for needle in ("Hirst Lab Manual EPIF Submission Kit", "Two or more items?", BOM_NAME):
        assert needle in kw["initial_comment"]
    assert "could not be attached" not in kw["initial_comment"]
    client.chat_postMessage.assert_not_called()


def test_command_in_a_channel_is_private(client):
    respond = _run(client, "C_PURCH")
    assert "C_PURCH" not in _channels(client)
    assert client.files_upload_v2.call_count == 1
    respond.assert_called_once()
    kw = respond.call_args.kwargs
    assert kw["response_type"] == "ephemeral"
    assert "Sent the EPIF and BOM templates to" in kw["text"]
    assert "https://slack.com/app_redirect?channel=D_ASKER" in kw["text"]


def test_note_only_skipped_in_own_bot_dm(client):
    respond = _run(client, "D_ASKER")
    assert client.files_upload_v2.call_count == 1
    respond.assert_not_called()

    client.reset_mock()
    client.conversations_open.return_value = {"channel": {"id": "D_ASKER"}}
    respond = _run(client, "D_SOMEONE_ELSE")
    assert client.files_upload_v2.call_count == 1
    respond.assert_called_once()
    assert "Sent the EPIF and BOM templates to" in respond.call_args.kwargs["text"]


def test_missing_template_still_sends_the_rest(client, tmp_path, monkeypatch):
    missing_bom = str(tmp_path / "gone.xlsx")
    monkeypatch.setattr(config, "BOM_TEMPLATE_PATH", missing_bom)

    ops.send_template_kit(client, "U1")
    client.files_upload_v2.assert_called_once()
    kw = client.files_upload_v2.call_args.kwargs
    assert [u["filename"] for u in kw["file_uploads"]] == [EPIF_NAME]
    assert BOM_MISSING_LINE in kw["initial_comment"]
    assert EPIF_MISSING_LINE not in kw["initial_comment"]
    client.chat_postMessage.assert_called_once()
    alert = client.chat_postMessage.call_args.kwargs
    assert alert["channel"] == "C_ADMIN"
    assert alert["text"] == text_rules.storage_problem_message("BOM_TEMPLATE_PATH", missing_bom, "does not exist")

    client.reset_mock()
    client.conversations_open.return_value = {"channel": {"id": "D_ASKER"}}
    monkeypatch.setattr(config, "EPIF_TEMPLATE_PATH", "")
    ops.send_template_kit(client, "U1")
    client.files_upload_v2.assert_not_called()
    posts = client.chat_postMessage.call_args_list
    dm = [c.kwargs for c in posts if c.kwargs["channel"] == "D_ASKER"]
    assert len(dm) == 1
    for needle in ("Hirst Lab Manual EPIF Submission Kit", BOM_MISSING_LINE, EPIF_MISSING_LINE):
        assert needle in dm[0]["text"]
    alerts = [c.kwargs for c in posts if c.kwargs["channel"] == "C_ADMIN"]
    assert len(alerts) == 2
    assert "EPIF_TEMPLATE_PATH" in alerts[0]["text"] and "not set" in alerts[0]["text"]
    assert "BOM_TEMPLATE_PATH" in alerts[1]["text"]


def test_dm_failure_is_private_and_help_line(client):
    client.conversations_open.side_effect = Exception("cannot_dm_bot")
    respond = _run(client, "C_PURCH")
    assert "C_PURCH" not in _channels(client)
    respond.assert_called_once()
    kw = respond.call_args.kwargs
    assert kw["response_type"] == "ephemeral"
    assert "I couldn't DM you the templates. Ask an admin." in kw["text"]

    assert (
        "`/blank-template` — DMs you the blank EPIF PDF and the lab BOM template, with instructions."
        in blocks.get_help_message()
    )
