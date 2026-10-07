"""Tests for Ticket 100: Only real EPIFs count when a thread is searched.

WHY THIS EXISTS:
----------------
Ticket 100 / ADR 0015 Decisions 2 and 4:
Prevents quotes, BOMs, or bot-uploaded files in a thread from being parsed as EPIFs
when an approver approves via @Purchasing approved. Real AcroForm EPIFs are classified
as 'epifs', attached spreadsheets as 'boms', flattened EPIFs as 'flattened_epifs', and
all other PDFs as 'quotes'.
"""
import datetime
import io
import os
from unittest.mock import MagicMock

from pypdf import PdfWriter

from src import app, epif_filler, epif_parser, lifecycle, log_writer, queue_worker, roster, slack_io

FIXTURE_PATH = os.path.join(
    os.path.dirname(__file__), "fixtures", "EPIF_TEMPLATE_HIRST.pdf"
)


# ---------------------------------------------------------------------------
# Criterion 1: is_epif_form tests
# ---------------------------------------------------------------------------

def test_is_epif_form_with_fixture_and_negative_cases():
    """is_epif_form is True on the real EPIF template, False on {} and non-EPIF dicts."""
    with open(FIXTURE_PATH, "rb") as f:
        pdf_bytes = f.read()

    fields = epif_parser.read_fields(pdf_bytes)
    assert epif_parser.is_epif_form(fields) is True

    assert epif_parser.is_epif_form({}) is False
    assert epif_parser.is_epif_form({"Total": "1"}) is False
    assert epif_parser.is_epif_form({"Amount of Purchase": "100.00"}) is False
    assert epif_parser.is_epif_form({"Vendor": "Acme"}) is False
    assert epif_parser.is_epif_form({"Amount of Purchase": "100.00", "Vendor": "Acme"}) is True


# ---------------------------------------------------------------------------
# Criterion 2: classify_thread_files rules on plain message dicts
# ---------------------------------------------------------------------------

def test_classify_thread_files_skips_bot_user():
    """Bot-posted PDF by user is skipped."""
    messages = [
        {"user": "B_BOT", "ts": "100.0", "files": [{"name": "form.pdf"}]}
    ]
    read_fields = MagicMock(return_value={"Amount of Purchase": "10", "Vendor": "V"})
    result = slack_io.classify_thread_files(messages, "B_BOT", read_fields)
    assert result == {"epifs": [], "boms": [], "quotes": [], "flattened_epifs": []}
    read_fields.assert_not_called()


def test_classify_thread_files_skips_bot_id():
    """Bot-posted PDF by bot_id is skipped."""
    messages = [
        {"user": "U_OTHER", "bot_id": "B_APP_123", "ts": "100.0", "files": [{"name": "form.pdf"}]}
    ]
    read_fields = MagicMock(return_value={"Amount of Purchase": "10", "Vendor": "V"})
    result = slack_io.classify_thread_files(messages, "B_BOT", read_fields)
    assert result == {"epifs": [], "boms": [], "quotes": [], "flattened_epifs": []}
    read_fields.assert_not_called()


def test_classify_thread_files_person_epif():
    """A person's EPIF PDF is classified into 'epifs'."""
    file_obj = {"name": "sample_epif.pdf", "id": "F1"}
    messages = [
        {"user": "U_PERSON", "ts": "100.0", "files": [file_obj]}
    ]
    read_fields = MagicMock(return_value={"Amount of Purchase": "50.0", "Vendor": "Airgas"})
    result = slack_io.classify_thread_files(messages, "B_BOT", read_fields)
    assert result["epifs"] == [{"file": file_obj, "user": "U_PERSON", "ts": "100.0"}]
    assert result["boms"] == []
    assert result["quotes"] == []
    assert result["flattened_epifs"] == []


def test_classify_thread_files_formless_quote():
    """A person's form-less PDF named 'Quote 27732.pdf' is classified into 'quotes'."""
    file_obj = {"name": "Quote 27732.pdf", "id": "F2"}
    messages = [
        {"user": "U_PERSON", "ts": "100.0", "files": [file_obj]}
    ]
    read_fields = MagicMock(return_value={})
    result = slack_io.classify_thread_files(messages, "B_BOT", read_fields)
    assert result["quotes"] == [{"file": file_obj, "user": "U_PERSON", "ts": "100.0"}]
    assert result["epifs"] == []
    assert result["boms"] == []
    assert result["flattened_epifs"] == []


def test_classify_thread_files_flattened_epif():
    """A form-less 'Smith_EPIF.pdf' is classified into 'flattened_epifs'."""
    file_obj = {"name": "Smith_EPIF.pdf", "id": "F3"}
    messages = [
        {"user": "U_PERSON", "ts": "100.0", "files": [file_obj]}
    ]
    read_fields = MagicMock(return_value={})
    result = slack_io.classify_thread_files(messages, "B_BOT", read_fields)
    assert result["flattened_epifs"] == [{"file": file_obj, "user": "U_PERSON", "ts": "100.0"}]
    assert result["epifs"] == []
    assert result["boms"] == []
    assert result["quotes"] == []


def test_classify_thread_files_boms():
    """bom.xlsx and BOM.CSV are classified into 'boms', case-insensitively, without reading fields."""
    file_xlsx = {"name": "bom.xlsx", "id": "F4"}
    file_csv = {"name": "BOM.CSV", "id": "F5"}
    messages = [
        {"user": "U_PERSON", "ts": "100.0", "files": [file_xlsx, file_csv]}
    ]
    read_fields = MagicMock()
    result = slack_io.classify_thread_files(messages, "B_BOT", read_fields)
    assert result["boms"] == [
        {"file": file_xlsx, "user": "U_PERSON", "ts": "100.0"},
        {"file": file_csv, "user": "U_PERSON", "ts": "100.0"},
    ]
    assert result["epifs"] == []
    assert result["quotes"] == []
    assert result["flattened_epifs"] == []
    read_fields.assert_not_called()


def test_classify_thread_files_skips_png():
    """Non-PDF/Excel/CSV files (e.g. .png) are skipped."""
    messages = [
        {"user": "U_PERSON", "ts": "100.0", "files": [{"name": "screenshot.png", "id": "F6"}]}
    ]
    read_fields = MagicMock()
    result = slack_io.classify_thread_files(messages, "B_BOT", read_fields)
    assert result == {"epifs": [], "boms": [], "quotes": [], "flattened_epifs": []}
    read_fields.assert_not_called()


def test_classify_thread_files_skips_quote_command_message():
    """A PDF on a <@BOT> quote message is skipped."""
    file_obj = {"name": "Quote.pdf", "id": "F7"}
    messages = [
        {
            "user": "U_PERSON",
            "ts": "100.0",
            "text": "<@B_BOT> quote here is the quote",
            "files": [file_obj],
        }
    ]
    read_fields = MagicMock()
    result = slack_io.classify_thread_files(messages, "B_BOT", read_fields)
    assert result == {"epifs": [], "boms": [], "quotes": [], "flattened_epifs": []}
    read_fields.assert_not_called()


def test_classify_thread_files_order_oldest_first():
    """Classified lists maintain oldest-first order by message timestamp."""
    file_newer = {"name": "epif_newer.pdf", "id": "F_NEW"}
    file_older = {"name": "epif_older.pdf", "id": "F_OLD"}
    messages = [
        {"user": "U_PERSON", "ts": "200.0", "files": [file_newer]},
        {"user": "U_PERSON", "ts": "100.0", "files": [file_older]},
    ]
    read_fields = MagicMock(return_value={"Amount of Purchase": "10", "Vendor": "Acme"})
    result = slack_io.classify_thread_files(messages, "B_BOT", read_fields)
    assert len(result["epifs"]) == 2
    assert result["epifs"][0]["file"] == file_older
    assert result["epifs"][1]["file"] == file_newer


# ---------------------------------------------------------------------------
# Criterion 3: Driving handle_epif_processing with only Quote.pdf
# ---------------------------------------------------------------------------

def _create_blank_pdf_bytes() -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    stream = io.BytesIO()
    writer.write(stream)
    return stream.getvalue()


def test_handle_epif_processing_thread_with_only_quote_posts_bare_thread_reply(monkeypatch):
    """Keyword approval on a thread with only Quote.pdf posts bare-thread reply, no Error processing."""
    client = MagicMock()
    say = MagicMock()

    blank_bytes = _create_blank_pdf_bytes()
    quote_file = {
        "name": "Quote.pdf",
        "id": "F_QUOTE",
        "url_private_download": "https://slack.test/quote.pdf",
    }

    client.auth_test.return_value = {"ok": True, "user_id": "B_BOT"}
    client.conversations_replies.return_value = {
        "messages": [
            {
                "user": "U_REQUESTER",
                "ts": "100.0",
                "text": "Can we order this?",
                "files": [quote_file],
            }
        ]
    }

    # Real classification and parser must be used, download returns real PDF bytes
    monkeypatch.setattr(slack_io, "download", lambda f: blank_bytes)
    monkeypatch.setattr(slack_io, "get_thread_parent_author", lambda cl, ch, ts: "U_REQUESTER")
    monkeypatch.setattr(slack_io, "resolve_requester", lambda cl, uid: "Katarina")
    monkeypatch.setattr(slack_io, "find_card_in_thread", lambda *a, **kw: (None, None, [], None))
    monkeypatch.setattr(slack_io, "find_request_metadata_in_thread", lambda *a, **kw: (None, None, None, False))

    lifecycle.handle_epif_processing(
        client=client,
        say=say,
        channel="C123",
        thread_ts="100.0",
        approver="Charlie",
        event_ts="100.1",
    )

    # Assert exactly one thread reply with bare-thread wording
    say.assert_called_once()
    reply_text = say.call_args[1]["text"]
    assert "✅ Approved by Charlie. No EPIF in this thread" in reply_text
    assert "treating this as a *Workday order*" in reply_text
    assert "<@U_REQUESTER>" in reply_text

    # Assert no text starting with 'Error processing' was posted
    for call in say.call_args_list:
        text = call[1].get("text", "")
        assert not text.startswith("Error processing")

    # Assert waiting_for_details card was posted
    client.chat_postMessage.assert_called_once()
    post_kwargs = client.chat_postMessage.call_args[1]
    assert "Approved — waiting for details" in post_kwargs["text"]


# ---------------------------------------------------------------------------
# Criterion 4: Person's EPIF followed by newer Quote PDF approves the EPIF
# ---------------------------------------------------------------------------

def test_thread_epif_followed_by_newer_quote_approves_epif(monkeypatch):
    """A thread holding a person's EPIF followed by a newer quote PDF approves the EPIF."""
    client = MagicMock()
    say = MagicMock()

    with open(FIXTURE_PATH, "rb") as f:
        template_bytes = f.read()

    epif_data = {
        "item_description": "Lab Gas Cylinder",
        "purpose": "Research in lab",
        "total_price": 450.0,
        "vendor": "Airgas",
        "vendor_contact_name": "Jane Gas",
        "vendor_contact_email": "jane@airgas.com",
        "date_of_purchase": datetime.date(2026, 9, 23),
        "name_of_system": "Laser",
        "delivery_room": "ERB 212",
        "project_id": "PG000025831",
        "fund": "133",
        "category": "Research/Lab Supplies (3105)",
        "payment_method": "P-card",
    }
    epif_bytes = epif_filler.fill_epif(template_bytes, epif_data)
    blank_quote_bytes = _create_blank_pdf_bytes()

    epif_file = {
        "name": "Airgas_EPIF.pdf",
        "id": "F_EPIF",
        "url_private_download": "https://slack.test/epif.pdf",
    }
    quote_file = {
        "name": "Quote 9876.pdf",
        "id": "F_QUOTE",
        "url_private_download": "https://slack.test/quote.pdf",
    }

    client.auth_test.return_value = {"ok": True, "user_id": "B_BOT"}
    client.conversations_replies.return_value = {
        "messages": [
            {
                "user": "U_REQUESTER",
                "ts": "100.0",
                "text": "Here is the EPIF",
                "files": [epif_file],
            },
            {
                "user": "U_REQUESTER",
                "ts": "200.0",
                "text": "And here is the quote",
                "files": [quote_file],
            },
        ]
    }

    def fake_download(file_obj):
        if file_obj.get("name") == "Airgas_EPIF.pdf" or file_obj.get("id") == "F_EPIF":
            return epif_bytes
        return blank_quote_bytes

    monkeypatch.setattr(slack_io, "download", fake_download)
    monkeypatch.setattr(slack_io, "resolve_requester", lambda cl, uid: "Katarina")
    monkeypatch.setattr(slack_io, "find_card_in_thread", lambda *a, **kw: (None, None, [], None))
    monkeypatch.setattr(roster, "is_buyer", lambda uid: True)

    captured_rows = []
    monkeypatch.setattr(log_writer, "build_row", lambda p, r: captured_rows.append(p) or {"I": p["vendor"]})
    monkeypatch.setattr(log_writer, "append_row", lambda row, path=None: 1)
    monkeypatch.setattr(log_writer, "save_epif", lambda b, f: f"EPIFs/{f}")
    monkeypatch.setattr(
        queue_worker,
        "submit_write_task",
        lambda action_fn, channel, thread_ts, user_id, task_type, description, success_callback, failure_callback, client=None: success_callback(action_fn()),
    )

    lifecycle.handle_epif_processing(
        client=client,
        say=say,
        channel="C123",
        thread_ts="100.0",
        approver="Charlie",
        event_ts="250.0",
    )

    # Assert row was created and vendor comes from the EPIF
    assert len(captured_rows) == 1
    assert captured_rows[0]["vendor"] == "Airgas"


# ---------------------------------------------------------------------------
# Criterion 5: get_bot_user_id and slack_io.bot_user_id caching
# ---------------------------------------------------------------------------

def test_slack_io_bot_user_id_caching(monkeypatch):
    """slack_io.bot_user_id calls auth_test once across two calls (cached)."""
    monkeypatch.setattr(slack_io, "_CACHED_BOT_USER_ID", None)
    client = MagicMock()
    client.auth_test.return_value = {"ok": True, "user_id": "B_BOT_99"}

    first = slack_io.bot_user_id(client)
    assert first == "B_BOT_99"
    client.auth_test.assert_called_once()

    second = slack_io.bot_user_id(client)
    assert second == "B_BOT_99"
    client.auth_test.assert_called_once()


def test_app_get_bot_user_id_delegates(monkeypatch):
    """app.get_bot_user_id delegates to slack_io.bot_user_id and honors context shortcut."""
    monkeypatch.setattr(slack_io, "_CACHED_BOT_USER_ID", None)
    # Context shortcut
    ctx_res = app.get_bot_user_id(None, context={"bot_user_id": "B_CTX"})
    assert ctx_res == "B_CTX"

    # Client delegation
    monkeypatch.setattr(slack_io, "_CACHED_BOT_USER_ID", None)
    client = MagicMock()
    client.auth_test.return_value = {"ok": True, "user_id": "B_CLIENT"}
    client_res = app.get_bot_user_id(client)
    assert client_res == "B_CLIENT"
    client.auth_test.assert_called_once()
